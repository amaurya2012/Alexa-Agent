"""Task tools: add_task, list_tasks, complete_task, delete_task."""
from __future__ import annotations

from datetime import date
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from pydantic import BaseModel, ConfigDict, Field

from app import database as db
from mcp_server.tools import (
    CONFIRM_DESCRIPTION,
    RecordId,
    SafeStr,
    confirmation_required,
    guarded,
    parse_input,
    read_only_annotations,
    write_annotations,
)

TITLE_MAX = 200
NOTES_MAX = 1000


class AddTaskInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: SafeStr = Field(min_length=1, max_length=TITLE_MAX)
    notes: SafeStr | None = Field(default=None, max_length=NOTES_MAX)
    priority: Literal["low", "normal", "high"] = "normal"
    due_date: date | None = None


class ListTasksInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["pending", "completed", "all"] = "pending"
    limit: int = Field(default=50, strict=True, ge=1, le=100)


class TaskIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task_id: RecordId


class DeleteTaskInput(TaskIdInput):
    confirm: bool = Field(default=False, strict=True)


@guarded
def add_task(
    title: Annotated[str, Field(description="Short task title.", max_length=TITLE_MAX)],
    notes: Annotated[str | None, Field(description="Optional extra details.", max_length=NOTES_MAX)] = None,
    priority: Annotated[Literal["low", "normal", "high"], Field(description="Task priority.")] = "normal",
    due_date: Annotated[str | None, Field(description="Optional due date, YYYY-MM-DD.")] = None,
) -> dict[str, Any]:
    """Create a new to-do task."""
    data = parse_input(AddTaskInput, title=title, notes=notes, priority=priority, due_date=due_date)
    task = db.insert_task(
        data.title, data.notes, data.priority, data.due_date.isoformat() if data.due_date else None
    )
    return {"ok": True, "message": "Task created", "task": task}


@guarded
def list_tasks(
    status: Annotated[Literal["pending", "completed", "all"], Field(description="Which tasks to list.")] = "pending",
    limit: Annotated[int, Field(description="Maximum number of tasks (1-100).", ge=1, le=100)] = 50,
) -> dict[str, Any]:
    """List tasks, pending ones by default."""
    data = parse_input(ListTasksInput, status=status, limit=limit)
    tasks = db.list_tasks(None if data.status == "all" else data.status, data.limit)
    return {"ok": True, "message": f"{len(tasks)} task(s) found", "count": len(tasks), "tasks": tasks}


@guarded
def complete_task(
    task_id: Annotated[int, Field(description="ID of the task to mark as completed.", ge=1)],
) -> dict[str, Any]:
    """Mark a task as completed."""
    data = parse_input(TaskIdInput, task_id=task_id)
    task, changed = db.complete_task(data.task_id)
    return {"ok": True, "message": "Task completed" if changed else "Task was already completed", "task": task}


@guarded
def delete_task(
    task_id: Annotated[int, Field(description="ID of the task to permanently delete.", ge=1)],
    confirm: Annotated[bool, Field(description=CONFIRM_DESCRIPTION)] = False,
) -> dict[str, Any]:
    """Permanently delete a task. Requires explicit user confirmation before it executes."""
    data = parse_input(DeleteTaskInput, task_id=task_id, confirm=confirm)
    task = db.get_task(data.task_id)
    if task is None:
        raise ToolError(f"Task {data.task_id} not found.")
    if not data.confirm:
        return confirmation_required(f"Delete task #{task['id']} '{task['title']}'", task=task)
    deleted = db.delete_task(data.task_id)
    return {"ok": True, "executed": True, "message": "Task deleted", "task": deleted}


def register(mcp: MCPServer) -> None:
    mcp.tool(name="add_task", annotations=write_annotations())(add_task)
    mcp.tool(name="list_tasks", annotations=read_only_annotations())(list_tasks)
    mcp.tool(name="complete_task", annotations=write_annotations(idempotent=True))(complete_task)
    mcp.tool(name="delete_task", annotations=write_annotations(destructive=True, idempotent=True))(delete_task)
