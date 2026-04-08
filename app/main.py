import os
import sys

# ---------------------------------------------------------------------------
# Windows event-loop fix for MQTT fanout (aiomqtt / paho-mqtt) compatibility
# ---------------------------------------------------------------------------
# On Windows, uvicorn's default "auto" loop explicitly creates ProactorEventLoop,
# which does NOT implement add_reader()/add_writer() — calls that paho-mqtt
# requires internally.  Setting the event loop *policy* alone is not enough
# because uvicorn's "auto" factory bypasses it.
#
# The fix: re-exec the current process with "--loop none", which tells uvicorn
# to let asyncio.run() create the loop through the standard policy (where we
# have just installed WindowsSelectorEventLoopPolicy).
#
# Guards:
#   - "--loop" already in argv  → we (or the operator) already handled it
#   - MESHCORE_NO_AUTO_LOOP_ON_WIN32=true → operator opt-out for custom
#     runners, test harnesses, or other non-uvicorn invocations
# ---------------------------------------------------------------------------
_win32_needs_reexec = (
    sys.platform == "win32"
    and os.environ.get("MESHCORE_NO_AUTO_LOOP_ON_WIN32", "").lower() not in ("true", "1")
    and "--loop" not in sys.argv
)
# Skip re-exec when --reload is active: on Windows os.execv spawns a new
# process and exits, so the reloader's child dies and a fresh uvicorn
# (with its own reloader) starts — creating doubled watchers or a loop.
# Also skip if sys.executable is missing (embedded / frozen Python).
if _win32_needs_reexec and "--reload" in sys.argv:
    print(
        "\n" + "!" * 78 + "\n"
        "  WINDOWS + --reload DETECTED\n" + "!" * 78 + "\n"
        "\n"
        "  We can't auto-fix the event loop when --reload is active because\n"
        "  the re-exec would fight with uvicorn's reloader process.\n"
        "\n"
        "  If you need MQTT fanout, add --loop none to your command:\n"
        "\n"
        "    uv run uvicorn app.main:app --reload \033[1m--loop none\033[0m [... other options ...]\n"
        "\n"
        "  Everything else works fine as-is.\n"
        "\n" + "!" * 78 + "\n",
        file=sys.stderr,
        flush=True,
    )
    _win32_needs_reexec = False

if _win32_needs_reexec and not sys.executable:
    # Embedded or frozen Python — can't re-exec, just warn.
    _win32_needs_reexec = False

if _win32_needs_reexec:
    import asyncio as _asyncio

    _asyncio.set_event_loop_policy(
        _asyncio.WindowsSelectorEventLoopPolicy()  # type: ignore[attr-defined]
    )

    print(
        "\n" + "=" * 78 + "\n"
        "  HALLO FRIEND WINDOWS USER <3 WE GOTTA ADJUST THINGS BEFORE YOU STARTUP\n"
        + "="
        * 78
        + "\n"
        "\n"
        "  uvicorn's default event loop on Windows (ProactorEventLoop) is not\n"
        "  compatible with aiomqtt/paho-mqtt, which require add_reader() /\n"
        "  add_writer(). Re-executing with '--loop none' so uvicorn honours\n"
        "  WindowsSelectorEventLoopPolicy and MQTT fanout can function.\n"
        ""
        "  In English: The code we use for MQTT is fussy. We're restarting\n"
        "  the server with the right settings for MQTT to work.\n"
        "\n"
        "  This may or may not work :) If the app starts up after this without a warning, you're good to go.\n"
        "\n" + "=" * 78 + "\n",
        file=sys.stderr,
        flush=True,
    )

    # sys.argv[0] on Windows is typically a .exe console-script launcher
    # (e.g. .venv\Scripts\uvicorn.exe) which Python can't open as a script.
    # use "python -m uvicorn" instead, forwarding the original arguments.
    # yes, this is brittle as all hell.
    try:
        os.execv(
            sys.executable,
            [sys.executable, "-m", "uvicorn"] + sys.argv[1:] + ["--loop", "none"],
        )
    except Exception:
        # execv failed — fall through and let the app start normally.
        # MQTT fanout will not work, but everything else will.
        print(
            "\n" + "!" * 78 + "\n"
            "  AUTO-RESTART FAILED :<\n" + "!" * 78 + "\n"
            "\n"
            "  We tried to restart uvicorn with the necessary settings\n"
            "  automatically, but there was a problem with the invocation\n"
            "  (not shocking; this is a fragile system).\n"
            "\n"
            "  Please rerun RemoteTerm with a command like:\n"
            "\n"
            "    uv run uvicorn app.main:app \033[1m--loop none\033[0m [... other options ...]\n"
            "\n"
            "  Setting '--loop none' on uvicorn startup will put you in a good\n"
            "  state for MQTT and bypass this self-repair.\n"
            "\n"
            "  The server is starting anyway -- everything except MQTT fanout\n"
            "  will work normally. If you want to suppress this attempt, \n"
            "  set the env var MESHCORE_NO_AUTO_LOOP_ON_WIN32=true\n"
            "\n" + "!" * 78 + "\n",
            file=sys.stderr,
            flush=True,
        )

# ---------------------------------------------------------------------------

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse

from app.config import settings as server_settings
from app.config import setup_logging
from app.database import db
from app.frontend_static import (
    register_first_available_frontend_static_routes,
    register_frontend_missing_fallback,
)
from app.radio import RadioDisconnectedError
from app.radio_sync import (
    stop_background_contact_reconciliation,
    stop_message_polling,
    stop_periodic_advert,
    stop_periodic_sync,
    stop_telemetry_collect,
)
from app.routers import (
    channels,
    contacts,
    debug,
    fanout,
    health,
    messages,
    packets,
    radio,
    read_state,
    repeaters,
    rooms,
    settings,
    statistics,
    ws,
)
from app.security import add_optional_basic_auth_middleware
from app.services.radio_noise_floor import start_noise_floor_sampling, stop_noise_floor_sampling
from app.services.radio_runtime import radio_runtime as radio_manager
from app.version_info import get_app_build_info

setup_logging()
logger = logging.getLogger(__name__)


async def _startup_radio_connect_and_setup() -> None:
    """Connect/setup the radio in the background so HTTP serving can start immediately."""
    try:
        connected = await radio_manager.reconnect_and_prepare(broadcast_on_success=True)
        if connected:
            logger.info("Connected to radio")
        else:
            logger.warning("Failed to connect to radio on startup")
    except Exception:
        logger.exception("Failed to connect to radio on startup")


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
    await start_noise_floor_sampling()

    # Always start connection monitor (even if initial connection failed)
    await radio_manager.start_connection_monitor()

    # Start fanout modules (MQTT, etc.) from database configs
    from app.fanout.manager import fanout_manager

    try:
        await fanout_manager.load_from_db()
    except Exception:
        logger.exception("Failed to start fanout modules")

    startup_radio_task = asyncio.create_task(_startup_radio_connect_and_setup())
    app.state.startup_radio_task = startup_radio_task

    yield

    logger.info("Shutting down")
    if startup_radio_task and not startup_radio_task.done():
        startup_radio_task.cancel()
        try:
            await startup_radio_task
        except asyncio.CancelledError:
            pass
    await fanout_manager.stop_all()
    await radio_manager.stop_connection_monitor()
    await stop_background_contact_reconciliation()
    await stop_message_polling()
    await stop_noise_floor_sampling()
    await stop_periodic_advert()
    await stop_periodic_sync()
    await stop_telemetry_collect()
    if radio_manager.meshcore:
        await radio_manager.meshcore.stop_auto_message_fetching()
    await radio_manager.disconnect()
    await db.disconnect()


app = FastAPI(
    title="RemoteTerm for MeshCore API",
    description="API for interacting with MeshCore mesh radio networks",
    version=get_app_build_info().version,
    lifespan=lifespan,
)

add_optional_basic_auth_middleware(app, server_settings)
app.add_middleware(GZipMiddleware, minimum_size=500)
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
app.include_router(debug.router, prefix="/api")
app.include_router(fanout.router, prefix="/api")
app.include_router(radio.router, prefix="/api")
app.include_router(contacts.router, prefix="/api")
app.include_router(repeaters.router, prefix="/api")
app.include_router(rooms.router, prefix="/api")
app.include_router(channels.router, prefix="/api")
app.include_router(messages.router, prefix="/api")
app.include_router(packets.router, prefix="/api")
app.include_router(read_state.router, prefix="/api")
app.include_router(settings.router, prefix="/api")
app.include_router(statistics.router, prefix="/api")
app.include_router(ws.router, prefix="/api")

# Serve frontend static files in production
FRONTEND_DIST_DIR = Path(__file__).parent.parent / "frontend" / "dist"
FRONTEND_PREBUILT_DIR = Path(__file__).parent.parent / "frontend" / "prebuilt"
if not register_first_available_frontend_static_routes(
    app, [FRONTEND_DIST_DIR, FRONTEND_PREBUILT_DIR]
):
    register_frontend_missing_fallback(app)
