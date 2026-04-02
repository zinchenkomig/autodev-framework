"""API middleware for error handling and alerts."""

from __future__ import annotations

import logging
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)


class ErrorAlertMiddleware(BaseHTTPMiddleware):
    """Middleware to create alerts for 500 errors."""

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        try:
            response = await call_next(request)

            # Create alert for 500 errors
            if response.status_code >= 500:
                await self._create_error_alert(
                    request=request,
                    status_code=response.status_code,
                    error_message=f"HTTP {response.status_code} error",
                )

            return response

        except Exception as e:
            # Log and create alert for unhandled exceptions
            tb = traceback.format_exc()
            logger.exception("Unhandled exception in request")

            await self._create_error_alert(request=request, status_code=500, error_message=str(e), traceback=tb)

            raise

    async def _create_error_alert(
        self, request: Request, status_code: int, error_message: str, traceback: str | None = None
    ) -> None:
        """Create an alert for API errors."""
        try:
            from autodev.api.database import SessionLocal
            from autodev.api.routes.alerts import notify_openclaw
            from autodev.core.models import Alert

            message = f"Endpoint: {request.method} {request.url.path}\n"
            message += f"Error: {error_message}\n"
            if traceback:
                message += f"\nTraceback:\n{traceback[:2000]}"

            async with SessionLocal() as session:
                alert = Alert(
                    id=uuid4(),
                    type="api_error",
                    severity="high" if status_code >= 500 else "medium",
                    title=f"API Error {status_code}: {request.url.path}",
                    message=message,
                    source=f"{request.method} {request.url.path}",
                    resolved=False,
                    notified=False,
                    created_at=datetime.now(UTC),
                )
                session.add(alert)
                await session.commit()

                # Notify OpenClaw
                await notify_openclaw(alert)
                alert.notified = True
                await session.commit()

        except Exception as e:
            logger.error(f"Failed to create error alert: {e}")
