"""Read-only endpoints: tool catalogue and data views. There is NO endpoint that executes a tool directly;
tools run only through the agent (POST /api/chat), which enforces confirmation for risky actions."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app import database as db
from app.agent import Agent
from app.config import REMINDER_NOTICE
from app.deps import get_agent, require_api_key
from app.mcp_client import public_input_schema
from app.schemas import (
    InventoryItemOut, InventoryResponse, ReminderOut, RemindersResponse, TaskOut, TasksResponse, ToolInfo, ToolsResponse,
)

router = APIRouter(prefix="/api", tags=["data"], dependencies=[Depends(require_api_key)])


@router.get("/tools", response_model=ToolsResponse, summary="List MCP tools discovered from the tool server")
async def list_tools(agent: Agent = Depends(get_agent)) -> ToolsResponse:
    tools = await agent.list_tools()
    infos = [
        ToolInfo(
            name=t.name,
            description=t.description,
            input_schema=public_input_schema(t.input_schema),
            read_only=t.read_only,
            requires_confirmation=t.requires_confirmation,
        )
        for t in tools
    ]
    return ToolsResponse(tools=infos, count=len(infos))


@router.get("/tasks", response_model=TasksResponse, summary="All tasks")
def get_tasks() -> TasksResponse:
    tasks = [TaskOut(**t) for t in db.list_tasks(None, 500)]
    return TasksResponse(tasks=tasks, count=len(tasks))


@router.get("/reminders", response_model=RemindersResponse, summary="All stored reminders (no notifications are sent)")
def get_reminders() -> RemindersResponse:
    reminders = [ReminderOut(**r) for r in db.list_reminders(500)]
    return RemindersResponse(reminders=reminders, count=len(reminders), notice=REMINDER_NOTICE)


@router.get("/inventory", response_model=InventoryResponse, summary="Inventory with low-stock flags")
def get_inventory() -> InventoryResponse:
    items = [
        InventoryItemOut(**i, low_stock=i["quantity"] <= i["low_stock_threshold"]) for i in db.list_inventory()
    ]
    return InventoryResponse(items=items, count=len(items))
