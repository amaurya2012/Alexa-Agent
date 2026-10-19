"""Tool validation (direct calls) and real MCP-protocol tests against a live Streamable HTTP server."""
import dataclasses
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from mcp.server.mcpserver.exceptions import ToolError

from app import database as db
from app.config import get_settings
from app.errors import McpUnavailableError
from app.mcp_client import McpToolClient, to_bedrock_tool_spec
from mcp_server.tools import inventory, reminders, tasks


def future(**delta) -> str:
    return (datetime.now(timezone.utc) + timedelta(**delta)).isoformat(timespec="seconds")


# ------------------------------------------------------------------ validation (independent of MCP transport)
@pytest.mark.parametrize(
    "kwargs",
    [
        {"title": ""},
        {"title": "   "},
        {"title": "x" * 201},
        {"title": "bad\x00title"},
        {"title": "ok", "priority": "urgent"},
        {"title": "ok", "due_date": "next tuesday"},
        {"title": "ok", "notes": "n" * 1001},
    ],
)
def test_add_task_rejects_invalid_input(kwargs):
    with pytest.raises(ToolError):
        tasks.add_task(**kwargs)
    assert db.list_tasks(None) == []


def test_add_task_ok_and_normalises():
    out = tasks.add_task(title="  Buy milk  ", priority="high", due_date="2030-05-01")
    assert out["message"] == "Task created"
    assert out["task"]["title"] == "Buy milk" and out["task"]["due_date"] == "2030-05-01"


def test_list_and_complete_tasks_validate_ids_and_limits():
    tasks.add_task(title="a")
    assert tasks.list_tasks()["count"] == 1
    with pytest.raises(ToolError):
        tasks.list_tasks(limit=0)
    with pytest.raises(ToolError):
        tasks.complete_task(task_id=0)
    with pytest.raises(ToolError):
        tasks.complete_task(task_id=True)  # strict int: bool rejected
    with pytest.raises(ToolError, match="not found"):
        tasks.complete_task(task_id=42)
    assert tasks.complete_task(task_id=1)["message"] == "Task completed"


def test_delete_task_requires_confirmation():
    tasks.add_task(title="keep me")
    first = tasks.delete_task(task_id=1)
    assert first["confirmation_required"] is True and first["executed"] is False
    assert db.get_task(1) is not None  # nothing deleted

    with pytest.raises(ToolError):
        tasks.delete_task(task_id=1, confirm="yes")  # confirm must be a real boolean
    assert db.get_task(1) is not None

    done = tasks.delete_task(task_id=1, confirm=True)
    assert done["message"] == "Task deleted" and db.get_task(1) is None
    with pytest.raises(ToolError, match="not found"):
        tasks.delete_task(task_id=1, confirm=True)


@pytest.mark.parametrize(
    "remind_at",
    ["2030-01-01T09:00:00", "yesterday", future(seconds=-60), future(days=400), ""],
)
def test_create_reminder_rejects_bad_times(remind_at):
    with pytest.raises(ToolError):
        reminders.create_reminder(text="call mom", remind_at=remind_at)
    assert db.list_reminders() == []


def test_create_reminder_is_store_only_and_says_so():
    out = reminders.create_reminder(text="call mom", remind_at=future(hours=2))
    assert out["notification_delivery"] == "not_configured"
    assert "no notification" in out["message"].lower()
    assert "stored only" in out["notice"].lower()
    assert reminders.list_reminders()["count"] == 1


def test_update_inventory_confirmation_rules():
    add = inventory.update_inventory(item_name="eggs", operation="add", quantity=6)
    assert add["executed"] is True and add["item"]["quantity"] == 18

    for op, qty in (("remove", 2), ("set", 5)):
        pending = inventory.update_inventory(item_name="eggs", operation=op, quantity=qty)
        assert pending["confirmation_required"] is True and pending["executed"] is False
    assert inventory.check_inventory(item_name="eggs")["items"][0]["quantity"] == 18

    removed = inventory.update_inventory(item_name="eggs", operation="remove", quantity=8, confirm=True)
    assert removed["item"]["quantity"] == 10


@pytest.mark.parametrize(
    "kwargs",
    [
        {"item_name": "", "operation": "add", "quantity": 1},
        {"item_name": "eggs", "operation": "delete", "quantity": 1},
        {"item_name": "eggs", "operation": "add", "quantity": 0},
        {"item_name": "eggs", "operation": "add", "quantity": -3},
        {"item_name": "eggs", "operation": "add", "quantity": 10**7},
        {"item_name": "eggs", "operation": "add", "quantity": 1.5},
        {"item_name": "x" * 81, "operation": "add", "quantity": 1},
        {"item_name": "eggs; DROP TABLE tasks", "operation": "add", "quantity": 1, "unit": "u" * 21},
    ],
)
def test_update_inventory_rejects_invalid_input(kwargs):
    with pytest.raises(ToolError):
        inventory.update_inventory(**kwargs)


def test_sql_metacharacters_are_just_data():
    inventory.update_inventory(item_name="x'); DROP TABLE tasks;--", operation="add", quantity=1)
    assert db.list_tasks(None) == []  # table still exists and works
    assert inventory.check_inventory(item_name="DROP TABLE")["count"] == 1


def test_check_inventory_variants():
    assert inventory.check_inventory()["count"] >= 8
    assert inventory.check_inventory(item_name="nothing here")["found"] is False
    milk = inventory.check_inventory(item_name="milk")["items"][0]
    assert milk["low_stock"] is True  # seeded at the threshold


# ------------------------------------------------------------------ real MCP protocol over Streamable HTTP
EXPECTED_TOOLS = {
    "add_task", "list_tasks", "complete_task", "delete_task",
    "create_reminder", "list_reminders", "check_inventory", "update_inventory",
}


async def test_mcp_discovery_over_http(mcp_server):
    found = await McpToolClient(get_settings()).list_tools()
    assert {t.name for t in found} == EXPECTED_TOOLS
    by_name = {t.name: t for t in found}
    assert by_name["delete_task"].requires_confirmation and by_name["update_inventory"].requires_confirmation
    assert not by_name["add_task"].requires_confirmation
    assert by_name["list_tasks"].read_only


async def test_mcp_call_tool_roundtrip(mcp_server):
    client = McpToolClient(get_settings())
    result = await client.call_tool("add_task", {"title": "via MCP", "priority": "low"})
    assert not result.is_error and result.data["message"] == "Task created"
    assert db.get_task(result.data["task"]["id"])["title"] == "via MCP"

    pending = await client.call_tool("delete_task", {"task_id": result.data["task"]["id"]})
    assert pending.data["confirmation_required"] is True
    assert db.get_task(result.data["task"]["id"]) is not None


async def test_mcp_errors_are_clean(mcp_server):
    client = McpToolClient(get_settings())
    bad = await client.call_tool("add_task", {"title": ""})
    assert bad.is_error and "Traceback" not in bad.text and "errors.pydantic.dev" not in bad.data["error"]
    unknown = await client.call_tool("rm_rf", {})
    assert unknown.is_error
    missing = await client.call_tool("complete_task", {"task_id": 12345})
    assert missing.is_error and "not found" in missing.data["error"]


async def test_mcp_server_requires_bearer_token(mcp_server):
    async with httpx.AsyncClient() as http:
        no_token = await http.post(f"{mcp_server}/mcp", json={})
        assert no_token.status_code == 401
        wrong = await http.post(f"{mcp_server}/mcp", json={}, headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 401
        assert (await http.get(f"{mcp_server}/healthz")).status_code == 200  # health stays open

    wrong_client = McpToolClient(dataclasses.replace(get_settings(), mcp_auth_token="wrong"))
    with pytest.raises(McpUnavailableError):
        await wrong_client.list_tools()


async def test_mcp_unreachable_raises_clean_error():
    dead = McpToolClient(dataclasses.replace(get_settings(), mcp_server_url="http://127.0.0.1:9/mcp"))
    with pytest.raises(McpUnavailableError) as exc:
        await dead.list_tools()
    assert "127.0.0.1" not in exc.value.message


async def test_bedrock_tool_spec_translation(mcp_server):
    specs = {t.name: to_bedrock_tool_spec(t)["toolSpec"] for t in await McpToolClient(get_settings()).list_tools()}
    add = specs["add_task"]["inputSchema"]["json"]
    assert add["type"] == "object" and add["required"] == ["title"]
    assert "title" in add["properties"]  # a property NAMED title survives schema cleaning
    assert "anyOf" not in add["properties"]["notes"]  # Optional[...] collapsed
    assert "title" not in add["properties"]["title"]  # annotation titles removed
    for name in ("delete_task", "update_inventory"):  # the model can never see or set `confirm`
        assert "confirm" not in specs[name]["inputSchema"]["json"]["properties"]
    assert all(s["name"] and s["description"] for s in specs.values())
