"""Loopback transport: bridges a browser-side serial/BLE connection over WebSocket."""

import asyncio
import logging
from typing import Any, Literal

from starlette.websockets import WebSocket, WebSocketState

logger = logging.getLogger(__name__)


class LoopbackTransport:
    """ConnectionProtocol implementation that tunnels bytes over a WebSocket.

    For serial mode, applies the same 0x3c + 2-byte LE size framing that
    meshcore's SerialConnection uses.  For BLE mode, passes raw bytes through
    (matching BLEConnection behaviour).
    """

    def __init__(self, websocket: WebSocket, mode: Literal["serial", "ble"]) -> None:
        self._ws = websocket
        self._mode = mode
        self._reader: Any = None
        self._disconnect_callback: Any = None

        # Serial framing state (mirrors meshcore serial_cx.py handle_rx)
        self._header = b""
        self._inframe = b""
        self._frame_started = False
        self._frame_size = 0

    # -- ConnectionProtocol methods ------------------------------------------

    async def connect(self) -> str:
        """No-op — the WebSocket is already established."""
        info = f"Loopback ({self._mode})"
        logger.info("Loopback transport connected: %s", info)
        return info

    async def disconnect(self) -> None:
        """Ask the browser to release the hardware and close the WS."""
        try:
            if self._ws.client_state == WebSocketState.CONNECTED:
                await self._ws.send_json({"type": "disconnect"})
        except Exception:
            pass  # WS may already be closed

    async def send(self, data: Any) -> None:
        """Send data to the browser (which writes it to the physical radio).

        Serial mode: prepend 0x3c + 2-byte LE size header.
        BLE mode: send raw bytes.
        """
        try:
            if self._ws.client_state != WebSocketState.CONNECTED:
                return
            if self._mode == "serial":
                size = len(data)
                pkt = b"\x3c" + size.to_bytes(2, byteorder="little") + bytes(data)
                await self._ws.send_bytes(pkt)
            else:
                await self._ws.send_bytes(bytes(data))
        except Exception as e:
            logger.debug("Loopback send error: %s", e)

    def set_reader(self, reader: Any) -> None:
        self._reader = reader

    def set_disconnect_callback(self, callback: Any) -> None:
        self._disconnect_callback = callback

    # -- Incoming data from browser ------------------------------------------

    def handle_rx(self, data: bytes) -> None:
        """Process bytes received from the browser.

        Serial mode: accumulate bytes, strip framing, deliver payload.
        BLE mode: deliver raw bytes directly.
        """
        if self._mode == "serial":
            self._handle_rx_serial(data)
        else:
            self._handle_rx_ble(data)

    def _handle_rx_ble(self, data: bytes) -> None:
        if self._reader is not None:
            asyncio.create_task(self._reader.handle_rx(data))

    def _handle_rx_serial(self, data: bytes) -> None:
        """Mirror meshcore's SerialConnection.handle_rx state machine."""
        raw = bytes(data)
        headerlen = len(self._header)

        if not self._frame_started:
            if len(raw) >= 3 - headerlen:
                self._header = self._header + raw[: 3 - headerlen]
                self._frame_started = True
                self._frame_size = int.from_bytes(self._header[1:], byteorder="little")
                remainder = raw[3 - headerlen :]
                # Reset header for next frame
                self._header = b""
                if remainder:
                    self._handle_rx_serial(remainder)
            else:
                self._header = self._header + raw
        else:
            framelen = len(self._inframe)
            if framelen + len(raw) < self._frame_size:
                self._inframe = self._inframe + raw
            else:
                self._inframe = self._inframe + raw[: self._frame_size - framelen]
                if self._reader is not None:
                    asyncio.create_task(self._reader.handle_rx(self._inframe))
                remainder = raw[self._frame_size - framelen :]
                self._frame_started = False
                self._inframe = b""
                if remainder:
                    self._handle_rx_serial(remainder)

    def reset_framing(self) -> None:
        """Reset the serial framing state machine."""
        self._header = b""
        self._inframe = b""
        self._frame_started = False
        self._frame_size = 0
