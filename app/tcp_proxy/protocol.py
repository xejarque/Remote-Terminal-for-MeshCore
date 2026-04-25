"""MeshCore companion protocol constants, frame helpers, and streaming parser."""

from __future__ import annotations

# ── Frame markers ────────────────────────────────────────────────────

FRAME_TX = 0x3C  # client → radio
FRAME_RX = 0x3E  # radio → client
MAX_FRAME_SIZE = 300  # firmware MAX_FRAME_SIZE is 172; we allow a bit more

# ── Command types (client → proxy) ──────────────────────────────────

CMD_APP_START = 0x01
CMD_SEND_TXT_MSG = 0x02
CMD_SEND_CHANNEL_TXT_MSG = 0x03
CMD_GET_CONTACTS = 0x04
CMD_GET_DEVICE_TIME = 0x05
CMD_SET_DEVICE_TIME = 0x06
CMD_SEND_SELF_ADVERT = 0x07
CMD_SET_ADVERT_NAME = 0x08
CMD_ADD_UPDATE_CONTACT = 0x09
CMD_SYNC_NEXT_MESSAGE = 0x0A
CMD_SET_RADIO_PARAMS = 0x0B
CMD_SET_RADIO_TX_POWER = 0x0C
CMD_RESET_PATH = 0x0D
CMD_SET_ADVERT_LATLON = 0x0E
CMD_REMOVE_CONTACT = 0x0F
CMD_REBOOT = 0x13
CMD_GET_BATT_AND_STORAGE = 0x14
CMD_DEVICE_QUERY = 0x16
CMD_EXPORT_PRIVATE_KEY = 0x17
CMD_HAS_CONNECTION = 0x1C
CMD_GET_CONTACT_BY_KEY = 0x1E
CMD_GET_CHANNEL = 0x1F
CMD_SET_CHANNEL = 0x20
CMD_SET_FLOOD_SCOPE = 0x36
CMD_GET_STATS = 0x38

CMD_NAMES: dict[int, str] = {
    0x01: "APP_START",
    0x02: "SEND_TXT_MSG",
    0x03: "SEND_CHAN_MSG",
    0x04: "GET_CONTACTS",
    0x05: "GET_TIME",
    0x06: "SET_TIME",
    0x07: "SEND_ADVERT",
    0x08: "SET_NAME",
    0x09: "ADD_CONTACT",
    0x0A: "SYNC_MSG",
    0x0B: "SET_RADIO",
    0x0C: "SET_TX_POWER",
    0x0D: "RESET_PATH",
    0x0E: "SET_LATLON",
    0x0F: "REMOVE_CONTACT",
    0x13: "REBOOT",
    0x14: "GET_BATTERY",
    0x16: "DEVICE_QUERY",
    0x17: "EXPORT_PRIV_KEY",
    0x1C: "HAS_CONNECTION",
    0x1E: "GET_CONTACT_BY_KEY",
    0x1F: "GET_CHANNEL",
    0x20: "SET_CHANNEL",
    0x36: "SET_FLOOD_SCOPE",
    0x38: "GET_STATS",
}

# ── Response / push types (proxy → client) ──────────────────────────

RESP_OK = 0x00
RESP_ERR = 0x01
RESP_CONTACT_START = 0x02
RESP_CONTACT = 0x03
RESP_CONTACT_END = 0x04
RESP_SELF_INFO = 0x05
RESP_MSG_SENT = 0x06
RESP_CONTACT_MSG_RECV = 0x07
RESP_CHANNEL_MSG_RECV = 0x08
RESP_CURRENT_TIME = 0x09
RESP_NO_MORE_MSGS = 0x0A
RESP_BATTERY = 0x0C
RESP_DEVICE_INFO = 0x0D
RESP_DISABLED = 0x0F
RESP_CONTACT_MSG_RECV_V3 = 0x10
RESP_CHANNEL_MSG_RECV_V3 = 0x11
RESP_CHANNEL_INFO = 0x12

PUSH_ACK = 0x82
PUSH_MSG_WAITING = 0x83
PUSH_NEW_ADVERT = 0x8A

# ── Error codes ──────────────────────────────────────────────────────

ERR_UNSUPPORTED = 1
ERR_NOT_FOUND = 2

# ── Virtual device identity ─────────────────────────────────────────

PROXY_FW_VER = 11
PROXY_MAX_CONTACTS_RAW = 255  # reader multiplies by 2 → 510
PROXY_MAX_CHANNELS = 40
PROXY_MODEL = "RemoteTerm Proxy"
PROXY_FW_VERSION = "v0.1.0-proxy"
PROXY_FW_BUILD = "proxy"


# ── Frame helpers ────────────────────────────────────────────────────


def frame_response(payload: bytes) -> bytes:
    """Wrap *payload* in a ``0x3E`` frame for sending to the client."""
    return bytes([FRAME_RX]) + len(payload).to_bytes(2, "little") + payload


def build_ok(value: int | None = None) -> bytes:
    """Build a ``RESP_OK`` payload, optionally with a 4-byte LE value."""
    if value is not None:
        return bytes([RESP_OK]) + value.to_bytes(4, "little")
    return bytes([RESP_OK])


def build_error(code: int = ERR_UNSUPPORTED) -> bytes:
    """Build a ``RESP_ERR`` payload with the given error code."""
    return bytes([RESP_ERR, code])


def pad(data: bytes, length: int) -> bytes:
    """Pad or truncate *data* to exactly *length* bytes."""
    return data[:length].ljust(length, b"\x00")


def encode_path_byte(hop_count: int, hash_mode: int) -> int:
    """Encode hop count + hash mode into a single packed byte.

    Returns ``0xFF`` (direct / non-flood) when either value is negative.
    """
    if hop_count < 0 or hash_mode < 0:
        return 0xFF
    return ((hash_mode & 0x03) << 6) | (hop_count & 0x3F)


# ── Streaming frame parser ──────────────────────────────────────────


class FrameParser:
    """Stateful parser for ``0x3C``-framed TCP data.

    Mirrors the framing logic in ``meshcore_py`` ``tcp_cx.py``.
    """

    def __init__(self) -> None:
        self.header = b""
        self.inframe = b""
        self.frame_size = 0
        self.started = False

    def feed(self, data: bytes) -> list[bytes]:
        """Feed raw TCP bytes, return a list of complete payloads."""
        payloads: list[bytes] = []
        offset = 0

        while offset < len(data):
            remaining = data[offset:]

            if not self.started:
                needed = 3 - len(self.header)
                chunk = remaining[:needed]
                self.header += chunk
                offset += len(chunk)

                if len(self.header) < 3:
                    break

                if self.header[0] != FRAME_TX:
                    self.header = b""
                    continue

                self.frame_size = int.from_bytes(self.header[1:3], "little")
                if self.frame_size > MAX_FRAME_SIZE:
                    self.header = b""
                    continue

                self.started = True
            else:
                needed = self.frame_size - len(self.inframe)
                chunk = remaining[:needed]
                self.inframe += chunk
                offset += len(chunk)

                if len(self.inframe) >= self.frame_size:
                    payloads.append(self.inframe)
                    self.header = b""
                    self.inframe = b""
                    self.started = False

        return payloads
