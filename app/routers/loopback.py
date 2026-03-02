"""WebSocket endpoint for loopback transport (browser-bridged radio connection)."""

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from app.config import settings
from app.loopback import LoopbackTransport
from app.radio import radio_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.websocket("/ws/transport")
async def loopback_transport(websocket: WebSocket) -> None:
    """Bridge a browser-side serial/BLE connection to the backend MeshCore stack.

    Protocol:
      1. Client sends init JSON: {"type": "init", "mode": "serial"|"ble"}
      2. Binary frames flow bidirectionally (raw bytes for BLE, framed for serial)
      3. Either side can send {"type": "disconnect"} to tear down
    """
    # Guard: reject if an explicit transport is configured via env vars
    if not settings.loopback_eligible:
        await websocket.accept()
        await websocket.close(code=4003, reason="Explicit transport configured")
        return

    # Guard: reject if the radio is already connected (direct or another loopback)
    if radio_manager.is_connected:
        await websocket.accept()
        await websocket.close(code=4004, reason="Radio already connected")
        return

    await websocket.accept()

    transport: LoopbackTransport | None = None
    setup_task: asyncio.Task | None = None

    try:
        # Wait for init message
        init_raw = await asyncio.wait_for(websocket.receive_text(), timeout=10.0)
        init_msg = json.loads(init_raw)

        if init_msg.get("type") != "init" or init_msg.get("mode") not in ("serial", "ble"):
            await websocket.close(code=4001, reason="Invalid init message")
            return

        mode = init_msg["mode"]
        logger.info("Loopback init: mode=%s", mode)

        # Create transport and MeshCore instance
        transport = LoopbackTransport(websocket, mode)

        from meshcore import MeshCore

        mc = MeshCore(transport, auto_reconnect=False, max_reconnect_attempts=0)
        await mc.connect()

        if not mc.is_connected:
            logger.warning("Loopback MeshCore failed to connect")
            await websocket.close(code=4005, reason="MeshCore handshake failed")
            return

        connection_info = f"Loopback ({mode})"
        radio_manager.connect_loopback(mc, connection_info)

        # Run post-connect setup in background so the receive loop can run
        setup_task = asyncio.create_task(radio_manager.post_connect_setup())

        # Main receive loop
        while True:
            message = await websocket.receive()

            if message.get("type") == "websocket.disconnect":
                break

            if "bytes" in message and message["bytes"]:
                transport.handle_rx(message["bytes"])
            elif "text" in message and message["text"]:
                try:
                    text_msg = json.loads(message["text"])
                    if text_msg.get("type") == "disconnect":
                        logger.info("Loopback client requested disconnect")
                        break
                except (json.JSONDecodeError, TypeError):
                    pass

    except WebSocketDisconnect:
        logger.info("Loopback WebSocket disconnected")
    except asyncio.TimeoutError:
        logger.warning("Loopback init timeout")
        if websocket.client_state == WebSocketState.CONNECTED:
            await websocket.close(code=4002, reason="Init timeout")
    except Exception as e:
        logger.exception("Loopback error: %s", e)
    finally:
        if setup_task is not None:
            setup_task.cancel()
            try:
                await setup_task
            except (asyncio.CancelledError, Exception):
                pass

        await radio_manager.disconnect_loopback()

        if websocket.client_state == WebSocketState.CONNECTED:
            try:
                await websocket.close()
            except Exception:
                pass
