"""dashboard/server.py
FastAPI-based dashboard server for REX metrics.

Provides:
- Static file serving for dashboard UI
- REST API for current stats
- WebSocket for real-time updates
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from pathlib import Path
from typing import Optional, Set

logger = logging.getLogger(__name__)

# Global state for the dashboard server
_server_thread: Optional[threading.Thread] = None
_should_stop = threading.Event()
_websocket_clients: Set = set()


def _get_app():
    """Create and configure the FastAPI application."""
    try:
        from fastapi import FastAPI, WebSocket, WebSocketDisconnect
        from fastapi.responses import HTMLResponse, JSONResponse
        from fastapi.staticfiles import StaticFiles
    except ImportError:
        raise ImportError(
            "Dashboard dependencies not installed. "
            "Install with: pip install rex-voice-assistant[dashboard]"
        )

    from rex_main.metrics import metrics

    app = FastAPI(title="REX Dashboard", docs_url=None, redoc_url=None)

    # Static files directory
    static_dir = Path(__file__).parent / "static"

    @app.get("/", response_class=HTMLResponse)
    async def index():
        """Serve the dashboard HTML."""
        index_file = static_dir / "index.html"
        if index_file.exists():
            return HTMLResponse(content=index_file.read_text(), status_code=200)
        return HTMLResponse(content="<h1>Dashboard not found</h1>", status_code=404)

    @app.get("/api/stats")
    async def get_stats():
        """Get current session statistics."""
        return JSONResponse(content=metrics.get_session_stats())

    @app.get("/api/commands")
    async def get_commands():
        """Get command frequency data."""
        return JSONResponse(content=metrics.get_command_frequency())

    @app.get("/api/recent")
    async def get_recent():
        """Get recent transcriptions."""
        return JSONResponse(content=metrics.get_recent_transcriptions(limit=20))

    @app.get("/api/history")
    async def get_history(minutes: int = 60):
        """Get latency history for charts."""
        return JSONResponse(content=metrics.get_latency_history(minutes=minutes))

    @app.websocket("/ws")
    async def websocket_endpoint(websocket: WebSocket):
        """WebSocket endpoint for real-time updates."""
        logger.info("WebSocket connection attempt from %s", websocket.client)
        try:
            await websocket.accept()
            _websocket_clients.add(websocket)
            logger.info("WebSocket client connected, total: %d", len(_websocket_clients))

            try:
                while True:
                    # Check stop signal
                    if _should_stop.is_set():
                        break

                    # Send stats every second
                    data = {
                        "stats": metrics.get_session_stats(),
                        "recent": metrics.get_recent_transcriptions(limit=10),
                        "commands": metrics.get_command_frequency()[:10],
                    }
                    await websocket.send_json(data)
                    await asyncio.sleep(1)
            except WebSocketDisconnect:
                logger.info("WebSocket client disconnected normally")
            except Exception as e:
                logger.warning("WebSocket error: %s", e)
            finally:
                _websocket_clients.discard(websocket)
                logger.info("WebSocket client disconnected, total: %d", len(_websocket_clients))
        except Exception as e:
            logger.error("Failed to accept WebSocket connection: %s", e)
            import traceback
            logger.error(traceback.format_exc())

    # Mount static files last (catch-all for CSS, JS)
    if static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    return app


def _run_server(host: str, port: int):
    """Run the uvicorn server in a thread."""
    try:
        import uvicorn
    except ImportError:
        raise ImportError(
            "Dashboard dependencies not installed. "
            "Install with: pip install rex-voice-assistant[dashboard]"
        )

    app = _get_app()

    # Use INFO level to see connection attempts in logs
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        access_log=True,
    )
    server = uvicorn.Server(config)

    # Run until stop signal
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    async def serve():
        await server.serve()

    try:
        loop.run_until_complete(serve())
    except Exception as e:
        if not _should_stop.is_set():
            logger.error("Dashboard server error: %s", e)
    finally:
        loop.close()


def start_dashboard(host: str = "127.0.0.1", port: int = 9876) -> bool:
    """Start the dashboard server in a background thread.

    Args:
        host: Host to bind to (default: localhost only)
        port: Port to listen on (default: 9876)

    Returns:
        True if started successfully, False if already running or failed

    Raises:
        ImportError: If dashboard dependencies (fastapi, uvicorn) are not installed
    """
    global _server_thread

    # Check dependencies before starting thread
    try:
        import uvicorn  # noqa: F401
        import fastapi  # noqa: F401
    except ImportError:
        raise ImportError(
            "Dashboard dependencies not installed. "
            "Install with: pip install rex-voice-assistant[dashboard]"
        )

    if _server_thread is not None and _server_thread.is_alive():
        logger.warning("Dashboard server already running")
        return False

    _should_stop.clear()

    try:
        _server_thread = threading.Thread(
            target=_run_server,
            args=(host, port),
            daemon=True,
            name="rex-dashboard"
        )
        _server_thread.start()
        logger.info("Dashboard started at http://%s:%d", host, port)
        return True
    except Exception as e:
        logger.error("Failed to start dashboard: %s", e)
        return False


def stop_dashboard():
    """Stop the dashboard server."""
    global _server_thread

    _should_stop.set()

    # Close all websocket connections
    for ws in list(_websocket_clients):
        try:
            asyncio.run(ws.close())
        except Exception:
            pass
    _websocket_clients.clear()

    if _server_thread is not None:
        _server_thread.join(timeout=2)
        _server_thread = None

    logger.info("Dashboard stopped")


def is_running() -> bool:
    """Check if dashboard server is running."""
    return _server_thread is not None and _server_thread.is_alive()
