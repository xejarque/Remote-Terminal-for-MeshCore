"""TCP server lifecycle, session registry, and broadcast event dispatch."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .session import ProxySession

logger = logging.getLogger(__name__)

# ── Session registry ─────────────────────────────────────────────────

_sessions: set[ProxySession] = set()
_server: asyncio.Server | None = None


def register(session: ProxySession) -> None:
    _sessions.add(session)


def unregister(session: ProxySession) -> None:
    _sessions.discard(session)


# ── Event dispatch (called from broadcast_event) ─────────────────────


async def dispatch_event(event_type: str, data: dict[str, Any]) -> None:
    """Dispatch a broadcast event to all connected proxy sessions.

    Called from :func:`app.websocket.broadcast_event` for ``message``,
    ``message_acked``, and ``contact`` events.
    """
    for session in list(_sessions):
        try:
            if event_type == "message":
                await session.on_event_message(data)
            elif event_type == "contact":
                await session.on_event_contact(data)
        except Exception:
            logger.exception("Error dispatching %s to %s", event_type, session.addr)


# ── TCP client handler ───────────────────────────────────────────────


async def _handle_client(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
) -> None:
    session = ProxySession(reader, writer)
    register(session)
    try:
        await session.run()
    finally:
        unregister(session)


# ── Server lifecycle ─────────────────────────────────────────────────


async def start(host: str, port: int) -> None:
    """Start the TCP proxy server."""
    global _server
    if _server is not None:
        return

    _server = await asyncio.start_server(_handle_client, host, port)
    addrs = ", ".join(str(s.getsockname()) for s in _server.sockets)
    logger.info("TCP proxy listening on %s", addrs)


async def stop() -> None:
    """Stop the TCP proxy server and disconnect all clients."""
    global _server
    if _server is None:
        return

    # Close all active sessions
    for session in list(_sessions):
        try:
            session.writer.close()
        except Exception:
            pass
    _sessions.clear()

    _server.close()
    await _server.wait_closed()
    _server = None
    logger.info("TCP proxy stopped")
