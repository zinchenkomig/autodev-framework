"""WebSocket endpoints for real-time event streaming.

Clients connect to receive live domain events (task updates, agent status,
log tails) without polling the REST API.

TODO: Implement authentication for WebSocket connections.
TODO: Add per-connection event type filtering.
TODO: Add reconnection / missed-event catchup via cursor.
TODO: Integrate with EventBus to fan out events to all connected clients.
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)
router = APIRouter()

# Active WebSocket connections grouped by channel.
# TODO: Replace with proper connection manager class.
_connections: dict[str, list[WebSocket]] = defaultdict(list)


async def broadcast(channel: str, message: dict[str, Any]) -> None:
    """Send a message to all clients subscribed to a channel.

    Args:
        channel: Channel identifier (e.g. ``"events"``, ``"logs"``).
        message: JSON-serialisable payload.

    TODO: Add error handling for disconnected clients.
    """
    clients = _connections.get(channel, [])
    if not clients:
        return
    results = await asyncio.gather(
        *(ws.send_json(message) for ws in clients),
        return_exceptions=True,
    )
    for ws, result in zip(clients, results):
        if isinstance(result, Exception):
            logger.warning("Failed to send to WebSocket client: %s", result)


@router.websocket("/events")
async def events_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for live domain event streaming.

    Clients receive all domain events published after connection.

    TODO: Authenticate connection before accepting.
    TODO: Support event type filter via query param.
    """
    await websocket.accept()
    _connections["events"].append(websocket)
    logger.info("WebSocket client connected to /ws/events")

    try:
        while True:
            # Keep connection alive; server pushes events via broadcast().
            # TODO: Handle client-sent filter commands.
            data = await websocket.receive_text()
            logger.debug("WebSocket /events received: %r", data)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /ws/events")
    finally:
        _connections["events"].remove(websocket)


@router.websocket("/logs")
async def logs_ws(websocket: WebSocket) -> None:
    """WebSocket endpoint for live log streaming.

    TODO: Subscribe to log handler and stream records to client.
    TODO: Support log level filter via query param.
    """
    await websocket.accept()
    _connections["logs"].append(websocket)
    logger.info("WebSocket client connected to /ws/logs")

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /ws/logs")
    finally:
        _connections["logs"].remove(websocket)
