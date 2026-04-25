"""Tests for app.tcp_proxy.encoder — binary payload builders."""

import struct

from app.tcp_proxy.encoder import (
    build_contact,
    build_contact_from_dict,
    build_device_info,
    build_self_info,
    build_self_info_from_runtime,
)
from app.tcp_proxy.protocol import (
    PROXY_FW_VER,
    PROXY_MAX_CHANNELS,
    PROXY_MAX_CONTACTS_RAW,
    PUSH_NEW_ADVERT,
    RESP_CONTACT,
    RESP_DEVICE_INFO,
    RESP_SELF_INFO,
)

EXAMPLE_KEY = "ab" * 32  # 64-char hex → 32 bytes


# ── build_contact ────────────────────────────────────────────────────


class TestBuildContact:
    def test_basic_structure(self):
        payload = build_contact(EXAMPLE_KEY, name="Alice")
        assert payload[0] == RESP_CONTACT
        # public key at bytes 1-32
        assert payload[1:33] == bytes.fromhex(EXAMPLE_KEY)
        # total length: 1 + 32 + 1(type) + 1(flags) + 1(path) + 64(path) + 32(name) + 4(adv) + 4(lat) + 4(lon) + 4(lastmod) = 148
        assert len(payload) == 148

    def test_push_variant(self):
        payload = build_contact(EXAMPLE_KEY, push=True)
        assert payload[0] == PUSH_NEW_ADVERT
        assert len(payload) == 148

    def test_favorite_flag(self):
        payload = build_contact(EXAMPLE_KEY, favorite=True)
        flags_byte = payload[34]  # byte 1+32+1 = 34
        assert flags_byte & 0x01 == 1

    def test_not_favorite(self):
        payload = build_contact(EXAMPLE_KEY, favorite=False)
        flags_byte = payload[34]
        assert flags_byte & 0x01 == 0

    def test_flood_path(self):
        payload = build_contact(EXAMPLE_KEY)
        path_byte = payload[35]  # byte 1+32+1+1 = 35
        assert path_byte == 0xFF

    def test_direct_path(self):
        payload = build_contact(
            EXAMPLE_KEY,
            direct_path="aabb",
            direct_path_len=2,
            direct_path_hash_mode=1,
        )
        path_byte = payload[35]
        # mode=1 → 0x40, hops=2 → 0x02 → packed = 0x42
        assert path_byte == 0x42

    def test_name_truncated(self):
        long_name = "A" * 50
        payload = build_contact(EXAMPLE_KEY, name=long_name)
        # name field is 32 bytes at offset 100 (1+32+1+1+1+64)
        name_bytes = payload[100:132]
        assert name_bytes == b"A" * 32

    def test_lat_lon_encoding(self):
        payload = build_contact(EXAMPLE_KEY, lat=45.123456, lon=-122.654321)
        lat_offset = 136  # 1+32+1+1+1+64+32+4 = 136
        lat = struct.unpack_from("<i", payload, lat_offset)[0]
        lon = struct.unpack_from("<i", payload, lat_offset + 4)[0]
        assert abs(lat - 45123456) < 2
        assert abs(lon - (-122654321)) < 2

    def test_contact_type(self):
        payload = build_contact(EXAMPLE_KEY, contact_type=2)
        assert payload[33] == 2  # type byte at offset 1+32


# ── build_contact_from_dict ──────────────────────────────────────────


class TestBuildContactFromDict:
    def test_minimal_dict(self):
        data = {"public_key": EXAMPLE_KEY}
        payload = build_contact_from_dict(data)
        assert payload[0] == RESP_CONTACT
        assert len(payload) == 148

    def test_full_dict(self):
        data = {
            "public_key": EXAMPLE_KEY,
            "type": 1,
            "favorite": True,
            "name": "Bob",
            "direct_path": "ff",
            "direct_path_len": 1,
            "direct_path_hash_mode": 0,
            "last_advert": 1700000000,
            "lat": 37.7749,
            "lon": -122.4194,
            "first_seen": 1699000000,
        }
        payload = build_contact_from_dict(data)
        assert payload[33] == 1  # type
        assert payload[34] & 0x01 == 1  # favorite

    def test_push_flag(self):
        data = {"public_key": EXAMPLE_KEY}
        payload = build_contact_from_dict(data, push=True)
        assert payload[0] == PUSH_NEW_ADVERT


# ── build_self_info ──────────────────────────────────────────────────


class TestBuildSelfInfo:
    def test_basic_structure(self):
        payload = build_self_info()
        assert payload[0] == RESP_SELF_INFO
        assert payload[1] == 1  # adv_type = CHAT
        # minimum length: 1+1+1+1+32+4+4+1+1+1+1+4+4+1+1 + len("RemoteTerm") = 68
        assert len(payload) >= 58

    def test_name_appended(self):
        payload = build_self_info(name="TestNode")
        # name starts at offset 58
        name_bytes = payload[58:]
        assert name_bytes == b"TestNode"

    def test_public_key_encoded(self):
        payload = build_self_info(public_key=EXAMPLE_KEY)
        assert payload[4:36] == bytes.fromhex(EXAMPLE_KEY)

    def test_radio_params(self):
        payload = build_self_info(radio_freq=868.0, radio_bw=125.0, radio_sf=12, radio_cr=8)
        freq = struct.unpack_from("<I", payload, 48)[0]
        bw = struct.unpack_from("<I", payload, 52)[0]
        assert freq == 868000
        assert bw == 125000
        assert payload[56] == 12  # sf
        assert payload[57] == 8  # cr

    def test_multi_acks_flag(self):
        on = build_self_info(multi_acks=True)
        off = build_self_info(multi_acks=False)
        assert on[44] == 1
        assert off[44] == 0


class TestBuildSelfInfoFromRuntime:
    def test_from_self_info_dict(self):
        info = {
            "public_key": EXAMPLE_KEY,
            "name": "MyRadio",
            "tx_power": 18,
            "max_tx_power": 22,
            "adv_lat": 40.0,
            "adv_lon": -74.0,
            "multi_acks": 1,
            "adv_loc_policy": 1,
            "radio_freq": 915.0,
            "radio_bw": 250.0,
            "radio_sf": 10,
            "radio_cr": 7,
        }
        payload = build_self_info_from_runtime(info)
        assert payload[0] == RESP_SELF_INFO
        assert payload[58:] == b"MyRadio"

    def test_missing_fields_use_defaults(self):
        payload = build_self_info_from_runtime({})
        assert payload[0] == RESP_SELF_INFO
        assert payload[58:] == b"RemoteTerm"


# ── build_device_info ────────────────────────────────────────────────


class TestBuildDeviceInfo:
    def test_basic_structure(self):
        payload = build_device_info()
        assert payload[0] == RESP_DEVICE_INFO
        assert payload[1] == PROXY_FW_VER
        assert payload[2] == PROXY_MAX_CONTACTS_RAW
        assert payload[3] == PROXY_MAX_CHANNELS

    def test_path_hash_mode(self):
        payload = build_device_info(path_hash_mode=2)
        # path_hash_mode is at offset 81 (1+1+1+1+4+12+40+20+1 = 81)
        assert payload[81] == 2

    def test_expected_length(self):
        # fw_ver=11 → 1+1+1+1+4+12+40+20+1+1 = 82 bytes
        payload = build_device_info()
        assert len(payload) == 82
