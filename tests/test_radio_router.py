"""Tests for radio router endpoint logic."""

import asyncio
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from meshcore import EventType

from app.radio import RadioManager, radio_manager
from app.routers.radio import (
    PrivateKeyUpdate,
    RadioConfigResponse,
    RadioConfigUpdate,
    RadioSettings,
    get_radio_config,
    reboot_radio,
    reconnect_radio,
    send_advertisement,
    set_private_key,
    update_radio_config,
)


def _radio_result(event_type=EventType.OK, payload=None):
    result = MagicMock()
    result.type = event_type
    result.payload = payload or {}
    return result


def _noop_radio_operation(mc=None):
    """Factory for a no-op radio_operation context manager that yields mc."""

    @asynccontextmanager
    async def _ctx(*_args, **_kwargs):
        yield mc

    return _ctx


@pytest.fixture(autouse=True)
def _reset_radio_state():
    """Save/restore radio_manager state so tests don't leak."""
    prev = radio_manager._meshcore
    prev_lock = radio_manager._operation_lock
    prev_path_hash_mode = radio_manager._path_hash_mode
    prev_path_hash_mode_supported = radio_manager._path_hash_mode_supported
    yield
    radio_manager._meshcore = prev
    radio_manager._operation_lock = prev_lock
    radio_manager._path_hash_mode = prev_path_hash_mode
    radio_manager._path_hash_mode_supported = prev_path_hash_mode_supported


def _mock_meshcore_with_info():
    mc = MagicMock()
    mc.self_info = {
        "public_key": "aa" * 32,
        "name": "NodeA",
        "adv_lat": 10.0,
        "adv_lon": 20.0,
        "tx_power": 17,
        "max_tx_power": 22,
        "radio_freq": 910.525,
        "radio_bw": 62.5,
        "radio_sf": 7,
        "radio_cr": 5,
    }
    mc.commands = MagicMock()
    mc.commands.set_name = AsyncMock()
    mc.commands.set_coords = AsyncMock()
    mc.commands.set_tx_power = AsyncMock()
    mc.commands.set_radio = AsyncMock()
    mc.commands.send_appstart = AsyncMock()
    mc.commands.send_device_query = AsyncMock(
        return_value=_radio_result(payload={"path_hash_mode": 1})
    )
    mc.commands.send = AsyncMock(return_value=_radio_result())
    mc.commands.import_private_key = AsyncMock(return_value=_radio_result())
    return mc


class TestGetRadioConfig:
    @pytest.mark.asyncio
    async def test_maps_self_info_to_response(self):
        mc = _mock_meshcore_with_info()
        radio_manager.set_path_hash_mode_info(1, True)
        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
        ):
            response = await get_radio_config()

        assert response.public_key == "aa" * 32
        assert response.name == "NodeA"
        assert response.lat == 10.0
        assert response.lon == 20.0
        assert response.radio.freq == 910.525
        assert response.radio.cr == 5
        assert response.path_hash_mode == 1
        assert response.path_hash_mode_supported is True
        mc.commands.send_device_query.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_returns_503_when_self_info_missing(self):
        mc = MagicMock()
        mc.self_info = None
        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
        ):
            with pytest.raises(HTTPException) as exc:
                await get_radio_config()

        assert exc.value.status_code == 503

    @pytest.mark.asyncio
    async def test_marks_path_hash_mode_unsupported_when_device_info_lacks_field(self):
        mc = _mock_meshcore_with_info()
        radio_manager.set_path_hash_mode_info(0, False)

        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
        ):
            response = await get_radio_config()

        assert response.path_hash_mode == 0
        assert response.path_hash_mode_supported is False
        mc.commands.send_device_query.assert_not_awaited()


class TestUpdateRadioConfig:
    @pytest.mark.asyncio
    async def test_updates_only_requested_fields_and_refreshes_info(self):
        mc = _mock_meshcore_with_info()
        expected = RadioConfigResponse(
            public_key="aa" * 32,
            name="NodeUpdated",
            lat=1.23,
            lon=20.0,
            tx_power=17,
            max_tx_power=22,
            path_hash_mode=1,
            path_hash_mode_supported=True,
            radio=RadioSettings(freq=910.525, bw=62.5, sf=7, cr=5),
        )

        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
            patch.object(radio_manager, "radio_operation", _noop_radio_operation(mc)),
            patch("app.routers.radio.sync_radio_time", new_callable=AsyncMock) as mock_sync_time,
            patch(
                "app.routers.radio.get_radio_config", new_callable=AsyncMock, return_value=expected
            ),
        ):
            result = await update_radio_config(RadioConfigUpdate(name="NodeUpdated", lat=1.23))

        mc.commands.set_name.assert_awaited_once_with("NodeUpdated")
        mc.commands.set_coords.assert_awaited_once_with(lat=1.23, lon=20.0)
        mc.commands.set_tx_power.assert_not_awaited()
        mc.commands.set_radio.assert_not_awaited()
        mc.commands.send_appstart.assert_awaited_once()
        mock_sync_time.assert_awaited_once()
        assert result == expected

    @pytest.mark.asyncio
    async def test_updates_path_hash_mode_via_raw_command_fallback(self):
        mc = _mock_meshcore_with_info()
        mc.commands.set_path_hash_mode = None
        radio_manager.set_path_hash_mode_info(1, True)
        expected = RadioConfigResponse(
            public_key="aa" * 32,
            name="NodeA",
            lat=10.0,
            lon=20.0,
            tx_power=17,
            max_tx_power=22,
            path_hash_mode=2,
            path_hash_mode_supported=True,
            radio=RadioSettings(freq=910.525, bw=62.5, sf=7, cr=5),
        )

        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
            patch.object(radio_manager, "radio_operation", _noop_radio_operation(mc)),
            patch("app.routers.radio.sync_radio_time", new_callable=AsyncMock),
            patch(
                "app.routers.radio.get_radio_config", new_callable=AsyncMock, return_value=expected
            ),
        ):
            result = await update_radio_config(RadioConfigUpdate(path_hash_mode=2))

        mc.commands.send.assert_awaited_once_with(b"\x3d\x00\x02", [EventType.OK, EventType.ERROR])
        assert result == expected

    @pytest.mark.asyncio
    async def test_rejects_path_hash_mode_update_when_radio_does_not_expose_it(self):
        mc = _mock_meshcore_with_info()
        mc.commands.send_device_query = AsyncMock(return_value=_radio_result(payload={}))
        radio_manager.set_path_hash_mode_info(0, False)

        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
            patch.object(radio_manager, "radio_operation", _noop_radio_operation(mc)),
        ):
            with pytest.raises(HTTPException) as exc:
                await update_radio_config(RadioConfigUpdate(path_hash_mode=2))

        assert exc.value.status_code == 400
        assert "path hash mode" in exc.value.detail.lower()


class TestPrivateKeyImport:
    @pytest.mark.asyncio
    async def test_rejects_invalid_hex(self):
        mc = _mock_meshcore_with_info()
        with patch("app.routers.radio.require_connected", return_value=mc):
            with pytest.raises(HTTPException) as exc:
                await set_private_key(PrivateKeyUpdate(private_key="not-hex"))

        assert exc.value.status_code == 400

    @pytest.mark.asyncio
    async def test_returns_500_on_radio_error(self):
        mc = _mock_meshcore_with_info()
        mc.commands.import_private_key = AsyncMock(
            return_value=_radio_result(EventType.ERROR, {"error": "failed"})
        )
        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
        ):
            with pytest.raises(HTTPException) as exc:
                await set_private_key(PrivateKeyUpdate(private_key="aa" * 64))

        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_successful_import_refreshes_keystore(self):
        mc = _mock_meshcore_with_info()
        mc.commands.import_private_key = AsyncMock(return_value=_radio_result())
        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
            patch(
                "app.keystore.export_and_store_private_key",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_export,
        ):
            result = await set_private_key(PrivateKeyUpdate(private_key="aa" * 64))

        assert result == {"status": "ok"}
        mock_export.assert_awaited_once_with(mc)

    @pytest.mark.asyncio
    async def test_import_ok_but_keystore_refresh_fails_returns_500(self):
        mc = _mock_meshcore_with_info()
        mc.commands.import_private_key = AsyncMock(return_value=_radio_result())
        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
            patch(
                "app.keystore.export_and_store_private_key",
                new_callable=AsyncMock,
                return_value=False,
            ) as mock_export,
        ):
            with pytest.raises(HTTPException) as exc:
                await set_private_key(PrivateKeyUpdate(private_key="aa" * 64))

        assert exc.value.status_code == 500
        assert "keystore" in exc.value.detail.lower()
        # Called twice: initial attempt + one retry
        assert mock_export.await_count == 2

    @pytest.mark.asyncio
    async def test_keystore_refresh_succeeds_on_retry(self):
        mc = _mock_meshcore_with_info()
        mc.commands.import_private_key = AsyncMock(return_value=_radio_result())
        with (
            patch("app.routers.radio.require_connected", return_value=mc),
            patch.object(radio_manager, "_meshcore", mc),
            patch(
                "app.keystore.export_and_store_private_key",
                new_callable=AsyncMock,
                side_effect=[False, True],
            ) as mock_export,
        ):
            result = await set_private_key(PrivateKeyUpdate(private_key="aa" * 64))

        assert result == {"status": "ok"}
        assert mock_export.await_count == 2


class TestAdvertise:
    @pytest.mark.asyncio
    async def test_raises_when_send_fails(self):
        radio_manager._meshcore = MagicMock()
        with (
            patch("app.routers.radio.require_connected"),
            patch(
                "app.routers.radio.do_send_advertisement",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            with pytest.raises(HTTPException) as exc:
                await send_advertisement()

        assert exc.value.status_code == 500

    @pytest.mark.asyncio
    async def test_concurrent_advertise_calls_are_serialized(self):
        active = 0
        max_active = 0

        async def fake_send(mc, *, force: bool):
            nonlocal active, max_active
            assert force is True
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return True

        isolated_manager = RadioManager()
        isolated_manager._meshcore = MagicMock()
        with (
            patch("app.routers.radio.require_connected"),
            patch("app.routers.radio.radio_manager", isolated_manager),
            patch(
                "app.routers.radio.do_send_advertisement",
                new_callable=AsyncMock,
                side_effect=fake_send,
            ),
        ):
            await asyncio.gather(send_advertisement(), send_advertisement())

        assert max_active == 1


class TestRebootAndReconnect:
    @pytest.mark.asyncio
    async def test_reboot_connected_sends_reboot_command(self):
        mock_mc = MagicMock()
        mock_mc.commands.reboot = AsyncMock()

        mock_rm = MagicMock()
        mock_rm.is_connected = True
        mock_rm.meshcore = mock_mc
        mock_rm.radio_operation = _noop_radio_operation(mock_mc)

        with patch("app.routers.radio.radio_manager", mock_rm):
            result = await reboot_radio()

        assert result["status"] == "ok"
        mock_mc.commands.reboot.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reboot_returns_pending_when_reconnect_in_progress(self):
        mock_rm = MagicMock()
        mock_rm.is_connected = False
        mock_rm.meshcore = None
        mock_rm.is_reconnecting = True
        mock_rm.radio_operation = _noop_radio_operation()

        with patch("app.routers.radio.radio_manager", mock_rm):
            result = await reboot_radio()

        assert result["status"] == "pending"
        assert result["connected"] is False

    @pytest.mark.asyncio
    async def test_reboot_attempts_reconnect_when_disconnected(self):
        mock_rm = MagicMock()
        mock_rm.is_connected = False
        mock_rm.meshcore = None
        mock_rm.is_reconnecting = False
        mock_rm.reconnect = AsyncMock(return_value=True)
        mock_rm.post_connect_setup = AsyncMock()
        mock_rm.radio_operation = _noop_radio_operation()

        with patch("app.routers.radio.radio_manager", mock_rm):
            result = await reboot_radio()

        assert result["status"] == "ok"
        assert result["connected"] is True
        mock_rm.reconnect.assert_awaited_once()
        mock_rm.post_connect_setup.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_reconnect_returns_already_connected(self):
        mock_rm = MagicMock()
        mock_rm.is_connected = True
        mock_rm.radio_operation = _noop_radio_operation()

        with patch("app.routers.radio.radio_manager", mock_rm):
            result = await reconnect_radio()

        assert result["status"] == "ok"
        assert result["connected"] is True

    @pytest.mark.asyncio
    async def test_reconnect_raises_503_on_failure(self):
        mock_rm = MagicMock()
        mock_rm.is_connected = False
        mock_rm.is_reconnecting = False
        mock_rm.reconnect = AsyncMock(return_value=False)
        mock_rm.radio_operation = _noop_radio_operation()

        with patch("app.routers.radio.radio_manager", mock_rm):
            with pytest.raises(HTTPException) as exc:
                await reconnect_radio()

        assert exc.value.status_code == 503
