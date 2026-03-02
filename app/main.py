import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import setup_logging
from app.database import db
from app.frontend_static import register_frontend_missing_fallback, register_frontend_static_routes
from app.radio import RadioDisconnectedError, radio_manager
from app.radio_sync import (
    stop_message_polling,
    stop_periodic_advert,
    stop_periodic_sync,
)
from app.routers import (
    channels,
    contacts,
    health,
    loopback,
    messages,
    packets,
    radio,
    read_state,
    repeaters,
    settings,
    statistics,
    ws,
)

setup_logging()
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Manage database and radio connection lifecycle."""
    await db.connect()
    logger.info("Database connected")

    # Ensure default channels exist in the database even before the radio
    # connects. Without this, a fresh or disconnected instance would return
    # zero channels from GET /channels until the first successful radio sync.
    from app.radio_sync import ensure_default_channels

    await ensure_default_channels()

    try:
        await radio_manager.connect()
        logger.info("Connected to radio")
        await radio_manager.post_connect_setup()
    except Exception as e:
        logger.warning("Failed to connect to radio on startup: %s", e)

    # Always start connection monitor (even if initial connection failed)
    await radio_manager.start_connection_monitor()

    # Start MQTT publisher if configured
    from app.mqtt import mqtt_publisher
    from app.repository import AppSettingsRepository

    try:
        mqtt_settings = await AppSettingsRepository.get()
        await mqtt_publisher.start(mqtt_settings)
    except Exception as e:
        logger.warning("Failed to start MQTT publisher: %s", e)

    yield

    logger.info("Shutting down")
    await mqtt_publisher.stop()
    await radio_manager.stop_connection_monitor()
    await stop_message_polling()
    await stop_periodic_advert()
    await stop_periodic_sync()
    if radio_manager.meshcore:
        await radio_manager.meshcore.stop_auto_message_fetching()
    await radio_manager.disconnect()
    await db.disconnect()


def _get_version() -> str:
    """Read version from pyproject.toml so it stays in sync automatically."""
    try:
        pyproject = Path(__file__).resolve().parent.parent / "pyproject.toml"
        for line in pyproject.read_text().splitlines():
            if line.startswith("version = "):
                return line.split('"')[1]
    except Exception:
        pass
    return "0.0.0"


app = FastAPI(
    title="RemoteTerm for MeshCore API",
    description="API for interacting with MeshCore mesh radio networks",
    version=_get_version(),
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(RadioDisconnectedError)
async def radio_disconnected_handler(request: Request, exc: RadioDisconnectedError):
    """Return 503 when a radio disconnect race occurs during an operation."""
    return JSONResponse(status_code=503, content={"detail": "Radio not connected"})


# API routes - all prefixed with /api for production compatibility
app.include_router(health.router, prefix="/api")
app.include_router(radio.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(repeaters.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(packets.router, prefix="/api")
app.include_router(read_state.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(statistics.router, prefix="/api")
app.include_router(ws.router, prefix="/api")
app.include_router(loopback.router, prefix="/api")

# Serve frontend static files in production
FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "dist"
if not register_frontend_static_routes(app, FRONTEND_DIR):
    register_frontend_missing_fallback(app)
