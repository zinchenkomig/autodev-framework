"""API middleware for error handling and alerts."""

from __future__ import annotations

import logging
import re
import traceback
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urlsplit
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

logger = logging.getLogger(__name__)

LOCAL_ORIGIN = re.compile(r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$")
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


class SameOriginMiddleware(BaseHTTPMiddleware):
    """Reject state-changing browser requests from other origins (CSRF).

    Project apps live on sibling subdomains (``*.stage.<domain>``), which browsers
    treat as same-site: SameSite=Lax doesn't stop them sending the session cookie.
    Browsers always send ``Origin`` on such requests; clients without it (curl,
    the Telegram webhook) are let through.
    """

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        origin = request.headers.get("origin")
        if request.method not in SAFE_METHODS and origin and not _allowed_origin(origin, request):
            return JSONResponse({"detail": "Cross-origin request rejected"}, status_code=403)
        return await call_next(request)


def _allowed_origin(origin: str, request: Request) -> bool:
    if LOCAL_ORIGIN.match(origin):
        return True
    host = request.headers.get("x-forwarded-host") or request.headers.get("host") or ""
    return urlsplit(origin).netloc.lower() == host.split(",")[0].strip().lower()


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
            from autodev.api.routes.alerts import notify_alert
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

                alert.notified = await notify_alert(alert)
                await session.commit()

        except Exception as e:
            logger.error(f"Failed to create error alert: {e}")
