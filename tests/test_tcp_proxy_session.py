"""Tests for app.tcp_proxy.session — ProxySession command handlers."""

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.tcp_proxy.protocol import (
    CMD_APP_START,
    CMD_DEVICE_QUERY,
    CMD_GET_BATT_AND_STORAGE,
    CMD_GET_CHANNEL,
    CMD_GET_CONTACT_BY_KEY,
    CMD_GET_CONTACTS,
    CMD_GET_DEVICE_TIME,
    CMD_HAS_CONNECTION,
    CMD_RESET_PATH,
    CMD_SEND_CHANNEL_TXT_MSG,
    CMD_SEND_TXT_MSG,
    CMD_SET_CHANNEL,
    CMD_SYNC_NEXT_MESSAGE,
    ERR_NOT_FOUND,
    PROXY_FW_VER,
    PUSH_MSG_WAITING,
    RESP_BATTERY,
    RESP_CONTACT_END,
    RESP_CONTACT_START,
    RESP_CURRENT_TIME,
    RESP_DEVICE_INFO,
    RESP_ERR,
    RESP_MSG_SENT,
    RESP_NO_MORE_MSGS,
    RESP_OK,
    RESP_SELF_INFO,
)
from app.tcp_proxy.session import ProxySession

EXAMPLE_KEY = "ab" * 32


# ── Helpers ──────────────────────────────────────────────────────────


def _make_session() -> tuple[ProxySession, list[bytes]]:
    """Create a ProxySession with a capturing writer."""
    reader = AsyncMock(spec=asyncio.StreamReader)
    writer = MagicMock(spec=asyncio.StreamWriter)
    writer.get_extra_info.return_value = ("127.0.0.1", 12345)

    sent: list[bytes] = []

    def capture_write(data: bytes):
        sent.append(data)

    writer.write = capture_write
    writer.drain = AsyncMock()

    session = ProxySession(reader, writer)
    return session, sent


def _extract_payloads(sent: list[bytes]) -> list[bytes]:
    """Extract payloads from framed response bytes."""
    payloads = []
    for frame in sent:
        assert frame[0] == 0x3E
        size = int.from_bytes(frame[1:3], "little")
        payloads.append(frame[3 : 3 + size])
    return payloads


def _make_contact(public_key: str = EXAMPLE_KEY, name: str = "Alice", **kw):
    return MagicMock(
        model_dump=MagicMock(
            return_value={
                "public_key": public_key,
                "name": name,
                "type": 1,
                "favorite": True,
                "direct_path": None,
                "direct_path_len": -1,
                "direct_path_hash_mode": -1,
                "last_advert": 0,
                "lat": 0.0,
                "lon": 0.0,
                "first_seen": int(time.time()),
                **kw,
            }
        )
    )


def _make_channel(key: str = "cc" * 16, name: str = "test", favorite: bool = True):
    return MagicMock(
        model_dump=MagicMock(return_value={"key": key, "name": name, "favorite": favorite})
    )


def _make_settings(last_message_times=None):
    return MagicMock(last_message_times=last_message_times or {})


def _mock_radio_runtime(connected: bool = True, self_info: dict | None = None):
    rt = MagicMock()
    rt.is_connected = connected
    mc = MagicMock()
    mc.self_info = self_info or {
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
    return rt


# ── Tests ────────────────────────────────────────────────────────────


class TestAppStart:
    @pytest.mark.asyncio
    async def test_sends_self_info(self):
        session, sent = _make_session()
        contacts = [_make_contact()]
        channels = [_make_channel()]
        settings = _make_settings()
        rt = _mock_radio_runtime()

        with (
            patch("app.repository.ContactRepository") as cr,
            patch("app.repository.ChannelRepository") as chr_,
            patch("app.repository.AppSettingsRepository") as sr,
            patch("app.services.radio_runtime.radio_runtime", rt),
        ):
            cr.get_favorites = AsyncMock(return_value=contacts)
            chr_.get_all = AsyncMock(return_value=channels)
            sr.get = AsyncMock(return_value=settings)

            await session._cmd_app_start(bytes([CMD_APP_START]))

        payloads = _extract_payloads(sent)
        assert len(payloads) == 1
        assert payloads[0][0] == RESP_SELF_INFO

    @pytest.mark.asyncio
    async def test_populates_contacts_and_channels(self):
        session, sent = _make_session()
        contacts = [_make_contact(), _make_contact(public_key="cd" * 32, name="Bob")]
        channels = [_make_channel(), _make_channel(key="dd" * 16, name="ch2")]
        settings = _make_settings()
        rt = _mock_radio_runtime()

        with (
            patch("app.repository.ContactRepository") as cr,
            patch("app.repository.ChannelRepository") as chr_,
            patch("app.repository.AppSettingsRepository") as sr,
            patch("app.services.radio_runtime.radio_runtime", rt),
        ):
            cr.get_favorites = AsyncMock(return_value=contacts)
            chr_.get_all = AsyncMock(return_value=channels)
            sr.get = AsyncMock(return_value=settings)

            await session._cmd_app_start(bytes([CMD_APP_START]))

        assert len(session.contacts) == 2
        # Only favorite channels are slotted
        assert len(session.channel_slots) == 2


class TestDeviceQuery:
    @pytest.mark.asyncio
    async def test_sends_device_info(self):
        session, sent = _make_session()
        rt = _mock_radio_runtime()

        with patch("app.services.radio_runtime.radio_runtime", rt):
            await session._cmd_device_query(bytes([CMD_DEVICE_QUERY, 0x03]))

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_DEVICE_INFO
        assert payloads[0][1] == PROXY_FW_VER


class TestGetContacts:
    @pytest.mark.asyncio
    async def test_sends_start_contacts_end(self):
        session, sent = _make_session()
        contacts = [_make_contact()]

        with patch("app.repository.ContactRepository") as cr:
            cr.get_favorites = AsyncMock(return_value=contacts)
            await session._cmd_get_contacts(bytes([CMD_GET_CONTACTS]))

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_CONTACT_START
        count = int.from_bytes(payloads[0][1:5], "little")
        assert count == 1
        # Middle payload(s) are contacts
        assert payloads[-1][0] == RESP_CONTACT_END


class TestGetContactByKey:
    @pytest.mark.asyncio
    async def test_found(self):
        session, sent = _make_session()
        session.contacts = [
            {
                "public_key": EXAMPLE_KEY,
                "type": 1,
                "name": "Alice",
                "favorite": True,
                "direct_path": None,
                "direct_path_len": -1,
                "direct_path_hash_mode": -1,
                "last_advert": 0,
                "lat": 0.0,
                "lon": 0.0,
                "first_seen": 0,
            }
        ]

        cmd = bytes([CMD_GET_CONTACT_BY_KEY]) + bytes.fromhex(EXAMPLE_KEY)
        await session._cmd_get_contact_by_key(cmd)

        payloads = _extract_payloads(sent)
        assert len(payloads) == 1
        assert payloads[0][0] == 0x03  # RESP_CONTACT

    @pytest.mark.asyncio
    async def test_not_found(self):
        session, sent = _make_session()
        session.contacts = []

        cmd = bytes([CMD_GET_CONTACT_BY_KEY]) + bytes.fromhex(EXAMPLE_KEY)
        await session._cmd_get_contact_by_key(cmd)

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_ERR
        assert payloads[0][1] == ERR_NOT_FOUND


class TestGetChannel:
    @pytest.mark.asyncio
    async def test_found(self):
        session, sent = _make_session()
        key = "cc" * 16
        session.channel_slots = {0: key}
        session.channels = [{"key": key, "name": "test"}]

        await session._cmd_get_channel(bytes([CMD_GET_CHANNEL, 0]))

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == 0x12  # RESP_CHANNEL_INFO

    @pytest.mark.asyncio
    async def test_empty_slot_returns_error(self):
        session, sent = _make_session()
        session.channel_slots = {}

        await session._cmd_get_channel(bytes([CMD_GET_CHANNEL, 5]))

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_ERR


class TestSetChannel:
    @pytest.mark.asyncio
    async def test_updates_slot_mapping(self):
        session, sent = _make_session()

        name = b"test" + b"\x00" * 28  # 32 bytes
        secret = b"\xaa" * 16
        cmd = bytes([CMD_SET_CHANNEL, 3]) + name + secret
        await session._cmd_set_channel(cmd)

        assert session.channel_slots[3] == "aa" * 16
        assert session.key_to_idx["aa" * 16] == 3

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_OK

    @pytest.mark.asyncio
    async def test_cleans_stale_mapping(self):
        session, sent = _make_session()

        # Pre-load slot 0 with key_a
        session.channel_slots[0] = "aa" * 16
        session.key_to_idx["aa" * 16] = 0

        # Overwrite slot 0 with key_b
        name = b"\x00" * 32
        secret_b = b"\xbb" * 16
        cmd = bytes([CMD_SET_CHANNEL, 0]) + name + secret_b
        await session._cmd_set_channel(cmd)

        assert session.channel_slots[0] == "bb" * 16
        assert "aa" * 16 not in session.key_to_idx


class TestSendDm:
    @pytest.mark.asyncio
    async def test_sends_msg_sent_and_ack(self):
        session, sent = _make_session()
        session.contacts = [{"public_key": EXAMPLE_KEY}]

        # CMD_SEND_TXT_MSG: cmd(1) + txt_type(1) + attempt(1) + ts(4) + prefix(6) + text
        prefix = bytes.fromhex(EXAMPLE_KEY[:12])
        cmd = (
            bytes([CMD_SEND_TXT_MSG, 0, 0])
            + int(time.time()).to_bytes(4, "little")
            + prefix
            + b"Hello"
        )

        with patch.object(session, "_do_send_dm", new_callable=AsyncMock):
            await session._cmd_send_dm(cmd)

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_MSG_SENT
        assert payloads[1][0] == 0x82  # PUSH_ACK
        # ACK code should match
        ack_from_sent = payloads[0][2:6]
        ack_from_push = payloads[1][1:5]
        assert ack_from_sent == ack_from_push


class TestSendChannel:
    @pytest.mark.asyncio
    async def test_sends_ok(self):
        session, sent = _make_session()
        key = "cc" * 16
        session.channel_slots = {0: key}
        session.channels = [{"key": key, "name": "test"}]

        cmd = (
            bytes([CMD_SEND_CHANNEL_TXT_MSG, 0, 0])
            + int(time.time()).to_bytes(4, "little")
            + b"Hello"
        )

        fake_channel = MagicMock(name="test")
        with (
            patch(
                "app.repository.ChannelRepository.get_by_key",
                new_callable=AsyncMock,
                return_value=fake_channel,
            ),
            patch.object(session, "_do_send_channel", new_callable=AsyncMock),
        ):
            await session._cmd_send_channel(cmd)

        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_OK


class TestSimpleCommands:
    @pytest.mark.asyncio
    async def test_get_time(self):
        session, sent = _make_session()
        await session._cmd_get_time(bytes([CMD_GET_DEVICE_TIME]))
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_CURRENT_TIME

    @pytest.mark.asyncio
    async def test_battery(self):
        session, sent = _make_session()
        await session._cmd_battery(bytes([CMD_GET_BATT_AND_STORAGE]))
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_BATTERY

    @pytest.mark.asyncio
    async def test_has_connection(self):
        session, sent = _make_session()
        rt = _mock_radio_runtime(connected=True)
        with patch("app.services.radio_runtime.radio_runtime", rt):
            await session._cmd_has_connection(bytes([CMD_HAS_CONNECTION]))
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_OK
        val = int.from_bytes(payloads[0][1:5], "little")
        assert val == 1

    @pytest.mark.asyncio
    async def test_ok_stub(self):
        session, sent = _make_session()
        await session._cmd_ok_stub(bytes([CMD_RESET_PATH]))
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_OK


class TestSyncNext:
    @pytest.mark.asyncio
    async def test_empty_queue(self):
        session, sent = _make_session()
        await session._cmd_sync_next(bytes([CMD_SYNC_NEXT_MESSAGE]))
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == RESP_NO_MORE_MSGS

    @pytest.mark.asyncio
    async def test_dequeues_message(self):
        session, sent = _make_session()
        fake_msg = bytes([0x10, 0x00, 0x00, 0x00]) + b"\xaa" * 10
        session._msg_queue.append(fake_msg)

        await session._cmd_sync_next(bytes([CMD_SYNC_NEXT_MESSAGE]))
        payloads = _extract_payloads(sent)
        assert payloads[0] == fake_msg
        assert len(session._msg_queue) == 0


class TestEventHandlers:
    @pytest.mark.asyncio
    async def test_priv_message_queued(self):
        session, sent = _make_session()
        data = {
            "type": "PRIV",
            "outgoing": False,
            "conversation_key": EXAMPLE_KEY,
            "text": "hello",
            "sender_timestamp": 1700000000,
        }
        await session.on_event_message(data)

        assert len(session._msg_queue) == 1
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == PUSH_MSG_WAITING

    @pytest.mark.asyncio
    async def test_chan_message_queued(self):
        session, sent = _make_session()
        key = "cc" * 16
        session.key_to_idx = {key: 0}

        data = {
            "type": "CHAN",
            "outgoing": False,
            "conversation_key": key.upper(),  # test case normalization
            "text": "hello",
            "sender_timestamp": 1700000000,
        }
        await session.on_event_message(data)

        assert len(session._msg_queue) == 1

    @pytest.mark.asyncio
    async def test_outgoing_message_ignored(self):
        session, sent = _make_session()
        data = {"type": "PRIV", "outgoing": True, "conversation_key": EXAMPLE_KEY}
        await session.on_event_message(data)
        assert len(session._msg_queue) == 0
        assert len(sent) == 0

    @pytest.mark.asyncio
    async def test_chan_unmapped_dropped(self):
        session, sent = _make_session()
        session.key_to_idx = {}
        data = {
            "type": "CHAN",
            "outgoing": False,
            "conversation_key": "ff" * 16,
            "text": "hello",
            "sender_timestamp": 0,
        }
        await session.on_event_message(data)
        assert len(session._msg_queue) == 0

    @pytest.mark.asyncio
    async def test_contact_event_updates_existing_cache(self):
        session, sent = _make_session()
        # Contact must already be in favorites cache to receive pushes
        session.contacts = [
            {
                "public_key": EXAMPLE_KEY,
                "name": "Old",
                "type": 1,
                "favorite": True,
                "direct_path": None,
                "direct_path_len": -1,
                "direct_path_hash_mode": -1,
                "last_advert": 0,
                "lat": 0.0,
                "lon": 0.0,
                "first_seen": 0,
            }
        ]

        data = {
            "public_key": EXAMPLE_KEY,
            "type": 1,
            "name": "Updated",
            "favorite": True,
            "direct_path": None,
            "direct_path_len": -1,
            "direct_path_hash_mode": -1,
            "last_advert": 100,
            "lat": 0.0,
            "lon": 0.0,
            "first_seen": 0,
        }
        await session.on_event_contact(data)
        assert len(session.contacts) == 1
        assert session.contacts[0]["name"] == "Updated"
        # Should have sent a PUSH_NEW_ADVERT
        payloads = _extract_payloads(sent)
        assert payloads[0][0] == 0x8A  # PUSH_NEW_ADVERT

    @pytest.mark.asyncio
    async def test_contact_event_ignored_for_non_favorites(self):
        session, sent = _make_session()
        session.contacts = []

        data = {
            "public_key": EXAMPLE_KEY,
            "type": 1,
            "name": "Stranger",
            "favorite": False,
        }
        await session.on_event_contact(data)
        assert len(session.contacts) == 0
        assert len(sent) == 0
