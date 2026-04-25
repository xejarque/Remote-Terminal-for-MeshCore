"""Binary encoders that build companion-protocol response payloads.

All functions return raw ``bytes`` payloads (without frame wrapping).
The caller is responsible for framing via :func:`protocol.frame_response`.
"""

from __future__ import annotations

import struct
import time
from typing import Any

from .protocol import (
    PROXY_FW_BUILD,
    PROXY_FW_VER,
    PROXY_FW_VERSION,
    PROXY_MAX_CHANNELS,
    PROXY_MAX_CONTACTS_RAW,
    PROXY_MODEL,
    PUSH_NEW_ADVERT,
    RESP_CONTACT,
    RESP_DEVICE_INFO,
    RESP_SELF_INFO,
    encode_path_byte,
    pad,
)


def build_contact(
    public_key: str,
    *,
    contact_type: int = 0,
    favorite: bool = False,
    direct_path: str | None = None,
    direct_path_len: int = -1,
    direct_path_hash_mode: int = -1,
    name: str | None = None,
    last_advert: int = 0,
    lat: float = 0.0,
    lon: float = 0.0,
    lastmod: int | None = None,
    push: bool = False,
) -> bytes:
    """Build a ``RESP_CONTACT`` (or ``PUSH_NEW_ADVERT``) payload.

    Args:
        push: If True, use ``PUSH_NEW_ADVERT`` (0x8A) instead of
              ``RESP_CONTACT`` (0x03) as the leading byte.
    """
    out = bytearray()
    out.append(PUSH_NEW_ADVERT if push else RESP_CONTACT)

    out.extend(pad(bytes.fromhex(public_key), 32))
    out.append(contact_type)

    flags = 0x01 if favorite else 0x00
    out.append(flags)

    if direct_path_len >= 0 and direct_path_hash_mode >= 0:
        out.append(encode_path_byte(direct_path_len, direct_path_hash_mode))
    else:
        out.append(0xFF)  # no route known

    path_bytes = bytes.fromhex(direct_path) if direct_path else b""
    out.extend(pad(path_bytes, 64))

    out.extend(pad((name or "").encode("utf-8", "replace"), 32))
    out.extend(struct.pack("<I", last_advert))

    out.extend(struct.pack("<i", int(lat * 1e6)))
    out.extend(struct.pack("<i", int(lon * 1e6)))

    out.extend(struct.pack("<I", lastmod or int(time.time())))

    return bytes(out)


def build_contact_from_dict(data: dict[str, Any], *, push: bool = False) -> bytes:
    """Build a contact payload from either a ``Contact`` model dict or a
    WS event ``data`` dict.  Accepts both snake_case model fields and
    the shapes produced by Pydantic JSON serialisation."""
    return build_contact(
        public_key=data["public_key"],
        contact_type=data.get("type") or 0,
        favorite=bool(data.get("favorite")),
        direct_path=data.get("direct_path") or None,
        direct_path_len=data.get("direct_path_len", -1),
        direct_path_hash_mode=data.get("direct_path_hash_mode", -1),
        name=data.get("name"),
        last_advert=int(data.get("last_advert") or 0),
        lat=float(data.get("lat") or 0),
        lon=float(data.get("lon") or 0),
        lastmod=int(data.get("lastmod") or data.get("first_seen") or 0) or None,
        push=push,
    )


def build_self_info(
    *,
    public_key: str = "00" * 32,
    name: str = "RemoteTerm",
    tx_power: int = 20,
    max_tx_power: int = 22,
    lat: float = 0.0,
    lon: float = 0.0,
    multi_acks: bool = False,
    advert_loc: bool = False,
    radio_freq: float = 915.0,
    radio_bw: float = 250.0,
    radio_sf: int = 10,
    radio_cr: int = 7,
) -> bytes:
    """Build a ``RESP_SELF_INFO`` payload (response to ``CMD_APP_START``)."""
    out = bytearray()
    out.append(RESP_SELF_INFO)
    out.append(1)  # adv_type = CHAT
    out.append(tx_power)
    out.append(max_tx_power)
    out.extend(pad(bytes.fromhex(public_key), 32))
    out.extend(struct.pack("<i", int(lat * 1e6)))
    out.extend(struct.pack("<i", int(lon * 1e6)))
    out.append(1 if multi_acks else 0)
    out.append(1 if advert_loc else 0)
    out.append(0)  # telemetry_mode
    out.append(0)  # manual_add_contacts
    out.extend(struct.pack("<I", int(radio_freq * 1000)))
    out.extend(struct.pack("<I", int(radio_bw * 1000)))
    out.append(radio_sf)
    out.append(radio_cr)
    out.extend(name.encode("utf-8"))
    return bytes(out)


def build_self_info_from_runtime(self_info: dict[str, Any]) -> bytes:
    """Build ``RESP_SELF_INFO`` from ``radio_runtime.self_info``."""
    return build_self_info(
        public_key=self_info.get("public_key") or "00" * 32,
        name=self_info.get("name") or "RemoteTerm",
        tx_power=self_info.get("tx_power") or 20,
        max_tx_power=self_info.get("max_tx_power") or 22,
        lat=float(self_info.get("adv_lat") or 0),
        lon=float(self_info.get("adv_lon") or 0),
        multi_acks=bool(self_info.get("multi_acks")),
        advert_loc=bool(self_info.get("adv_loc_policy")),
        radio_freq=float(self_info.get("radio_freq") or 915.0),
        radio_bw=float(self_info.get("radio_bw") or 250.0),
        radio_sf=int(self_info.get("radio_sf") or 10),
        radio_cr=int(self_info.get("radio_cr") or 7),
    )


def build_device_info(path_hash_mode: int = 0) -> bytes:
    """Build a ``RESP_DEVICE_INFO`` payload (response to ``CMD_DEVICE_QUERY``)."""
    out = bytearray()
    out.append(RESP_DEVICE_INFO)
    out.append(PROXY_FW_VER)
    out.append(PROXY_MAX_CONTACTS_RAW)  # ×2 by reader
    out.append(PROXY_MAX_CHANNELS)
    out.extend(struct.pack("<I", 0))  # ble_pin
    out.extend(pad(PROXY_FW_BUILD.encode(), 12))
    out.extend(pad(PROXY_MODEL.encode(), 40))
    out.extend(pad(PROXY_FW_VERSION.encode(), 20))
    out.append(0)  # repeat mode (fw v9+)
    out.append(path_hash_mode)  # (fw v10+)
    return bytes(out)
