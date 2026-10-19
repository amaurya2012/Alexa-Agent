"""Pydantic models that define the public HTTP contract (see backend/README.md)."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.config import get_settings


# ------------------------------------------------------------------ chat
class ChatRequest(BaseModel):
    """POST /api/chat body. Unknown extra fields are ignored for frontend compatibility."""

    model_config = ConfigDict(extra="ignore")

    message: str = Field(description="The user's natural-language request.", examples=["Add a task to buy milk"])

    @field_validator("message")
    @classmethod
    def _validate_message(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("message must not be empty")
        limit = get_settings().max_message_chars
        if len(value) > limit:
            raise ValueError(f"message must be at most {limit} characters")
        if any(ord(c) < 32 and c not in "\n\t\r" for c in value):
            raise ValueError("message must not contain control characters")
        return value


class ToolEvent(BaseModel):
    tool: str = Field(examples=["add_task"])
    status: Literal["success", "error", "confirmation_required"]
    message: str = Field(examples=["Task created"])


class ChatResponse(BaseModel):
    response: str
    events: list[ToolEvent]


# ------------------------------------------------------------------ health
class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    mode: Literal["mock", "bedrock"]
    database: Literal["ok", "error"]
    mcp_server: Literal["ok", "unreachable"]
    version: str


# ------------------------------------------------------------------ data views
class TaskOut(BaseModel):
    id: int
    title: str
    notes: str | None = None
    priority: Literal["low", "normal", "high"]
    due_date: str | None = None
    status: Literal["pending", "completed"]
    created_at: str
    completed_at: str | None = None


class ReminderOut(BaseModel):
    id: int
    text: str
    remind_at: str = Field(description="UTC, ISO 8601")
    status: str = Field(description="Always 'stored': no notification is ever sent by this backend.")
    created_at: str


class InventoryItemOut(BaseModel):
    id: int
    item_name: str
    quantity: int
    unit: str
    low_stock_threshold: int
    low_stock: bool
    updated_at: str


class TasksResponse(BaseModel):
    tasks: list[TaskOut]
    count: int


class RemindersResponse(BaseModel):
    reminders: list[ReminderOut]
    count: int
    notice: str


class InventoryResponse(BaseModel):
    items: list[InventoryItemOut]
    count: int


class ToolInfo(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    requires_confirmation: bool = Field(
        description="True when the backend asks the user to confirm before the tool executes."
    )


class ToolsResponse(BaseModel):
    tools: list[ToolInfo]
    count: int


# ------------------------------------------------------------------ errors
class ErrorDetail(BaseModel):
    field: str
    message: str


class ErrorResponse(BaseModel):
    error: str
    message: str
    details: list[ErrorDetail] | None = None
    request_id: str | None = None
