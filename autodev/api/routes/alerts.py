"""Alerts API routes."""

from __future__ import annotations

import uuid
import os
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession
import httpx

from autodev.api.database import get_session
from autodev.core.models import Alert, AlertSeverity, AlertType

router = APIRouter(tags=["alerts"])

OPENCLAW_URL = os.environ.get("OPENCLAW_URL", "http://localhost:3033")
OPENCLAW_CHAT_ID = os.environ.get("OPENCLAW_CHAT_ID", "861853668")


class AlertCreate(BaseModel):
    type: str
    severity: str = "medium"
    title: str
    message: str | None = None
    source: str | None = None


class AlertResponse(BaseModel):
    id: str
    type: str
    severity: str
    title: str
    message: str | None
    source: str | None
    resolved: bool
    resolved_at: datetime | None
    resolved_by: str | None
    notified: bool
    created_at: datetime

    model_config = {"from_attributes": True}


class AlertStats(BaseModel):
    total: int
    unresolved: int
    critical: int
    high: int
    by_type: dict[str, int]


async def notify_openclaw(alert: Alert) -> bool:
    """Send alert to OpenClaw for Brian to handle."""
    severity_emoji = {
        "critical": "🚨",
        "high": "🔴",
        "medium": "🟡",
        "low": "🟢"
    }
    emoji = severity_emoji.get(alert.severity, "⚠️")
    
    message = (
        f"{emoji} **AutoDev Alert** [{alert.severity.upper()}]\n\n"
        f"**Type:** {alert.type}\n"
        f"**Title:** {alert.title}\n"
    )
    if alert.message:
        message += f"\n**Details:**\n```\n{alert.message[:1000]}\n```\n"
    if alert.source:
        message += f"\n**Source:** {alert.source}"
    message += f"\n\n**Alert ID:** `{alert.id}`"
    
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{OPENCLAW_URL}/api/send",
                json={
                    "channel": "telegram",
                    "account": "default",
                    "chatId": OPENCLAW_CHAT_ID,
                    "message": message
                },
                timeout=10.0
            )
            return resp.status_code == 200
    except Exception as e:
        print(f"Failed to notify OpenClaw: {e}")
        return False


@router.post("", summary="Create a new alert")
async def create_alert(
    alert_data: AlertCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    notify: bool = Query(True, description="Send notification to OpenClaw"),
) -> AlertResponse:
    """Create a new system alert."""
    alert = Alert(
        id=uuid.uuid4(),
        type=alert_data.type,
        severity=alert_data.severity,
        title=alert_data.title,
        message=alert_data.message,
        source=alert_data.source,
        resolved=False,
        notified=False,
        created_at=datetime.now(UTC),
    )
    session.add(alert)
    await session.flush()
    
    # Notify OpenClaw
    if notify:
        notified = await notify_openclaw(alert)
        alert.notified = notified
    
    return AlertResponse(
        id=str(alert.id),
        type=alert.type,
        severity=alert.severity,
        title=alert.title,
        message=alert.message,
        source=alert.source,
        resolved=alert.resolved,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by,
        notified=alert.notified,
        created_at=alert.created_at,
    )


@router.get("", summary="List alerts")
async def list_alerts(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: int = Query(50, ge=1, le=200),
    unresolved_only: bool = Query(False),
    severity: str | None = Query(None),
    alert_type: str | None = Query(None),
) -> list[AlertResponse]:
    """List alerts with optional filters."""
    query = select(Alert).order_by(desc(Alert.created_at)).limit(limit)
    
    if unresolved_only:
        query = query.where(Alert.resolved == False)
    if severity:
        query = query.where(Alert.severity == severity)
    if alert_type:
        query = query.where(Alert.type == alert_type)
    
    result = await session.execute(query)
    alerts = result.scalars().all()
    
    return [
        AlertResponse(
            id=str(a.id),
            type=a.type,
            severity=a.severity,
            title=a.title,
            message=a.message,
            source=a.source,
            resolved=a.resolved,
            resolved_at=a.resolved_at,
            resolved_by=a.resolved_by,
            notified=a.notified,
            created_at=a.created_at,
        )
        for a in alerts
    ]


@router.get("/stats", summary="Get alert statistics")
async def get_alert_stats(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AlertStats:
    """Get alert statistics."""
    result = await session.execute(select(Alert))
    alerts = result.scalars().all()
    
    by_type: dict[str, int] = {}
    for a in alerts:
        by_type[a.type] = by_type.get(a.type, 0) + 1
    
    return AlertStats(
        total=len(alerts),
        unresolved=sum(1 for a in alerts if not a.resolved),
        critical=sum(1 for a in alerts if a.severity == "critical" and not a.resolved),
        high=sum(1 for a in alerts if a.severity == "high" and not a.resolved),
        by_type=by_type,
    )


@router.post("/{alert_id}/resolve", summary="Resolve an alert")
async def resolve_alert(
    alert_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    resolved_by: str = Query("user"),
) -> AlertResponse:
    """Mark an alert as resolved."""
    try:
        aid = uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid alert ID")
    
    alert = await session.get(Alert, aid)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    alert.resolved = True
    alert.resolved_at = datetime.now(UTC)
    alert.resolved_by = resolved_by
    
    return AlertResponse(
        id=str(alert.id),
        type=alert.type,
        severity=alert.severity,
        title=alert.title,
        message=alert.message,
        source=alert.source,
        resolved=alert.resolved,
        resolved_at=alert.resolved_at,
        resolved_by=alert.resolved_by,
        notified=alert.notified,
        created_at=alert.created_at,
    )


@router.delete("/{alert_id}", summary="Delete an alert")
async def delete_alert(
    alert_id: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict:
    """Delete an alert."""
    try:
        aid = uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid alert ID")
    
    alert = await session.get(Alert, aid)
    if not alert:
        raise HTTPException(status_code=404, detail="Alert not found")
    
    await session.delete(alert)
    return {"status": "deleted"}
