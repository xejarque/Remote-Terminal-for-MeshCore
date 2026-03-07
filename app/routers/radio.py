import logging
from collections.abc import Awaitable, Callable
from typing import Any, cast

from fastapi import APIRouter, HTTPException
from meshcore import EventType
from pydantic import BaseModel, Field

from app.dependencies import require_connected
from app.radio import radio_manager
from app.radio_sync import send_advertisement as do_send_advertisement
from app.radio_sync import sync_radio_time

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/radio", tags=["radio"])


class RadioSettings(BaseModel):
    freq: float = Field(description="Frequency in MHz")
    bw: float = Field(description="Bandwidth in kHz")
    sf: int = Field(description="Spreading factor (7-12)")
    cr: int = Field(description="Coding rate (1-4)")


class RadioConfigResponse(BaseModel):
    public_key: str = Field(description="Public key (64-char hex)")
    name: str
    lat: float
    lon: float
    tx_power: int = Field(description="Transmit power in dBm")
    max_tx_power: int = Field(description="Maximum transmit power in dBm")
    path_hash_mode: int = Field(
        default=0, description="Default outbound path hash mode (0=1 byte, 1=2 bytes, 2=3 bytes)"
    )
    path_hash_mode_supported: bool = Field(
        default=False, description="Whether the connected radio/firmware exposes path hash mode"
    )
    radio: RadioSettings


class RadioConfigUpdate(BaseModel):
    name: str | None = None
    lat: float | None = None
    lon: float | None = None
    tx_power: int | None = Field(default=None, description="Transmit power in dBm")
    path_hash_mode: int | None = Field(
        default=None, ge=0, le=2, description="Default outbound path hash mode"
    )
    radio: RadioSettings | None = None


class PrivateKeyUpdate(BaseModel):
    private_key: str = Field(description="Private key as hex string")


async def _get_path_hash_mode_info(mc) -> tuple[int, bool]:
    """Return (mode, supported) using the best interface available."""
    commands = getattr(mc, "commands", None)
    send_device_query = cast(
        Callable[[], Awaitable[Any]] | None, getattr(commands, "send_device_query", None)
    )
    if commands is None or not callable(send_device_query):
        return 0, False

    try:
        result = await send_device_query()
    except Exception as exc:
        logger.debug("Failed to query device info for path hash mode: %s", exc)
        return 0, False

    if result is None or result.type == EventType.ERROR:
        return 0, False

    payload = result.payload if isinstance(result.payload, dict) else {}
    mode = payload.get("path_hash_mode")
    if isinstance(mode, int) and 0 <= mode <= 2:
        return mode, True

    return 0, False


async def _set_path_hash_mode(mc, mode: int):
    """Set path hash mode using either the new helper or raw command fallback."""
    commands = getattr(mc, "commands", None)
    if commands is None:
        raise HTTPException(status_code=503, detail="Radio command interface unavailable")

    set_path_hash_mode = cast(
        Callable[[int], Awaitable[Any]] | None, getattr(commands, "set_path_hash_mode", None)
    )
    send_raw = cast(
        Callable[[bytes, list[EventType]], Awaitable[Any]] | None,
        getattr(commands, "send", None),
    )

    if callable(set_path_hash_mode):
        result = await set_path_hash_mode(mode)
    elif callable(send_raw):
        data = b"\x3d\x00" + int(mode).to_bytes(1, "little")
        result = await send_raw(data, [EventType.OK, EventType.ERROR])
    else:
        raise HTTPException(
            status_code=400,
            detail="Installed meshcore interface library cannot set path hash mode",
        )

    if result is not None and result.type == EventType.ERROR:
        raise HTTPException(status_code=500, detail="Failed to set path hash mode on radio")

    return result


@router.get("/config", response_model=RadioConfigResponse)
async def get_radio_config() -> RadioConfigResponse:
    """Get the current radio configuration."""
    require_connected()

    async with radio_manager.radio_operation("get_radio_config") as mc:
        info = mc.self_info
        if not info:
            raise HTTPException(status_code=503, detail="Radio info not available")

        path_hash_mode, path_hash_mode_supported = await _get_path_hash_mode_info(mc)

        return RadioConfigResponse(
            public_key=info.get("public_key", ""),
            name=info.get("name", ""),
            lat=info.get("adv_lat", 0.0),
            lon=info.get("adv_lon", 0.0),
            tx_power=info.get("tx_power", 0),
            max_tx_power=info.get("max_tx_power", 0),
            path_hash_mode=path_hash_mode,
            path_hash_mode_supported=path_hash_mode_supported,
            radio=RadioSettings(
                freq=info.get("radio_freq", 0.0),
                bw=info.get("radio_bw", 0.0),
                sf=info.get("radio_sf", 0),
                cr=info.get("radio_cr", 0),
            ),
        )


@router.patch("/config", response_model=RadioConfigResponse)
async def update_radio_config(update: RadioConfigUpdate) -> RadioConfigResponse:
    """Update radio configuration. Only provided fields will be updated."""
    require_connected()

    async with radio_manager.radio_operation("update_radio_config") as mc:
        if update.name is not None:
            logger.info("Setting radio name to %s", update.name)
            await mc.commands.set_name(update.name)

        if update.lat is not None or update.lon is not None:
            current_info = mc.self_info
            lat = update.lat if update.lat is not None else current_info.get("adv_lat", 0.0)
            lon = update.lon if update.lon is not None else current_info.get("adv_lon", 0.0)
            logger.info("Setting radio coordinates to %f, %f", lat, lon)
            await mc.commands.set_coords(lat=lat, lon=lon)

        if update.tx_power is not None:
            logger.info("Setting TX power to %d dBm", update.tx_power)
            await mc.commands.set_tx_power(val=update.tx_power)

        if update.path_hash_mode is not None:
            current_mode, supported = await _get_path_hash_mode_info(mc)
            if not supported:
                raise HTTPException(
                    status_code=400,
                    detail="Connected radio/firmware does not expose path hash mode",
                )
            if current_mode != update.path_hash_mode:
                logger.info("Setting path hash mode to %d", update.path_hash_mode)
                await _set_path_hash_mode(mc, update.path_hash_mode)

        if update.radio is not None:
            logger.info(
                "Setting radio params: freq=%f MHz, bw=%f kHz, sf=%d, cr=%d",
                update.radio.freq,
                update.radio.bw,
                update.radio.sf,
                update.radio.cr,
            )
            await mc.commands.set_radio(
                freq=update.radio.freq,
                bw=update.radio.bw,
                sf=update.radio.sf,
                cr=update.radio.cr,
            )

        # Sync time with system clock
        await sync_radio_time(mc)

        # Re-fetch self_info so the response reflects the changes we just made.
        # Commands like set_name() write to flash but don't update the cached
        # self_info — send_appstart() triggers a fresh SELF_INFO from the radio.
        await mc.commands.send_appstart()

    return await get_radio_config()


@router.put("/private-key")
async def set_private_key(update: PrivateKeyUpdate) -> dict:
    """Set the radio's private key. This is write-only."""
    require_connected()

    try:
        key_bytes = bytes.fromhex(update.private_key)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid hex string for private key") from None

    logger.info("Importing private key")
    async with radio_manager.radio_operation("import_private_key") as mc:
        result = await mc.commands.import_private_key(key_bytes)

        if result.type == EventType.ERROR:
            raise HTTPException(
                status_code=500, detail=f"Failed to import private key: {result.payload}"
            )

        # Re-export from radio so the server-side keystore uses the new key
        # for DM decryption immediately, rather than waiting for reconnect.
        from app.keystore import export_and_store_private_key

        keystore_refreshed = await export_and_store_private_key(mc)
        if not keystore_refreshed:
            logger.warning("Keystore refresh failed after import, retrying once")
            keystore_refreshed = await export_and_store_private_key(mc)

    if not keystore_refreshed:
        raise HTTPException(
            status_code=500,
            detail=(
                "Private key imported on radio, but server-side keystore "
                "refresh failed. Reconnect to apply the new key for DM decryption."
            ),
        )

    return {"status": "ok"}


@router.post("/advertise")
async def send_advertisement() -> dict:
    """Send a flood advertisement to announce presence on the mesh.

    Manual advertisement requests always send immediately, updating the
    last_advert_time which affects when the next periodic/startup advert
    can occur.

    Returns:
        status: "ok" if sent successfully
    """
    require_connected()

    logger.info("Sending flood advertisement")
    async with radio_manager.radio_operation("manual_advertisement") as mc:
        success = await do_send_advertisement(mc, force=True)

    if not success:
        raise HTTPException(status_code=500, detail="Failed to send advertisement")

    return {"status": "ok"}


async def _attempt_reconnect() -> dict:
    """Shared reconnection logic for reboot and reconnect endpoints."""
    if radio_manager.is_reconnecting:
        return {
            "status": "pending",
            "message": "Reconnection already in progress",
            "connected": False,
        }

    success = await radio_manager.reconnect()
    if not success:
        raise HTTPException(
            status_code=503, detail="Failed to reconnect. Check radio connection and power."
        )

    try:
        await radio_manager.post_connect_setup()
    except Exception as e:
        logger.exception("Post-connect setup failed after reconnect")
        raise HTTPException(
            status_code=503,
            detail=f"Radio connected but setup failed: {e}",
        ) from e

    return {"status": "ok", "message": "Reconnected successfully", "connected": True}


@router.post("/reboot")
async def reboot_radio() -> dict:
    """Reboot the radio, or reconnect if not currently connected.

    If connected: sends reboot command, connection will temporarily drop and auto-reconnect.
    If not connected: attempts to reconnect (same as /reconnect endpoint).
    """
    if radio_manager.is_connected:
        logger.info("Rebooting radio")
        async with radio_manager.radio_operation("reboot_radio") as mc:
            await mc.commands.reboot()
        return {
            "status": "ok",
            "message": "Reboot command sent. Radio will reconnect automatically.",
        }

    logger.info("Radio not connected, attempting reconnect")
    return await _attempt_reconnect()


@router.post("/reconnect")
async def reconnect_radio() -> dict:
    """Attempt to reconnect to the radio.

    This will try to re-establish connection to the radio, with auto-detection
    if no specific port is configured. Useful when the radio has been disconnected
    or power-cycled.
    """
    if radio_manager.is_connected:
        if radio_manager.is_setup_complete:
            return {"status": "ok", "message": "Already connected", "connected": True}

        logger.info("Radio connected but setup incomplete, retrying setup")
        try:
            await radio_manager.post_connect_setup()
            return {"status": "ok", "message": "Setup completed", "connected": True}
        except Exception as e:
            logger.exception("Post-connect setup failed")
            raise HTTPException(
                status_code=503,
                detail=f"Radio connected but setup failed: {e}",
            ) from e

    logger.info("Manual reconnect requested")
    return await _attempt_reconnect()
