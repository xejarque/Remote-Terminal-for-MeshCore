"""Per-client MeshCore companion protocol session.

Each connected TCP client gets its own ``ProxySession`` which:
- parses incoming 0x3C frames via :class:`protocol.FrameParser`
- dispatches commands to handler methods
- translates between binary companion payloads and in-process
  repository / service calls
- receives broadcast events and queues push frames for the client
"""

from __future__ import annotations

import asyncio
import io
import logging
import random
import struct
import time
from typing import Any

from .encoder import (
    build_contact_from_dict,
    build_device_info,
    build_self_info_from_runtime,
)
from .protocol import (
    CMD_ADD_UPDATE_CONTACT,
    CMD_APP_START,
    CMD_DEVICE_QUERY,
    CMD_EXPORT_PRIVATE_KEY,
    CMD_GET_BATT_AND_STORAGE,
    CMD_GET_CHANNEL,
    CMD_GET_CONTACT_BY_KEY,
    CMD_GET_CONTACTS,
    CMD_GET_DEVICE_TIME,
    CMD_HAS_CONNECTION,
    CMD_NAMES,
    CMD_REMOVE_CONTACT,
    CMD_RESET_PATH,
    CMD_SEND_CHANNEL_TXT_MSG,
    CMD_SEND_SELF_ADVERT,
    CMD_SEND_TXT_MSG,
    CMD_SET_ADVERT_LATLON,
    CMD_SET_ADVERT_NAME,
    CMD_SET_CHANNEL,
    CMD_SET_DEVICE_TIME,
    CMD_SET_FLOOD_SCOPE,
    CMD_SYNC_NEXT_MESSAGE,
    ERR_NOT_FOUND,
    ERR_UNSUPPORTED,
    PROXY_MAX_CHANNELS,
    PUSH_ACK,
    PUSH_MSG_WAITING,
    RESP_BATTERY,
    RESP_CHANNEL_INFO,
    RESP_CHANNEL_MSG_RECV_V3,
    RESP_CONTACT_END,
    RESP_CONTACT_MSG_RECV_V3,
    RESP_CONTACT_START,
    RESP_CURRENT_TIME,
    RESP_DISABLED,
    RESP_MSG_SENT,
    RESP_NO_MORE_MSGS,
    FrameParser,
    build_error,
    build_ok,
    encode_path_byte,
    frame_response,
    pad,
)

logger = logging.getLogger(__name__)


class ProxySession:
    """Handles one MeshCore TCP client, translating commands to RemoteTerm
    repository and service calls."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.addr = writer.get_extra_info("peername")
        self.parser = FrameParser()

        # Cached state
        self.contacts: list[dict[str, Any]] = []
        self.channels: list[dict[str, Any]] = []

        # Channel index ↔ key mapping
        self.channel_slots: dict[int, str] = {}  # idx → key (lowercase hex)
        self.key_to_idx: dict[str, int] = {}  # key (lowercase) → idx

        # Queued incoming messages for SYNC_NEXT_MESSAGE pull flow.
        self._msg_queue: list[bytes] = []

    # ── send helper ──────────────────────────────────────────────────

    async def send(self, payload: bytes) -> None:
        """Frame and send a response payload."""
        self.writer.write(frame_response(payload))
        await self.writer.drain()

    # ── main loop ────────────────────────────────────────────────────

    async def run(self) -> None:
        logger.info("Client connected: %s", self.addr)
        try:
            while True:
                data = await self.reader.read(4096)
                if not data:
                    break
                for payload in self.parser.feed(data):
                    await self._dispatch(payload)
        except (asyncio.CancelledError, ConnectionResetError):
            pass
        except Exception:
            logger.exception("Session error [%s]", self.addr)
        finally:
            self.writer.close()
            logger.info("Client disconnected: %s", self.addr)

    # ── command dispatch ─────────────────────────────────────────────

    _DISPATCH_TABLE: dict[int, str] | None = None

    @classmethod
    def _build_dispatch_table(cls) -> dict[int, str]:
        if cls._DISPATCH_TABLE is None:
            cls._DISPATCH_TABLE = {
                CMD_APP_START: "_cmd_app_start",
                CMD_DEVICE_QUERY: "_cmd_device_query",
                CMD_GET_CONTACTS: "_cmd_get_contacts",
                CMD_GET_CONTACT_BY_KEY: "_cmd_get_contact_by_key",
                CMD_GET_CHANNEL: "_cmd_get_channel",
                CMD_SET_CHANNEL: "_cmd_set_channel",
                CMD_SEND_TXT_MSG: "_cmd_send_dm",
                CMD_SEND_CHANNEL_TXT_MSG: "_cmd_send_channel",
                CMD_GET_DEVICE_TIME: "_cmd_get_time",
                CMD_SET_DEVICE_TIME: "_cmd_ok_stub",
                CMD_SEND_SELF_ADVERT: "_cmd_advertise",
                CMD_GET_BATT_AND_STORAGE: "_cmd_battery",
                CMD_HAS_CONNECTION: "_cmd_has_connection",
                CMD_SYNC_NEXT_MESSAGE: "_cmd_sync_next",
                CMD_ADD_UPDATE_CONTACT: "_cmd_ok_stub",
                CMD_REMOVE_CONTACT: "_cmd_remove_contact",
                CMD_RESET_PATH: "_cmd_ok_stub",
                CMD_SET_ADVERT_NAME: "_cmd_set_name",
                CMD_SET_ADVERT_LATLON: "_cmd_set_latlon",
                CMD_SET_FLOOD_SCOPE: "_cmd_ok_stub",
                CMD_EXPORT_PRIVATE_KEY: "_cmd_disabled",
            }
        return cls._DISPATCH_TABLE

    async def _dispatch(self, data: bytes) -> None:
        if not data:
            return
        cmd = data[0]
        name = CMD_NAMES.get(cmd, f"0x{cmd:02x}")
        logger.debug("[%s] ← %s (%dB)", self.addr, name, len(data))

        table = self._build_dispatch_table()
        method_name = table.get(cmd)
        if method_name:
            handler = getattr(self, method_name)
            try:
                await handler(data)
            except Exception:
                logger.exception("[%s] Error in %s", self.addr, name)
                await self.send(build_error())
        else:
            logger.warning("[%s] Unsupported: %s", self.addr, name)
            await self.send(build_error(ERR_UNSUPPORTED))

    # ── stubs ────────────────────────────────────────────────────────

    async def _cmd_ok_stub(self, data: bytes) -> None:
        await self.send(build_ok())

    async def _cmd_disabled(self, data: bytes) -> None:
        await self.send(bytes([RESP_DISABLED]))

    # ── APP_START → SELF_INFO ────────────────────────────────────────

    async def _cmd_app_start(self, data: bytes) -> None:
        from app.repository import AppSettingsRepository, ChannelRepository, ContactRepository
        from app.services.radio_runtime import radio_runtime

        self.contacts = [c.model_dump() for c in await ContactRepository.get_favorites()]
        self.channels = [c.model_dump() for c in await ChannelRepository.get_all()]

        settings = await AppSettingsRepository.get()
        lmt = settings.last_message_times or {}
        self._sort_channels(lmt)
        self._rebuild_slots()

        mc = radio_runtime.meshcore
        self_info = mc.self_info if mc else {}
        await self.send(build_self_info_from_runtime(self_info or {}))

        name = (self_info or {}).get("name", "?")
        pubkey = (self_info or {}).get("public_key", "?" * 12)
        logger.info(
            "[%s] Session started — %s (%s...) | %d contacts, %d channel slots",
            self.addr,
            name,
            pubkey[:12],
            len(self.contacts),
            len(self.channel_slots),
        )

    # ── DEVICE_QUERY → DEVICE_INFO ──────────────────────────────────

    async def _cmd_device_query(self, data: bytes) -> None:
        from app.services.radio_runtime import radio_runtime

        mc = radio_runtime.meshcore
        self_info = mc.self_info if mc else {}
        # Fall back to radio_runtime.path_hash_mode which radio_lifecycle
        # recovers from the raw device-info frame when self_info is missing it.
        phm = (self_info or {}).get("path_hash_mode")
        if phm is None:
            phm = getattr(radio_runtime, "path_hash_mode", 0) or 0
        await self.send(build_device_info(path_hash_mode=phm))

    # ── GET_CONTACTS ─────────────────────────────────────────────────

    async def _cmd_get_contacts(self, data: bytes) -> None:
        from app.repository import ContactRepository

        self.contacts = [c.model_dump() for c in await ContactRepository.get_favorites()]

        count = len(self.contacts)
        await self.send(bytes([RESP_CONTACT_START]) + count.to_bytes(4, "little"))

        for c in self.contacts:
            await self.send(build_contact_from_dict(c))

        await self.send(bytes([RESP_CONTACT_END]) + int(time.time()).to_bytes(4, "little"))
        logger.info("[%s] Sent %d contacts", self.addr, count)

    # ── GET_CONTACT_BY_KEY ───────────────────────────────────────────

    async def _cmd_get_contact_by_key(self, data: bytes) -> None:
        if len(data) < 33:
            await self.send(build_error(ERR_NOT_FOUND))
            return

        pubkey = data[1:33].hex()
        contact = next((c for c in self.contacts if c["public_key"] == pubkey), None)
        if contact is None:
            await self.send(build_error(ERR_NOT_FOUND))
            return

        await self.send(build_contact_from_dict(contact))

    # ── GET_CHANNEL → CHANNEL_INFO ───────────────────────────────────

    async def _cmd_get_channel(self, data: bytes) -> None:
        if len(data) < 2:
            await self.send(build_error(ERR_NOT_FOUND))
            return

        idx = data[1]
        key_hex = self.channel_slots.get(idx)
        if key_hex is None:
            await self.send(build_error(ERR_NOT_FOUND))
            return

        ch = next((c for c in self.channels if c["key"].lower() == key_hex), None)
        name = (ch.get("name") or "") if ch else ""

        out = bytearray()
        out.append(RESP_CHANNEL_INFO)
        out.append(idx)
        out.extend(pad(name.encode("utf-8"), 32))
        out.extend(pad(bytes.fromhex(key_hex), 16))
        await self.send(bytes(out))

    # ── SET_CHANNEL ──────────────────────────────────────────────────

    async def _cmd_set_channel(self, data: bytes) -> None:
        if len(data) < 50:
            await self.send(build_error())
            return

        idx = data[1]
        key_hex = data[34:50].hex()

        # Clean up stale bidirectional mappings
        old_key = self.channel_slots.get(idx)
        if old_key is not None and old_key != key_hex:
            self.key_to_idx.pop(old_key, None)

        old_idx = self.key_to_idx.get(key_hex)
        if old_idx is not None and old_idx != idx:
            self.channel_slots.pop(old_idx, None)

        self.channel_slots[idx] = key_hex
        self.key_to_idx[key_hex] = idx
        await self.send(build_ok())

    # ── SEND_TXT_MSG (DM) ───────────────────────────────────────────

    async def _cmd_send_dm(self, data: bytes) -> None:
        buf = io.BytesIO(data)
        buf.read(1)  # cmd
        buf.read(1)  # txt_type
        buf.read(1)  # attempt
        buf.read(4)  # timestamp
        remaining = buf.read()

        full_key, text = self._parse_destination_and_text(remaining)
        if not full_key or text is None:
            logger.warning(
                "[%s] Cannot resolve DM destination (remaining %dB)",
                self.addr,
                len(remaining),
            )
            await self.send(build_error(ERR_NOT_FOUND))
            return

        # Send immediate MSG_SENT + fake ACK — RemoteTerm handles retries.
        ack_code = random.randbytes(4)
        out = bytearray([RESP_MSG_SENT, 1])  # type=flood
        out.extend(ack_code)
        out.extend(struct.pack("<I", 5_000))
        await self.send(bytes(out))

        ack_frame = bytearray([PUSH_ACK])
        ack_frame.extend(ack_code)
        ack_frame.extend(struct.pack("<I", 100))  # fake trip_time
        await self.send(bytes(ack_frame))

        # Fire-and-forget the actual send
        asyncio.create_task(self._do_send_dm(full_key, text))
        logger.info("[%s] DM → %s...: %s", self.addr, full_key[:12], text[:40])

    async def _do_send_dm(self, public_key: str, text: str) -> None:
        """Background task: send a DM through the radio via the service layer."""
        try:
            from app.event_handlers import track_pending_ack
            from app.repository import ContactRepository, MessageRepository
            from app.services.message_send import send_direct_message_to_contact
            from app.services.radio_runtime import radio_runtime
            from app.websocket import broadcast_event

            contact = await ContactRepository.get_by_key_or_prefix(public_key)
            if not contact:
                logger.warning("DM send: contact %s not found", public_key[:12])
                return

            await send_direct_message_to_contact(
                contact=contact,
                text=text,
                radio_manager=radio_runtime,
                broadcast_fn=broadcast_event,
                track_pending_ack_fn=track_pending_ack,
                now_fn=time.time,
                message_repository=MessageRepository,
                contact_repository=ContactRepository,
            )
        except Exception:
            logger.exception("[%s] DM send failed for %s", self.addr, public_key[:12])

    def _parse_destination_and_text(self, remaining: bytes) -> tuple[str | None, str | None]:
        """Resolve destination key + text from the combined buffer.

        The standard companion protocol sends a 6-byte pubkey prefix at the
        start of ``remaining``, so we try prefix resolution first.  Only when
        prefix lookup fails do we attempt a 32-byte full-key parse (used by
        ``meshcore_py`` ``send_msg_with_retry``).
        """
        # Standard path: 6-byte prefix — resolve against cached contacts.
        if len(remaining) > 6:
            prefix = remaining[:6].hex()
            matches = [c["public_key"] for c in self.contacts if c["public_key"].startswith(prefix)]
            if len(matches) == 1:
                return matches[0], remaining[6:].decode("utf-8", "ignore")

        # Extended path: 32-byte full key (send_msg_with_retry sends full
        # keys).  _do_send_dm resolves from the repository, not just our
        # favorites cache.
        if len(remaining) > 32:
            candidate = remaining[:32].hex()
            return candidate, remaining[32:].decode("utf-8", "ignore")

        return None, None

    # ── SEND_CHANNEL_TXT_MSG ─────────────────────────────────────────

    async def _cmd_send_channel(self, data: bytes) -> None:
        buf = io.BytesIO(data)
        buf.read(1)  # cmd
        buf.read(1)  # txt_type
        channel_idx = buf.read(1)[0]
        buf.read(4)  # timestamp
        text = buf.read().rstrip(b"\x00").decode("utf-8", "ignore")

        key_hex = self.channel_slots.get(channel_idx)
        if not key_hex:
            logger.warning("[%s] No channel at slot %d", self.addr, channel_idx)
            await self.send(build_error(ERR_NOT_FOUND))
            return

        # Verify the channel exists in RemoteTerm's DB before confirming.
        # SET_CHANNEL is local-only, so client-loaded channels that aren't in
        # the DB can't be sent on — return ERR_NOT_FOUND instead of false OK.
        from app.repository import ChannelRepository

        channel = await ChannelRepository.get_by_key(key_hex)
        if not channel:
            logger.warning("[%s] Channel %s not in DB", self.addr, key_hex[:12])
            await self.send(build_error(ERR_NOT_FOUND))
            return

        await self.send(build_ok())
        asyncio.create_task(self._do_send_channel(key_hex, text))

        label = channel.name or key_hex[:8]
        logger.info("[%s] Chan [%s]: %s", self.addr, label, text[:40])

    async def _do_send_channel(self, channel_key: str, text: str) -> None:
        """Background task: send a channel message through the radio."""
        try:
            from app.repository import ChannelRepository, MessageRepository
            from app.services.message_send import send_channel_message_to_channel
            from app.services.radio_runtime import radio_runtime
            from app.websocket import broadcast_error, broadcast_event

            channel = await ChannelRepository.get_by_key(channel_key)
            if not channel:
                logger.warning("Channel send: key %s not found", channel_key[:12])
                return

            key_bytes = bytes.fromhex(channel_key)
            await send_channel_message_to_channel(
                channel=channel,
                channel_key_upper=channel_key.upper(),
                key_bytes=key_bytes,
                text=text,
                radio_manager=radio_runtime,
                broadcast_fn=broadcast_event,
                error_broadcast_fn=broadcast_error,
                now_fn=time.time,
                temp_radio_slot=0,
                message_repository=MessageRepository,
            )
        except Exception:
            logger.exception("[%s] Channel send failed for %s", self.addr, channel_key[:12])

    # ── Simple command handlers ──────────────────────────────────────

    async def _cmd_get_time(self, data: bytes) -> None:
        t = int(time.time())
        await self.send(bytes([RESP_CURRENT_TIME]) + t.to_bytes(4, "little"))

    async def _cmd_advertise(self, data: bytes) -> None:
        try:
            from app.services.radio_runtime import radio_runtime

            async with radio_runtime.radio_operation("proxy_advertise") as mc:
                await mc.commands.send_advert(flood=True)
            await self.send(build_ok())
        except Exception:
            logger.exception("Advertise failed")
            await self.send(build_error())

    async def _cmd_battery(self, data: bytes) -> None:
        out = bytearray([RESP_BATTERY])
        out.extend(struct.pack("<H", 0))  # no battery
        await self.send(bytes(out))

    async def _cmd_has_connection(self, data: bytes) -> None:
        from app.services.radio_runtime import radio_runtime

        val = 1 if radio_runtime.is_connected else 0
        await self.send(build_ok(val))

    async def _cmd_sync_next(self, data: bytes) -> None:
        if self._msg_queue:
            frame = self._msg_queue.pop(0)
            await self.send(frame)
            logger.debug(
                "[%s] Delivered queued msg (%d remaining)",
                self.addr,
                len(self._msg_queue),
            )
        else:
            await self.send(bytes([RESP_NO_MORE_MSGS]))

    async def _cmd_remove_contact(self, data: bytes) -> None:
        if len(data) < 33:
            await self.send(build_error())
            return
        pubkey = data[1:33].hex()
        self.contacts = [c for c in self.contacts if c["public_key"] != pubkey]
        await self.send(build_ok())

    async def _cmd_set_name(self, data: bytes) -> None:
        name = data[1:].decode("utf-8", "ignore").rstrip("\x00")
        try:
            from app.services.radio_runtime import radio_runtime

            async with radio_runtime.radio_operation("proxy_set_name") as mc:
                await mc.commands.set_name(name)
            await self.send(build_ok())
        except Exception:
            logger.exception("Set name failed")
            await self.send(build_error())

    async def _cmd_set_latlon(self, data: bytes) -> None:
        if len(data) < 9:
            await self.send(build_error())
            return
        lat = struct.unpack_from("<i", data, 1)[0] / 1e6
        lon = struct.unpack_from("<i", data, 5)[0] / 1e6
        try:
            from app.services.radio_runtime import radio_runtime

            async with radio_runtime.radio_operation("proxy_set_latlon") as mc:
                await mc.commands.set_coords(lat, lon)
            await self.send(build_ok())
        except Exception:
            logger.exception("Set lat/lon failed")
            await self.send(build_error())

    # ── Channel slot management ──────────────────────────────────────

    def _sort_channels(self, last_message_times: dict[str, Any]) -> None:
        """Sort channels: favorites first, then most recently active."""
        lmt = last_message_times

        def key(ch: dict) -> tuple:
            is_fav = 1 if ch.get("favorite") else 0
            state_key = f"channel-{ch['key']}"
            last_activity = lmt.get(state_key) or 0
            return (-is_fav, -last_activity)

        self.channels.sort(key=key)

    def _rebuild_slots(self) -> None:
        """Pre-load only favorite channels into slots."""
        self.channel_slots.clear()
        self.key_to_idx.clear()
        favorites = [ch for ch in self.channels if ch.get("favorite")]
        for i, ch in enumerate(favorites[:PROXY_MAX_CHANNELS]):
            k = ch["key"].lower()
            self.channel_slots[i] = k
            self.key_to_idx[k] = i
        logger.debug("Pre-loaded %d favorite channel(s)", len(self.channel_slots))

    # ── Broadcast event helpers ────────────────────────────────────────

    @staticmethod
    def _extract_path_meta(data: dict[str, Any]) -> tuple[int, int]:
        """Extract (snr_byte, path_len_byte) from a broadcast message dict.

        Returns the SNR as ``int8(snr * 4)`` and path_len as the companion-
        protocol packed byte ``(hash_mode << 6) | hop_count``.  When no path
        data is available, returns ``(0, 0)`` — 0 hops at 1-byte hash mode,
        which is the safest "we don't know" default for flood messages.
        """
        paths = data.get("paths") or []
        first = paths[0] if paths else None

        # SNR — V3 field, signed int8 encoded as snr * 4
        snr_raw = (first.get("snr") if first else None) or 0.0
        snr_byte = max(-128, min(127, int(snr_raw * 4))) & 0xFF

        if first is None:
            return snr_byte, 0  # no path info → 0 hops

        hop_count = first.get("path_len")
        path_hex: str = first.get("path") or ""
        if hop_count is None:
            # Legacy: infer 1-byte hops from hex length
            hop_count = len(path_hex) // 2

        # Determine hash mode from path hex length and hop count
        if hop_count > 0 and path_hex:
            path_byte_len = len(path_hex) // 2
            hash_size = path_byte_len // hop_count if hop_count else 1
            hash_mode = max(0, hash_size - 1)  # 1-byte → 0, 2 → 1, 3 → 2
        else:
            hash_mode = 0

        return snr_byte, encode_path_byte(hop_count, hash_mode)

    # ── Broadcast event handlers (called by server.dispatch_event) ──

    async def _push_contact_from_db(self, public_key: str) -> None:
        """Fetch a contact from the DB and push it to the client so it can
        display messages from senders not in the favorites cache."""
        try:
            from app.repository import ContactRepository

            contact = await ContactRepository.get_by_key(public_key)
            if not contact:
                return
            contact_dict = contact.model_dump()
            await self.send(build_contact_from_dict(contact_dict, push=True))
            self.contacts.append(contact_dict)
        except Exception:
            logger.debug("Failed to push contact %s from DB", public_key[:12])

    async def on_event_message(self, data: dict[str, Any]) -> None:
        """Translate a broadcast ``message`` event into a queued push frame."""
        if data.get("outgoing"):
            return

        msg_type = data.get("type")

        if msg_type == "PRIV":
            sender_key = data.get("conversation_key", "")
            if len(sender_key) < 12:
                return

            # If sender isn't in our cache, fetch from DB and push to client
            # so it knows who the message is from.
            if not any(c["public_key"] == sender_key for c in self.contacts):
                await self._push_contact_from_db(sender_key)

            text = data.get("text") or ""
            ts = int(data.get("sender_timestamp") or time.time())
            snr_byte, path_byte = self._extract_path_meta(data)

            frame = bytearray([RESP_CONTACT_MSG_RECV_V3])
            frame.append(snr_byte)
            frame.extend(b"\x00\x00")  # reserved
            frame.extend(bytes.fromhex(sender_key[:12]))  # 6-byte prefix
            frame.append(path_byte)
            frame.append(0)  # txt_type
            frame.extend(struct.pack("<I", ts))
            frame.extend(text.encode("utf-8"))

            self._msg_queue.append(bytes(frame))
            await self.send(bytes([PUSH_MSG_WAITING]))

        elif msg_type == "CHAN":
            conv_key = data.get("conversation_key", "").lower()
            idx = self.key_to_idx.get(conv_key)
            if idx is None:
                return

            text = data.get("text") or ""
            ts = int(data.get("sender_timestamp") or time.time())
            snr_byte, path_byte = self._extract_path_meta(data)

            frame = bytearray([RESP_CHANNEL_MSG_RECV_V3])
            frame.append(snr_byte)
            frame.extend(b"\x00\x00")  # reserved
            frame.append(idx)
            frame.append(path_byte)
            frame.append(0)  # txt_type
            frame.extend(struct.pack("<I", ts))
            frame.extend(text.encode("utf-8"))

            self._msg_queue.append(bytes(frame))
            await self.send(bytes([PUSH_MSG_WAITING]))

    async def on_event_contact(self, data: dict[str, Any]) -> None:
        """Translate a broadcast ``contact`` event into a PUSH_NEW_ADVERT."""
        pubkey = data.get("public_key", "")
        if len(pubkey) < 64:
            return

        # Only push contacts that are already in our favorites cache.
        # Without this filter, a long-lived session would gradually sync
        # every contact on the mesh, defeating the favorites-only policy.
        existing = next((c for c in self.contacts if c["public_key"] == pubkey), None)
        if existing is None:
            return

        try:
            await self.send(build_contact_from_dict(data, push=True))
        except Exception:
            logger.debug("Failed to build contact push for %s", pubkey[:12])

        existing.update(data)
