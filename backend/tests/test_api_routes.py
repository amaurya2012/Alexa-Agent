"""HTTP contract tests: real FastAPI app + real MCP server + SQLite, with the mock (demo) model."""
from datetime import datetime, timezone

from app.errors import BedrockError

DEMO = "[DEMO MODE"


def chat(client, message):
    r = client.post("/api/chat", json={"message": message})
    assert r.status_code == 200, r.text
    return r.json()


# ------------------------------------------------------------------ health / docs
def test_health_ok(client):
    body = client.get("/health").json()
    assert body == {"status": "ok", "mode": "mock", "database": "ok", "mcp_server": "ok", "version": body["version"]}


def test_health_degraded_when_mcp_is_down(make_client):
    with make_client(MCP_SERVER_URL="http://127.0.0.1:9/mcp") as c:
        body = c.get("/health").json()
    assert body["status"] == "degraded" and body["mcp_server"] == "unreachable" and body["database"] == "ok"


def test_swagger_docs_and_openapi_available(client):
    assert client.get("/docs").status_code == 200
    paths = client.get("/openapi.json").json()["paths"]
    assert {"/health", "/api/chat", "/api/tasks", "/api/reminders", "/api/inventory", "/api/tools"} <= set(paths)


# ------------------------------------------------------------------ chat contract
def test_chat_response_shape_matches_frontend_contract(client):
    body = chat(client, "add a task to buy milk")
    assert set(body) == {"response", "events"}
    assert body["events"] == [{"tool": "add_task", "status": "success", "message": "Task created"}]
    assert body["response"].startswith(DEMO) and "buy milk" in body["response"]  # mock output is labelled
    tasks = client.get("/api/tasks").json()
    assert tasks["count"] == 1 and tasks["tasks"][0]["title"] == "buy milk" and tasks["tasks"][0]["status"] == "pending"


def test_chat_multiple_tools_in_one_message(client):
    body = chat(client, "add a task to water plants; add a task to pay rent; list my tasks")
    assert [e["tool"] for e in body["events"]] == ["add_task", "add_task", "list_tasks"]
    assert "water plants" in body["response"] and "pay rent" in body["response"]


def test_chat_unrecognised_request_returns_help_not_error(client):
    body = chat(client, "write me a python script")
    assert body["events"] == [] and "demo mode" in body["response"].lower()


def test_chat_validation_errors(client):
    for payload in ({}, {"message": ""}, {"message": "   "}, {"message": 5}, {"message": "x" * 5000}, {"message": "bad\x00"}):
        r = client.post("/api/chat", json=payload)
        assert r.status_code == 422, payload
        err = r.json()
        assert err["error"] == "validation_error" and err["details"] and "request_id" in err
    assert client.post("/api/chat", content="not json", headers={"Content-Type": "application/json"}).status_code == 422


def test_chat_ignores_unknown_extra_fields(client):
    r = client.post("/api/chat", json={"message": "list my tasks", "session_id": "abc", "extra": 1})
    assert r.status_code == 200


# ------------------------------------------------------------------ reminders: stored only
def test_reminders_are_stored_and_the_api_says_no_notification_is_sent(client):
    body = chat(client, "remind me to call mom in 2 hours")
    assert body["events"][0]["tool"] == "create_reminder" and body["events"][0]["status"] == "success"
    assert "no notification" in body["events"][0]["message"].lower()
    assert "stored only" in body["response"].lower()

    data = client.get("/api/reminders").json()
    assert data["count"] == 1 and data["reminders"][0]["text"] == "call mom"
    assert data["reminders"][0]["status"] == "stored" and "stored only" in data["notice"].lower()
    remind_at = datetime.fromisoformat(data["reminders"][0]["remind_at"])
    assert remind_at.tzinfo is not None and remind_at > datetime.now(timezone.utc)


# ------------------------------------------------------------------ confirmation safeguards end to end
def test_delete_requires_confirmation_then_executes(client):
    chat(client, "add a task to old task")
    pending = chat(client, "delete task 1")
    assert pending["events"][0]["status"] == "confirmation_required"
    assert "confirm" in pending["response"].lower()
    assert client.get("/api/tasks").json()["count"] == 1  # still there

    done = chat(client, "confirm")
    assert done["events"] == [{"tool": "delete_task", "status": "success", "message": "Task deleted"}]
    assert client.get("/api/tasks").json()["count"] == 0
    assert chat(client, "confirm")["response"].endswith("There is nothing waiting for confirmation.")


def test_cancel_keeps_the_data(client):
    chat(client, "add a task to keep")
    chat(client, "delete task 1")
    assert "Nothing was changed" in chat(client, "cancel")["response"]
    assert client.get("/api/tasks").json()["count"] == 1


def test_inventory_add_is_immediate_but_remove_needs_confirmation(client):
    added = chat(client, "add 6 eggs to inventory")
    assert added["events"][0]["status"] == "success"

    pending = chat(client, "remove 2 milk from inventory")
    assert pending["events"][0]["status"] == "confirmation_required"
    milk = lambda: next(i for i in client.get("/api/inventory").json()["items"] if i["item_name"] == "milk")
    assert milk()["quantity"] == 2

    assert chat(client, "yes")["events"][0]["status"] == "success"
    assert milk()["quantity"] == 0 and milk()["low_stock"] is True
    eggs = next(i for i in client.get("/api/inventory").json()["items"] if i["item_name"] == "eggs")
    assert eggs["quantity"] == 18


def test_inventory_overdraw_is_a_tool_error_event_not_a_crash(client):
    chat(client, "remove 50 milk from inventory")
    result = chat(client, "confirm")
    assert result["events"][0]["status"] == "error" and "Insufficient stock" in result["events"][0]["message"]


# ------------------------------------------------------------------ data views and tools
def test_data_endpoints_shapes(client):
    inv = client.get("/api/inventory").json()
    assert inv["count"] >= 8 and {"id", "item_name", "quantity", "unit", "low_stock_threshold", "low_stock", "updated_at"} <= set(inv["items"][0])
    assert client.get("/api/tasks").json() == {"tasks": [], "count": 0}
    assert client.get("/api/reminders").json()["reminders"] == []


def test_tools_endpoint_lists_mcp_tools_without_exposing_confirm(client):
    body = client.get("/api/tools").json()
    assert body["count"] == 8
    by_name = {t["name"]: t for t in body["tools"]}
    assert by_name["delete_task"]["requires_confirmation"] and by_name["update_inventory"]["requires_confirmation"]
    assert not by_name["add_task"]["requires_confirmation"] and by_name["list_tasks"]["read_only"]
    assert all("confirm" not in t["input_schema"]["properties"] for t in body["tools"])


def test_there_is_no_direct_tool_execution_endpoint(client):
    assert client.post("/api/tools").status_code == 405
    assert client.post("/api/tools/add_task", json={"title": "x"}).status_code in (404, 405)
    assert client.post("/api/execute", json={}).status_code == 404
    assert client.get("/api/tasks").json()["count"] == 0


# ------------------------------------------------------------------ security & error handling
def test_api_key_enforced_when_configured(make_client):
    with make_client(API_KEY="s3cret") as c:
        assert c.get("/health").status_code == 200  # health stays open
        r = c.get("/api/tasks")
        assert r.status_code == 401 and r.json()["error"] == "unauthorized"
        assert c.post("/api/chat", json={"message": "list my tasks"}).status_code == 401
        assert c.get("/api/tasks", headers={"X-API-Key": "wrong"}).status_code == 401
        assert c.get("/api/tasks", headers={"X-API-Key": "s3cret"}).status_code == 200


def test_cors_allows_configured_origin_only(client):
    ok = client.options("/api/chat", headers={"Origin": "http://localhost:5173", "Access-Control-Request-Method": "POST",
                                              "Access-Control-Request-Headers": "content-type"})
    assert ok.status_code == 200 and ok.headers["access-control-allow-origin"] == "http://localhost:5173"
    bad = client.options("/api/chat", headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in bad.headers


def test_mcp_down_gives_503_without_internals(make_client):
    with make_client(MCP_SERVER_URL="http://127.0.0.1:9/mcp") as c:
        r = c.post("/api/chat", json={"message": "list my tasks"})
    assert r.status_code == 503 and r.json()["error"] == "tool_server_unavailable"
    assert "Traceback" not in r.text and "127.0.0.1" not in r.text


def test_bedrock_failure_maps_to_http_error(client):
    class Failing:
        mock = False

        async def converse(self, **_):
            raise BedrockError("Access to the configured Bedrock model was denied.", status_code=502, code="model_access_denied")

    client.app.state.agent.model = Failing()
    r = client.post("/api/chat", json={"message": "hello there"})
    assert r.status_code == 502 and r.json()["error"] == "model_access_denied"


def test_unhandled_exceptions_never_leak_details(client):
    async def boom(_):
        raise RuntimeError("super-secret-detail AKIAABCDEFGHIJKLMNOP")

    client.app.state.agent.handle_message = boom
    r = client.post("/api/chat", json={"message": "hi"})
    assert r.status_code == 500 and r.json()["error"] == "internal_error"
    assert "secret" not in r.text and "AKIA" not in r.text and "Traceback" not in r.text
    assert r.headers.get("x-request-id") or r.json().get("request_id")


def test_unknown_route_and_request_id_header(client):
    r = client.get("/nope", headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 404 and r.json()["error"] == "http_error" and r.headers["x-request-id"] == "abc-123"
    assert client.get("/health", headers={"X-Request-ID": "bad id with spaces!"}).headers["x-request-id"] != "bad id with spaces!"
