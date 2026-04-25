"""MeshCore TCP companion protocol proxy.

Emulates a MeshCore companion radio over TCP, translating the binary
protocol into in-process RemoteTerm operations.  Enable with
``MESHCORE_TCP_PROXY_ENABLED=true``.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def start_tcp_proxy() -> None:
    """Start the TCP proxy server using settings from config."""
    from app.config import settings

    from .server import start

    await start(settings.tcp_proxy_bind, settings.tcp_proxy_port)


async def stop_tcp_proxy() -> None:
    """Stop the TCP proxy server."""
    from .server import stop

    await stop()
