"""Tests for app.tcp_proxy.protocol — frame parsing, helpers, constants."""

from app.tcp_proxy.protocol import (
    ERR_NOT_FOUND,
    ERR_UNSUPPORTED,
    FRAME_RX,
    FRAME_TX,
    RESP_ERR,
    RESP_OK,
    FrameParser,
    build_error,
    build_ok,
    encode_path_byte,
    frame_response,
    pad,
)

# ── frame_response ───────────────────────────────────────────────────


class TestFrameResponse:
    def test_empty_payload(self):
        result = frame_response(b"")
        assert result == bytes([FRAME_RX, 0x00, 0x00])

    def test_short_payload(self):
        result = frame_response(b"\x05\x01")
        assert result[0] == FRAME_RX
        size = int.from_bytes(result[1:3], "little")
        assert size == 2
        assert result[3:] == b"\x05\x01"

    def test_larger_payload(self):
        payload = b"\xaa" * 200
        result = frame_response(payload)
        assert result[0] == FRAME_RX
        size = int.from_bytes(result[1:3], "little")
        assert size == 200
        assert result[3:] == payload


# ── build_ok / build_error ───────────────────────────────────────────


class TestBuildOk:
    def test_no_value(self):
        assert build_ok() == bytes([RESP_OK])

    def test_with_value(self):
        result = build_ok(42)
        assert result[0] == RESP_OK
        assert int.from_bytes(result[1:5], "little") == 42

    def test_zero_value(self):
        result = build_ok(0)
        assert len(result) == 5
        assert int.from_bytes(result[1:5], "little") == 0


class TestBuildError:
    def test_default_code(self):
        assert build_error() == bytes([RESP_ERR, ERR_UNSUPPORTED])

    def test_not_found(self):
        assert build_error(ERR_NOT_FOUND) == bytes([RESP_ERR, ERR_NOT_FOUND])


# ── pad ──────────────────────────────────────────────────────────────


class TestPad:
    def test_shorter_data(self):
        result = pad(b"AB", 5)
        assert result == b"AB\x00\x00\x00"
        assert len(result) == 5

    def test_exact_data(self):
        assert pad(b"ABCDE", 5) == b"ABCDE"

    def test_longer_data(self):
        assert pad(b"ABCDEFGH", 5) == b"ABCDE"

    def test_empty_data(self):
        assert pad(b"", 3) == b"\x00\x00\x00"


# ── encode_path_byte ────────────────────────────────────────────────


class TestEncodePathByte:
    def test_flood_negative_hop(self):
        assert encode_path_byte(-1, 0) == 0xFF

    def test_flood_negative_mode(self):
        assert encode_path_byte(0, -1) == 0xFF

    def test_flood_both_negative(self):
        assert encode_path_byte(-1, -1) == 0xFF

    def test_zero_hops_mode_zero(self):
        assert encode_path_byte(0, 0) == 0x00

    def test_three_hops_mode_one(self):
        # mode=1 → bits 6-7 = 01 → 0x40; hops=3 → 0x03
        assert encode_path_byte(3, 1) == 0x43

    def test_max_hops_mode_two(self):
        # mode=2 → bits 6-7 = 10 → 0x80; hops=63 → 0x3F
        assert encode_path_byte(63, 2) == 0xBF


# ── FrameParser ──────────────────────────────────────────────────────


class TestFrameParser:
    def test_single_complete_frame(self):
        parser = FrameParser()
        # 0x3C + 2-byte LE size (3) + 3 bytes payload
        data = bytes([FRAME_TX, 0x03, 0x00, 0xAA, 0xBB, 0xCC])
        payloads = parser.feed(data)
        assert len(payloads) == 1
        assert payloads[0] == b"\xaa\xbb\xcc"

    def test_two_frames_in_one_chunk(self):
        parser = FrameParser()
        frame1 = bytes([FRAME_TX, 0x02, 0x00, 0x01, 0x02])
        frame2 = bytes([FRAME_TX, 0x01, 0x00, 0xFF])
        payloads = parser.feed(frame1 + frame2)
        assert len(payloads) == 2
        assert payloads[0] == b"\x01\x02"
        assert payloads[1] == b"\xff"

    def test_split_across_chunks(self):
        parser = FrameParser()
        full = bytes([FRAME_TX, 0x04, 0x00, 0x01, 0x02, 0x03, 0x04])
        # Split in the middle of the payload
        p1 = parser.feed(full[:5])
        assert p1 == []
        p2 = parser.feed(full[5:])
        assert len(p2) == 1
        assert p2[0] == b"\x01\x02\x03\x04"

    def test_split_in_header(self):
        parser = FrameParser()
        full = bytes([FRAME_TX, 0x01, 0x00, 0xAA])
        p1 = parser.feed(full[:2])  # marker + first size byte
        assert p1 == []
        p2 = parser.feed(full[2:])  # second size byte + payload
        assert len(p2) == 1
        assert p2[0] == b"\xaa"

    def test_bad_marker_skipped(self):
        parser = FrameParser()
        junk = b"\x00\x00\x00"
        good = bytes([FRAME_TX, 0x01, 0x00, 0xBB])
        payloads = parser.feed(junk + good)
        assert len(payloads) == 1
        assert payloads[0] == b"\xbb"

    def test_oversized_frame_skipped(self):
        parser = FrameParser()
        # Size = 400 (> MAX_FRAME_SIZE=300)
        bad = bytes([FRAME_TX, 0x90, 0x01])
        good = bytes([FRAME_TX, 0x01, 0x00, 0xCC])
        payloads = parser.feed(bad + good)
        assert len(payloads) == 1
        assert payloads[0] == b"\xcc"

    def test_empty_feed(self):
        parser = FrameParser()
        assert parser.feed(b"") == []

    def test_byte_at_a_time(self):
        parser = FrameParser()
        full = bytes([FRAME_TX, 0x02, 0x00, 0xDE, 0xAD])
        payloads = []
        for b in full:
            payloads.extend(parser.feed(bytes([b])))
        assert len(payloads) == 1
        assert payloads[0] == b"\xde\xad"
