"""Tests for loopback transport and WebSocket endpoint."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from starlette.websockets import WebSocketState

# ---------------------------------------------------------------------------
# LoopbackTransport unit tests
# ---------------------------------------------------------------------------


class TestLoopbackTransportFraming:
    """Serial framing round-trip tests (0x3c + 2-byte LE size)."""

    def _make_transport(self, mode="serial"):
        from app.loopback import LoopbackTransport

        ws = MagicMock()
        ws.client_state = WebSocketState.CONNECTED
        ws.send_bytes = AsyncMock()
        ws.send_json = AsyncMock()
        return LoopbackTransport(ws, mode), ws

    @pytest.mark.asyncio
    async def test_send_serial_adds_framing(self):
        """send() in serial mode prepends 0x3c + 2-byte LE size."""
        transport, ws = self._make_transport("serial")
        payload = b"\x01\x02\x03\x04\x05"

        await transport.send(payload)

        expected = b"\x3c\x05\x00\x01\x02\x03\x04\x05"
        ws.send_bytes.assert_awaited_once_with(expected)

    @pytest.mark.asyncio
    async def test_send_ble_raw(self):
        """send() in BLE mode sends raw bytes (no framing)."""
        transport, ws = self._make_transport("ble")
        payload = b"\x01\x02\x03"

        await transport.send(payload)

        ws.send_bytes.assert_awaited_once_with(payload)

    def test_handle_rx_serial_strips_framing(self):
        """handle_rx in serial mode strips 0x3c header and delivers payload."""
        transport, _ = self._make_transport("serial")
        reader = MagicMock()
        reader.handle_rx = AsyncMock()
        transport.set_reader(reader)

        payload = b"\xaa\xbb\xcc"
        # Build framed data: 0x3c + 2-byte LE size + payload
        framed = b"\x3c" + len(payload).to_bytes(2, "little") + payload

        with patch("app.loopback.asyncio.create_task") as mock_task:
            transport.handle_rx(framed)

        # reader.handle_rx should be called with the payload only
        mock_task.assert_called_once()
        assert reader.handle_rx.call_count == 1
        assert reader.handle_rx.call_args[0][0] == payload

    def test_handle_rx_serial_incremental(self):
        """handle_rx in serial mode handles data arriving byte by byte."""
        transport, _ = self._make_transport("serial")
        reader = MagicMock()
        reader.handle_rx = AsyncMock()
        transport.set_reader(reader)

        payload = b"\x01\x02"
        framed = b"\x3c" + len(payload).to_bytes(2, "little") + payload

        with patch("app.loopback.asyncio.create_task") as mock_task:
            # Feed one byte at a time
            for byte in framed:
                transport.handle_rx(bytes([byte]))

        mock_task.assert_called_once()
        assert reader.handle_rx.call_args[0][0] == payload

    def test_handle_rx_serial_multiple_frames(self):
        """handle_rx handles two frames concatenated in one chunk."""
        transport, _ = self._make_transport("serial")
        reader = MagicMock()
        reader.handle_rx = AsyncMock()
        transport.set_reader(reader)

        p1 = b"\x01\x02"
        p2 = b"\x03\x04\x05"
        framed = (
            b"\x3c"
            + len(p1).to_bytes(2, "little")
            + p1
            + b"\x3c"
            + len(p2).to_bytes(2, "little")
            + p2
        )

        with patch("app.loopback.asyncio.create_task") as mock_task:
            transport.handle_rx(framed)

        assert mock_task.call_count == 2
        assert reader.handle_rx.call_args_list[0][0][0] == p1
        assert reader.handle_rx.call_args_list[1][0][0] == p2

    def test_handle_rx_ble_passthrough(self):
        """handle_rx in BLE mode passes raw bytes to reader directly."""
        transport, _ = self._make_transport("ble")
        reader = MagicMock()
        reader.handle_rx = AsyncMock()
        transport.set_reader(reader)

        data = b"\xde\xad\xbe\xef"

        with patch("app.loopback.asyncio.create_task") as mock_task:
            transport.handle_rx(data)

        mock_task.assert_called_once()
        assert reader.handle_rx.call_args[0][0] == data

    @pytest.mark.asyncio
    async def test_connect_returns_info_string(self):
        """connect() returns a descriptive string."""
        transport, _ = self._make_transport("serial")
        result = await transport.connect()
        assert "Loopback" in result
        assert "serial" in result

    @pytest.mark.asyncio
    async def test_disconnect_sends_json(self):
        """disconnect() sends a disconnect JSON message."""
        transport, ws = self._make_transport("serial")
        await transport.disconnect()
        ws.send_json.assert_awaited_once_with({"type": "disconnect"})

    @pytest.mark.asyncio
    async def test_disconnect_handles_closed_ws(self):
        """disconnect() does not raise if WS is already closed."""
        transport, ws = self._make_transport("serial")
        ws.client_state = WebSocketState.DISCONNECTED
        # Should not raise
        await transport.disconnect()
        ws.send_json.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_send_noop_when_ws_closed(self):
        """send() does nothing when WebSocket is not connected."""
        transport, ws = self._make_transport("serial")
        ws.client_state = WebSocketState.DISCONNECTED
        await transport.send(b"\x01\x02")
        ws.send_bytes.assert_not_awaited()

    def test_set_reader_and_callback(self):
        """set_reader and set_disconnect_callback store references."""
        transport, _ = self._make_transport("serial")
        reader = MagicMock()
        callback = MagicMock()
        transport.set_reader(reader)
        transport.set_disconnect_callback(callback)
        assert transport._reader is reader
        assert transport._disconnect_callback is callback

    def test_reset_framing(self):
        """reset_framing clears the state machine."""
        transport, _ = self._make_transport("serial")
        transport._frame_started = True
        transport._header = b"\x3c\x05"
        transport._inframe = b"\x01\x02"
        transport._frame_size = 5

        transport.reset_framing()

        assert transport._frame_started is False
        assert transport._header == b""
        assert transport._inframe == b""
        assert transport._frame_size == 0


# ---------------------------------------------------------------------------
# RadioManager loopback methods
# ---------------------------------------------------------------------------


class TestRadioManagerLoopback:
    """Tests for connect_loopback / disconnect_loopback state transitions."""

    def test_connect_loopback_sets_state(self):
        from app.radio import RadioManager

        rm = RadioManager()
        mc = MagicMock()
        rm.connect_loopback(mc, "Loopback (serial)")

        assert rm.meshcore is mc
        assert rm.connection_info == "Loopback (serial)"
        assert rm.loopback_active is True
        assert rm._last_connected is True
        assert rm._setup_complete is False

    @pytest.mark.asyncio
    async def test_disconnect_loopback_clears_state(self):
        from app.radio import RadioManager

        rm = RadioManager()
        mc = MagicMock()
        mc.disconnect = AsyncMock()
        rm.connect_loopback(mc, "Loopback (serial)")

        with patch("app.websocket.broadcast_health"):
            await rm.disconnect_loopback()

        assert rm.meshcore is None
        assert rm.connection_info is None
        assert rm.loopback_active is False
        mc.disconnect.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_disconnect_loopback_handles_mc_disconnect_error(self):
        """disconnect_loopback doesn't raise if mc.disconnect() fails."""
        from app.radio import RadioManager

        rm = RadioManager()
        mc = MagicMock()
        mc.disconnect = AsyncMock(side_effect=OSError("transport closed"))
        rm.connect_loopback(mc, "Loopback (ble)")

        with patch("app.websocket.broadcast_health"):
            # Should not raise
            await rm.disconnect_loopback()

        assert rm.loopback_active is False

    @pytest.mark.asyncio
    async def test_disconnect_loopback_broadcasts_health_false(self):
        from app.radio import RadioManager

        rm = RadioManager()
        mc = MagicMock()
        mc.disconnect = AsyncMock()
        rm.connect_loopback(mc, "Loopback (serial)")

        with patch("app.websocket.broadcast_health") as mock_bh:
            await rm.disconnect_loopback()

        mock_bh.assert_called_once_with(False, None)

    @pytest.mark.asyncio
    async def test_monitor_skips_reconnect_during_loopback(self):
        """Connection monitor skips auto-detect when _loopback_active is True."""
        from app.radio import RadioManager

        rm = RadioManager()
        mc = MagicMock()
        mc.is_connected = True
        rm.connect_loopback(mc, "Loopback (serial)")

        rm.reconnect = AsyncMock()

        sleep_count = 0

        async def _sleep(_seconds: float):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count >= 3:
                raise asyncio.CancelledError()

        with patch("app.radio.asyncio.sleep", side_effect=_sleep):
            await rm.start_connection_monitor()
            try:
                await rm._reconnect_task
            finally:
                await rm.stop_connection_monitor()

        # reconnect should never be called while loopback is active
        rm.reconnect.assert_not_awaited()


# ---------------------------------------------------------------------------
# WebSocket endpoint tests
# ---------------------------------------------------------------------------


class TestLoopbackEndpointGuards:
    """Tests for the /ws/transport WebSocket endpoint guard conditions."""

    def test_rejects_when_explicit_transport_configured(self):
        """Endpoint closes when explicit transport env is set."""
        from fastapi.testclient import TestClient

        from app.main import app

        with (
            patch("app.routers.loopback.settings") as mock_settings,
            patch("app.routers.loopback.radio_manager"),
        ):
            mock_settings.loopback_eligible = False

            client = TestClient(app)
            # Endpoint accepts then immediately closes — verify by catching the close
            with client.websocket_connect("/api/ws/transport") as ws:
                closed = False
                try:
                    ws.receive_text()
                except Exception:  # noqa: BLE001
                    closed = True
            assert closed

    def test_rejects_when_radio_already_connected(self):
        """Endpoint closes when radio is already connected."""
        from fastapi.testclient import TestClient

        from app.main import app

        with (
            patch("app.routers.loopback.settings") as mock_settings,
            patch("app.routers.loopback.radio_manager") as mock_rm,
        ):
            mock_settings.loopback_eligible = True
            mock_rm.is_connected = True

            client = TestClient(app)
            with client.websocket_connect("/api/ws/transport") as ws:
                closed = False
                try:
                    ws.receive_text()
                except Exception:  # noqa: BLE001
                    closed = True
            assert closed


class TestLoopbackEndpointInit:
    """Tests for the init handshake and basic operation."""

    def test_rejects_invalid_init_message(self):
        """Endpoint closes on invalid init JSON."""
        from fastapi.testclient import TestClient

        from app.main import app

        with (
            patch("app.routers.loopback.settings") as mock_settings,
            patch("app.routers.loopback.radio_manager") as mock_rm,
        ):
            mock_settings.loopback_eligible = True
            mock_rm.is_connected = False
            mock_rm.disconnect_loopback = AsyncMock()

            client = TestClient(app)
            with client.websocket_connect("/api/ws/transport") as ws:
                ws.send_text(json.dumps({"type": "init", "mode": "invalid"}))
                closed = False
                try:
                    ws.receive_text()
                except Exception:  # noqa: BLE001
                    closed = True
            assert closed

    def test_accepts_valid_serial_init(self):
        """Endpoint accepts valid serial init and proceeds to MeshCore creation."""
        mock_mc = MagicMock()
        mock_mc.is_connected = True
        mock_mc.connect = AsyncMock()

        with (
            patch("app.routers.loopback.settings") as mock_settings,
            patch("app.routers.loopback.radio_manager") as mock_rm,
            patch("meshcore.MeshCore", return_value=mock_mc) as mock_mc_cls,
        ):
            mock_settings.loopback_eligible = True
            mock_rm.is_connected = False
            mock_rm.connect_loopback = MagicMock()
            mock_rm.post_connect_setup = AsyncMock()
            mock_rm.disconnect_loopback = AsyncMock()

            from fastapi.testclient import TestClient

            from app.main import app

            client = TestClient(app)
            with client.websocket_connect("/api/ws/transport") as ws:
                ws.send_text(json.dumps({"type": "init", "mode": "serial"}))
                # Send disconnect to close cleanly
                ws.send_text(json.dumps({"type": "disconnect"}))

            # Verify MeshCore was created and connect_loopback called
            mock_mc_cls.assert_called_once()
            mock_mc.connect.assert_awaited_once()
            mock_rm.connect_loopback.assert_called_once()
            mock_rm.disconnect_loopback.assert_awaited_once()


# ---------------------------------------------------------------------------
# Config loopback_eligible property
# ---------------------------------------------------------------------------


class TestConfigLoopbackEligible:
    """Tests for the loopback_eligible property."""

    def test_eligible_when_no_transport_set(self):
        from app.config import Settings

        s = Settings(serial_port="", tcp_host="", ble_address="")
        assert s.loopback_eligible is True

    def test_not_eligible_with_serial_port(self):
        from app.config import Settings

        s = Settings(serial_port="/dev/ttyUSB0")
        assert s.loopback_eligible is False

    def test_not_eligible_with_tcp_host(self):
        from app.config import Settings

        s = Settings(tcp_host="192.168.1.1")
        assert s.loopback_eligible is False

    def test_not_eligible_with_ble(self):
        from app.config import Settings

        s = Settings(ble_address="AA:BB:CC:DD:EE:FF", ble_pin="1234")
        assert s.loopback_eligible is False
