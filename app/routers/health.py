import os

from fastapi import APIRouter
from pydantic import BaseModel

from app.config import settings
from app.radio import radio_manager
from app.repository import RawPacketRepository

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    radio_connected: bool
    connection_info: str | None
    database_size_mb: float
    oldest_undecrypted_timestamp: int | None
    mqtt_status: str | None = None
    loopback_eligible: bool = False


async def build_health_data(radio_connected: bool, connection_info: str | None) -> dict:
    """Build the health status payload used by REST endpoint and WebSocket broadcasts."""
    db_size_mb = 0.0
    try:
        db_size_bytes = os.path.getsize(settings.database_path)
        db_size_mb = round(db_size_bytes / (1024 * 1024), 2)
    except OSError:
        pass

    oldest_ts = None
    try:
        oldest_ts = await RawPacketRepository.get_oldest_undecrypted()
    except RuntimeError:
        pass  # Database not connected

    # MQTT status
    mqtt_status: str | None = None
    try:
        from app.mqtt import mqtt_publisher

        if mqtt_publisher._mqtt_configured():
            mqtt_status = "connected" if mqtt_publisher.connected else "disconnected"
        else:
            mqtt_status = "disabled"
    except Exception:
        pass

    return {
        "status": "ok" if radio_connected else "degraded",
        "radio_connected": radio_connected,
        "connection_info": connection_info,
        "database_size_mb": db_size_mb,
        "oldest_undecrypted_timestamp": oldest_ts,
        "mqtt_status": mqtt_status,
        "loopback_eligible": settings.loopback_eligible,
    }


@router.get("/health", response_model=HealthResponse)
async def healthcheck() -> HealthResponse:
    """Check if the API is running and if the radio is connected."""
    data = await build_health_data(radio_manager.is_connected, radio_manager.connection_info)
    return HealthResponse(**data)
