"""Helpers for working with hex-encoded routing paths."""


def get_path_hop_width(path_hex: str | None, path_len: int | None) -> int:
    """Return hop width in hex chars, falling back to legacy 1-byte hops."""
    if not path_hex:
        return 2
    if isinstance(path_len, int) and path_len > 0 and len(path_hex) % path_len == 0:
        hop_width = len(path_hex) // path_len
        if hop_width > 0 and hop_width % 2 == 0:
            return hop_width
    return 2


def split_path_hops(path_hex: str | None, path_len: int | None) -> list[str]:
    """Split a hex path string into hop-sized chunks."""
    if not path_hex:
        return []

    hop_width = get_path_hop_width(path_hex, path_len)
    normalized = path_hex.lower()
    return [
        normalized[i : i + hop_width]
        for i in range(0, len(normalized), hop_width)
        if i + hop_width <= len(normalized)
    ]


def first_path_hop(path_hex: str | None, path_len: int | None) -> str | None:
    """Return the first hop from a hex path string, if any."""
    hops = split_path_hops(path_hex, path_len)
    return hops[0] if hops else None
