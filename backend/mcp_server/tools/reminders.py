"""Reminder tools: create_reminder, list_reminders.

IMPORTANT: reminders are only STORED. This backend does not send notifications (no push, SMS,
email or voice) unless a notification provider is integrated later.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app import database as db
from app.config import REMINDER_NOTICE
from mcp_server.tools import SafeStr, guarded, parse_input, read_only_annotations, write_annotations

TEXT_MAX = 300
MAX_DAYS_AHEAD = 366


class CreateReminderInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    text: SafeStr = Field(min_length=1, max_length=TEXT_MAX)
    remind_at: datetime

    @field_validator("remind_at")
    @classmethod
    def _check_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("must include a timezone offset, e.g. 2026-10-14T09:00:00+00:00 or ...Z")
        value = value.astimezone(timezone.utc)
        now = datetime.now(timezone.utc)
        if value <= now:
            raise ValueError("must be in the future")
        if value > now + timedelta(days=MAX_DAYS_AHEAD):
            raise ValueError(f"must be within {MAX_DAYS_AHEAD} days from now")
        return value


class ListRemindersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    limit: int = Field(default=50, strict=True, ge=1, le=100)


@guarded
def create_reminder(
    text: Annotated[str, Field(description="What to be reminded about.", max_length=TEXT_MAX)],
    remind_at: Annotated[
        str, Field(description="When, as an ISO 8601 timestamp WITH timezone, e.g. 2026-10-14T09:00:00+00:00")
    ],
) -> dict[str, Any]:
    """Store a reminder for a future time. It is stored only - no notification will be sent."""
    data = parse_input(CreateReminderInput, text=text, remind_at=remind_at)
    reminder = db.insert_reminder(data.text, data.remind_at.isoformat(timespec="seconds"))
    return {
        "ok": True,
        "message": "Reminder stored (no notification will be sent: no provider configured)",
        "notification_delivery": "not_configured",
        "notice": REMINDER_NOTICE,
        "reminder": reminder,
    }


@guarded
def list_reminders(
    limit: Annotated[int, Field(description="Maximum number of reminders (1-100).", ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """List stored reminders ordered by time."""
    data = parse_input(ListRemindersInput, limit=limit)
    reminders = db.list_reminders(data.limit)
    return {
        "ok": True,
        "message": f"{len(reminders)} reminder(s) found",
        "count": len(reminders),
        "notice": REMINDER_NOTICE,
        "reminders": reminders,
    }


def register(mcp: MCPServer) -> None:
    mcp.tool(name="create_reminder", annotations=write_annotations())(create_reminder)
    mcp.tool(name="list_reminders", annotations=read_only_annotations())(list_reminders)
