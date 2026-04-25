"""Integration tests for the TCP proxy — real asyncio TCP server + client."""

import asyncio

import pytest

from app.tcp_proxy.protocol import (
    CMD_APP_START,
    CMD_DEVICE_QUERY,
    CMD_GET_CHANNEL,
    CMD_GET_CONTACTS,
    CMD_GET_DEVICE_TIME,
    CMD_HAS_CONNECTION,
    CMD_SET_CHANNEL,
    CMD_SYNC_NEXT_MESSAGE,
    FRAME_RX,
    FRAME_TX,
    PROXY_FW_VER,
    PUSH_MSG_WAITING,
    RESP_CONTACT_END,
    RESP_CONTACT_START,
    RESP_CURRENT_TIME,
    RESP_DEVICE_INFO,
    RESP_ERR,
    RESP_NO_MORE_MSGS,
    RESP_OK,
    RESP_SELF_INFO,
)
from app.tcp_proxy.server import dispatch_event, register, unregister
from app.tcp_proxy.session import ProxySession

# ── Helpers ──────────────────────────────────────────────────────────

EXAMPLE_KEY = "ab" * 32


def _frame_cmd(payload: bytes) -> bytes:
    """Wrap a command payload in a 0x3C frame."""
    return bytes([FRAME_TX]) + len(payload).to_bytes(2, "little") + payload


async def _read_response(reader: asyncio.StreamReader) -> bytes:
    """Read one 0x3E-framed response and return the payload."""
    marker = await reader.readexactly(1)
    assert marker[0] == FRAME_RX
    size_bytes = await reader.readexactly(2)
    size = int.from_bytes(size_bytes, "little")
    payload = await reader.readexactly(size)
    return payload


class _ProxyTestHarness:
    """Manages a real TCP proxy server for testing."""

    def __init__(self):
        self._server: asyncio.Server | None = None
        self.port: int = 0
        self.sessions: list[ProxySession] = []

    async def start(self):
        self._server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self.port = self._server.sockets[0].getsockname()[1]

    async def stop(self):
        for s in self.sessions:
            try:
                s.writer.close()
            except Exception:
                pass
        self.sessions.clear()
        if self._server:
            self._server.close()
            await self._server.wait_closed()

    async def _handle(self, reader, writer):
        session = ProxySession(reader, writer)
        self.sessions.append(session)
        register(session)
        try:
            await session.run()
        finally:
            unregister(session)

    async def connect(self) -> tuple[asyncio.StreamReader, asyncio.StreamWriter]:
        reader, writer = await asyncio.open_connection("127.0.0.1", self.port)
        return reader, writer


@pytest.fixture
async def harness():
    h = _ProxyTestHarness()
    await h.start()
    yield h
    await h.stop()


def _mock_repos_and_runtime():
    """Return a context manager that mocks repositories and radio_runtime."""
    import time
    from unittest.mock import AsyncMock, MagicMock, patch

    contacts = [
        MagicMock(
            model_dump=MagicMock(
                return_value={
                    "public_key": EXAMPLE_KEY,
                    "name": "Alice",
                    "type": 1,
                    "favorite": True,
                    "direct_path": None,
                    "direct_path_len": -1,
                    "direct_path_hash_mode": -1,
                    "last_advert": 0,
                    "lat": 0.0,
                    "lon": 0.0,
                    "first_seen": int(time.time()),
                }
            )
        )
    ]
    channels = [
        MagicMock(
            model_dump=MagicMock(return_value={"key": "cc" * 16, "name": "test", "favorite": True})
        )
    ]
    settings_obj = MagicMock(last_message_times={})

    rt = MagicMock()
    rt.is_connected = True
    mc = MagicMock()
    mc.self_info = {
        "public_key": EXAMPLE_KEY,
        "name": "TestNode",
        "tx_power": 20,
        "max_tx_power": 22,
        "adv_lat": 0.0,
        "adv_lon": 0.0,
        "radio_freq": 915.0,
        "radio_bw": 250.0,
        "radio_sf": 10,
        "radio_cr": 7,
    }
    rt.meshcore = mc

    class _Ctx:
        def __enter__(self_):
            self_._patches = [
                patch(
                    "app.repository.ContactRepository.get_favorites",
                    new_callable=AsyncMock,
                    return_value=contacts,
                ),
                patch(
                    "app.repository.ChannelRepository.get_all",
                    new_callable=AsyncMock,
                    return_value=channels,
                ),
                patch(
                    "app.repository.AppSettingsRepository.get",
                    new_callable=AsyncMock,
                    return_value=settings_obj,
                ),
                patch(
                    "app.services.radio_runtime.radio_runtime",
                    rt,
                ),
            ]
            for p in self_._patches:
                p.__enter__()
            return self_

        def __exit__(self_, *args):
            for p in reversed(self_._patches):
                p.__exit__(*args)

    return _Ctx()


# ── Tests ────────────────────────────────────────────────────────────


class TestTcpProxyIntegration:
    @pytest.mark.asyncio
    async def test_app_start_returns_self_info(self, harness):
        reader, writer = await harness.connect()
        try:
            with _mock_repos_and_runtime():
                writer.write(_frame_cmd(bytes([CMD_APP_START]) + b"\x03" + b" " * 6 + b"test"))
                await writer.drain()
                resp = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp[0] == RESP_SELF_INFO
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_device_query_returns_device_info(self, harness):
        reader, writer = await harness.connect()
        try:
            with _mock_repos_and_runtime():
                # First do APP_START to initialize session state
                writer.write(_frame_cmd(bytes([CMD_APP_START]) + b"\x03" + b" " * 6 + b"test"))
                await writer.drain()
                await asyncio.wait_for(_read_response(reader), timeout=3)

                writer.write(_frame_cmd(bytes([CMD_DEVICE_QUERY, 0x03])))
                await writer.drain()
                resp = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp[0] == RESP_DEVICE_INFO
                assert resp[1] == PROXY_FW_VER
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_get_contacts_flow(self, harness):
        reader, writer = await harness.connect()
        try:
            with _mock_repos_and_runtime():
                writer.write(_frame_cmd(bytes([CMD_GET_CONTACTS])))
                await writer.drain()

                # Should get CONTACT_START
                resp1 = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp1[0] == RESP_CONTACT_START
                count = int.from_bytes(resp1[1:5], "little")
                assert count == 1

                # One contact
                resp2 = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp2[0] == 0x03  # RESP_CONTACT

                # CONTACT_END
                resp3 = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp3[0] == RESP_CONTACT_END
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_get_time(self, harness):
        reader, writer = await harness.connect()
        try:
            writer.write(_frame_cmd(bytes([CMD_GET_DEVICE_TIME])))
            await writer.drain()
            resp = await asyncio.wait_for(_read_response(reader), timeout=3)
            assert resp[0] == RESP_CURRENT_TIME
            assert len(resp) == 5
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_has_connection(self, harness):
        reader, writer = await harness.connect()
        try:
            with _mock_repos_and_runtime():
                writer.write(_frame_cmd(bytes([CMD_HAS_CONNECTION])))
                await writer.drain()
                resp = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp[0] == RESP_OK
                val = int.from_bytes(resp[1:5], "little")
                assert val == 1
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_empty_channel_returns_error(self, harness):
        reader, writer = await harness.connect()
        try:
            writer.write(_frame_cmd(bytes([CMD_GET_CHANNEL, 5])))
            await writer.drain()
            resp = await asyncio.wait_for(_read_response(reader), timeout=3)
            assert resp[0] == RESP_ERR
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_set_then_get_channel(self, harness):
        reader, writer = await harness.connect()
        try:
            # SET_CHANNEL: cmd(1) + idx(1) + name(32) + secret(16) = 50
            name = b"mychan" + b"\x00" * 26  # 32 bytes
            secret = b"\xdd" * 16
            cmd = bytes([CMD_SET_CHANNEL, 2]) + name + secret
            writer.write(_frame_cmd(cmd))
            await writer.drain()
            resp = await asyncio.wait_for(_read_response(reader), timeout=3)
            assert resp[0] == RESP_OK

            # GET_CHANNEL for slot 2
            writer.write(_frame_cmd(bytes([CMD_GET_CHANNEL, 2])))
            await writer.drain()
            resp2 = await asyncio.wait_for(_read_response(reader), timeout=3)
            assert resp2[0] == 0x12  # RESP_CHANNEL_INFO
            assert resp2[1] == 2  # idx
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_sync_next_empty(self, harness):
        reader, writer = await harness.connect()
        try:
            writer.write(_frame_cmd(bytes([CMD_SYNC_NEXT_MESSAGE])))
            await writer.drain()
            resp = await asyncio.wait_for(_read_response(reader), timeout=3)
            assert resp[0] == RESP_NO_MORE_MSGS
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_event_dispatch_queues_message(self, harness):
        reader, writer = await harness.connect()
        try:
            with _mock_repos_and_runtime():
                # APP_START to init session
                writer.write(_frame_cmd(bytes([CMD_APP_START]) + b"\x03" + b" " * 6 + b"test"))
                await writer.drain()
                await asyncio.wait_for(_read_response(reader), timeout=3)

                # Set a channel so CHAN messages can be routed
                name = b"\x00" * 32
                secret = bytes.fromhex("cc" * 16)
                writer.write(_frame_cmd(bytes([CMD_SET_CHANNEL, 0]) + name + secret))
                await writer.drain()
                await asyncio.wait_for(_read_response(reader), timeout=3)

                # Simulate a broadcast event
                await dispatch_event(
                    "message",
                    {
                        "type": "CHAN",
                        "outgoing": False,
                        "conversation_key": "cc" * 16,
                        "text": "hello from event",
                        "sender_timestamp": 1700000000,
                    },
                )

                # Should receive PUSH_MSG_WAITING
                resp = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert resp[0] == PUSH_MSG_WAITING

                # Pull the message
                writer.write(_frame_cmd(bytes([CMD_SYNC_NEXT_MESSAGE])))
                await writer.drain()
                msg = await asyncio.wait_for(_read_response(reader), timeout=3)
                assert msg[0] == 0x11  # RESP_CHANNEL_MSG_RECV_V3
        finally:
            writer.close()

    @pytest.mark.asyncio
    async def test_multiple_clients_isolated(self, harness):
        r1, w1 = await harness.connect()
        r2, w2 = await harness.connect()
        try:
            # Both can get time independently
            w1.write(_frame_cmd(bytes([CMD_GET_DEVICE_TIME])))
            w2.write(_frame_cmd(bytes([CMD_GET_DEVICE_TIME])))
            await w1.drain()
            await w2.drain()

            resp1 = await asyncio.wait_for(_read_response(r1), timeout=3)
            resp2 = await asyncio.wait_for(_read_response(r2), timeout=3)
            assert resp1[0] == RESP_CURRENT_TIME
            assert resp2[0] == RESP_CURRENT_TIME
        finally:
            w1.close()
            w2.close()
