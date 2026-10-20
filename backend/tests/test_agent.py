"""Bedrock orchestration tests with a scripted fake model and a fake MCP backend (no AWS, no network)."""
import asyncio
import copy
import dataclasses

import pytest
from botocore.exceptions import ClientError, NoCredentialsError

from app import database as db
from app.agent import Agent, classify_reply
from app.bedrock_client import BedrockClient, MockBedrockClient
from app.config import get_settings
from app.errors import AgentTimeoutError, BedrockError
from app.mcp_client import McpCallResult, McpCallTimeout, McpTool


# ------------------------------------------------------------------ helpers
def text_response(text, stop="end_turn"):
    return {"output": {"message": {"role": "assistant", "content": [{"text": text}]}}, "stopReason": stop, "usage": {}}


def tool_response(*uses):
    content = [{"toolUse": {"toolUseId": i, "name": n, "input": a}} for i, n, a in uses]
    return {"output": {"message": {"role": "assistant", "content": content}}, "stopReason": "tool_use", "usage": {}}


class ScriptedModel:
    mock = True

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def converse(self, *, system, messages, tools):
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        if callable(item):
            return await item()
        return item


TOOLS = [
    McpTool("add_task", "Add a task", {"type": "object", "properties": {"title": {"type": "string"}}, "required": ["title"]}),
    McpTool(
        "delete_task", "Delete a task",
        {"type": "object", "properties": {"task_id": {"type": "integer"}, "confirm": {"type": "boolean"}}, "required": ["task_id"]},
        destructive=True, requires_confirmation=True,
    ),
]


class FakeMcp:
    def __init__(self):
        self.calls = []
        self.fail_with = None
        self.timeout = False

    async def list_tools(self):
        return TOOLS

    async def call_tool(self, name, arguments):
        self.calls.append((name, dict(arguments)))
        if self.timeout:
            raise McpCallTimeout("slow")
        if self.fail_with:
            return McpCallResult(is_error=True, data={"error": self.fail_with})
        if name == "delete_task" and not arguments.get("confirm"):
            return McpCallResult(False, {"ok": True, "executed": False, "confirmation_required": True,
                                         "summary": f"Delete task #{arguments['task_id']} 'x'", "message": "Confirmation required"})
        if name == "delete_task":
            return McpCallResult(False, {"ok": True, "executed": True, "message": "Task deleted"})
        return McpCallResult(False, {"ok": True, "message": "Task created", "task": {"id": len(self.calls), **arguments}})


def make_agent(model, mcp=None, prefix="", **overrides):
    settings = dataclasses.replace(get_settings(), **overrides)
    return Agent(model=model, tools=mcp or FakeMcp(), settings=settings, response_prefix=prefix), settings


# ------------------------------------------------------------------ the tool-use loop
async def test_multiple_tool_calls_in_one_turn_are_answered_with_matching_ids():
    model = ScriptedModel(
        tool_response(("tu_1", "add_task", {"title": "milk"}), ("tu_2", "add_task", {"title": "eggs"})),
        text_response("Added both."),
    )
    mcp = FakeMcp()
    agent, _ = make_agent(model, mcp)
    result = await agent.handle_message("add milk and eggs")

    assert result.response == "Added both."
    assert [(e.tool, e.status, e.message) for e in result.events] == [("add_task", "success", "Task created")] * 2
    assert [c[1]["title"] for c in mcp.calls] == ["milk", "eggs"]  # executed in order

    # Converse contract: assistant toolUse message, then ONE user message with a toolResult per id.
    second_call = model.calls[1]["messages"]
    assert [m["role"] for m in second_call] == ["user", "assistant", "user"]
    blocks = second_call[2]["content"]
    assert [b["toolResult"]["toolUseId"] for b in blocks] == ["tu_1", "tu_2"]
    assert all(b["toolResult"]["status"] == "success" for b in blocks)


async def test_model_sees_translated_tool_specs_without_confirm():
    model = ScriptedModel(text_response("hi"))
    agent, _ = make_agent(model)
    await agent.handle_message("hello")
    specs = {t["toolSpec"]["name"]: t["toolSpec"] for t in model.calls[0]["tools"]}
    assert set(specs) == {"add_task", "delete_task"}
    assert "confirm" not in specs["delete_task"]["inputSchema"]["json"]["properties"]
    assert specs["add_task"]["inputSchema"]["json"]["required"] == ["title"]
    assert "UTC time" in model.calls[0]["system"] and "STORED ONLY" in model.calls[0]["system"]


async def test_multi_step_loop_until_final_answer():
    model = ScriptedModel(
        tool_response(("a", "add_task", {"title": "1"})),
        tool_response(("b", "add_task", {"title": "2"})),
        text_response("done"),
    )
    agent, _ = make_agent(model)
    result = await agent.handle_message("two steps")
    assert result.response == "done" and len(model.calls) == 3 and len(result.events) == 2


async def test_iteration_limit_stops_runaway_loops():
    model = ScriptedModel(*[tool_response((f"t{i}", "add_task", {"title": str(i)})) for i in range(10)])
    agent, _ = make_agent(model, agent_max_iterations=3)
    result = await agent.handle_message("loop forever")
    assert len(model.calls) == 3
    assert result.events[-1].tool == "agent" and result.events[-1].status == "error"
    assert "allowed number of steps" in result.response


async def test_tool_call_limit_still_returns_a_result_for_every_tool_use_id():
    model = ScriptedModel(
        tool_response(("x1", "add_task", {"title": "1"}), ("x2", "add_task", {"title": "2"})),
        text_response("partial"),
    )
    mcp = FakeMcp()
    agent, _ = make_agent(model, mcp, agent_max_tool_calls=1)
    result = await agent.handle_message("two tools")
    blocks = model.calls[1]["messages"][2]["content"]
    assert [b["toolResult"]["toolUseId"] for b in blocks] == ["x1", "x2"]
    assert blocks[1]["toolResult"]["status"] == "error"
    assert len(mcp.calls) == 1 and result.events[1].status == "error"


async def test_unknown_tool_and_bad_input_are_rejected_without_calling_mcp():
    model = ScriptedModel(
        tool_response(("u1", "run_shell", {"cmd": "rm -rf /"}), ("u2", "add_task", "not-a-dict")),
        text_response("sorry"),
    )
    mcp = FakeMcp()
    agent, _ = make_agent(model, mcp)
    result = await agent.handle_message("hack")
    assert mcp.calls == []
    assert [e.status for e in result.events] == ["error", "error"]
    blocks = model.calls[1]["messages"][2]["content"]
    assert all(b["toolResult"]["status"] == "error" for b in blocks)


async def test_tool_error_is_reported_and_loop_continues():
    mcp = FakeMcp()
    mcp.fail_with = "Task 9 not found."
    model = ScriptedModel(tool_response(("e1", "add_task", {"title": "x"})), text_response("That failed."))
    agent, _ = make_agent(model, mcp)
    result = await agent.handle_message("go")
    assert result.response == "That failed."
    assert (result.events[0].status, result.events[0].message) == ("error", "Task 9 not found.")
    assert model.calls[1]["messages"][2]["content"][0]["toolResult"]["status"] == "error"


async def test_tool_timeout_becomes_error_event():
    mcp = FakeMcp()
    mcp.timeout = True
    model = ScriptedModel(tool_response(("t1", "add_task", {"title": "x"})), text_response("timed out"))
    agent, _ = make_agent(model, mcp)
    result = await agent.handle_message("go")
    assert result.events[0].status == "error" and "timed out" in result.events[0].message


async def test_final_text_edge_cases():
    agent, _ = make_agent(ScriptedModel(text_response("cut", stop="max_tokens")))
    assert "cut short" in (await agent.handle_message("a")).response
    agent, _ = make_agent(ScriptedModel(text_response("x", stop="guardrail_intervened")))
    assert (await agent.handle_message("a")).response == "I can't help with that request."
    agent, _ = make_agent(ScriptedModel(text_response("")))
    assert "wasn't able" in (await agent.handle_message("a")).response


async def test_reasoning_blocks_are_never_returned():
    msg = {"output": {"message": {"role": "assistant", "content": [
        {"reasoningContent": {"reasoningText": {"text": "SECRET CHAIN OF THOUGHT"}}}, {"text": "Final."}]}},
        "stopReason": "end_turn"}
    agent, _ = make_agent(ScriptedModel(msg))
    assert (await agent.handle_message("a")).response == "Final."


async def test_model_errors_and_timeouts_propagate_as_api_errors():
    agent, _ = make_agent(ScriptedModel(BedrockError("nope", status_code=502, code="model_error")))
    with pytest.raises(BedrockError):
        await agent.handle_message("a")

    async def slow():
        await asyncio.sleep(5)

    agent, _ = make_agent(ScriptedModel(slow), agent_timeout_seconds=0.2)
    with pytest.raises(AgentTimeoutError):
        await agent.handle_message("a")


async def test_response_prefix_label():
    agent, _ = make_agent(ScriptedModel(text_response("hello")), prefix="[DEMO MODE] ")
    assert (await agent.handle_message("a")).response == "[DEMO MODE] hello"


# ------------------------------------------------------------------ confirmation safeguards
async def test_model_cannot_confirm_for_itself_and_user_confirmation_executes():
    mcp = FakeMcp()
    model = ScriptedModel(
        tool_response(("d1", "delete_task", {"task_id": 7, "confirm": True})),  # model tries to self-confirm
        text_response("Please confirm deleting task 7."),
    )
    agent, _ = make_agent(model, mcp)
    first = await agent.handle_message("delete task 7")
    assert mcp.calls == [("delete_task", {"task_id": 7})]  # `confirm` stripped
    assert first.events[0].status == "confirmation_required"
    assert [a["tool"] for a in db.get_active_pending_actions()] == ["delete_task"]

    second = await agent.handle_message("Yes, confirm!")
    assert mcp.calls[1] == ("delete_task", {"task_id": 7, "confirm": True})
    assert len(model.calls) == 2  # the model was NOT consulted for the confirmation
    assert second.events[0].status == "success" and "Task deleted" in second.response
    assert db.get_active_pending_actions() == []


async def test_cancel_discards_pending_action():
    mcp = FakeMcp()
    agent, _ = make_agent(ScriptedModel(tool_response(("d1", "delete_task", {"task_id": 1})), text_response("ok?")), mcp)
    await agent.handle_message("delete task 1")
    result = await agent.handle_message("cancel")
    assert "Nothing was changed" in result.response
    assert len(mcp.calls) == 1  # only the unconfirmed probe, never a confirmed call
    assert (await agent.handle_message("confirm")).response == "There is nothing waiting for confirmation."


async def test_new_request_supersedes_pending_confirmation():
    mcp = FakeMcp()
    agent, _ = make_agent(
        ScriptedModel(tool_response(("d1", "delete_task", {"task_id": 1})), text_response("confirm?"), text_response("hi")), mcp
    )
    await agent.handle_message("delete task 1")
    await agent.handle_message("what's up")
    assert (await agent.handle_message("confirm")).response == "There is nothing waiting for confirmation."
    assert all("confirm" not in args for _, args in mcp.calls)


async def test_expired_confirmation_is_not_executed():
    db.create_pending_action("delete_task", {"task_id": 1}, "Delete task #1", -1)
    mcp = FakeMcp()
    agent, _ = make_agent(ScriptedModel(), mcp)
    assert (await agent.handle_message("confirm")).response == "There is nothing waiting for confirmation."
    assert mcp.calls == []


@pytest.mark.parametrize("text,expected", [
    ("confirm", "confirm"), ("Yes, confirm!", "confirm"), ("  GO AHEAD ", "confirm"), ("cancel", "cancel"),
    ("No.", "cancel"), ("yes delete everything and also add a task", None), ("confirm the budget report", None),
])
def test_classify_reply_only_matches_bare_replies(text, expected):
    assert classify_reply(text) == expected


# ------------------------------------------------------------------ Bedrock client (stubbed boto3 client)
class StubBoto:
    def __init__(self, response=None, error=None):
        self.response, self.error, self.params = response, error, None

    def converse(self, **params):
        self.params = params
        if self.error:
            raise self.error
        return self.response


def bedrock(stub):
    return BedrockClient(dataclasses.replace(get_settings(), mock_mode=False, bedrock_model_id="test-model-id"), client=stub)


async def test_bedrock_client_builds_converse_request():
    stub = StubBoto(response=text_response("ok"))
    tools = [{"toolSpec": {"name": "add_task", "description": "d", "inputSchema": {"json": {"type": "object"}}}}]
    out = await bedrock(stub).converse(system="sys", messages=[{"role": "user", "content": [{"text": "hi"}]}], tools=tools)
    assert out["stopReason"] == "end_turn"
    p = stub.params
    assert p["modelId"] == "test-model-id" and p["system"] == [{"text": "sys"}] and p["toolConfig"] == {"tools": tools}
    assert set(p["inferenceConfig"]) == {"maxTokens", "temperature"}


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": "arn:aws:... internal detail"}}, "Converse")


@pytest.mark.parametrize("error,status,code", [
    (client_error("AccessDeniedException"), 502, "model_access_denied"),
    (client_error("ThrottlingException"), 503, "model_throttled"),
    (client_error("ValidationException"), 502, "model_request_invalid"),
    (client_error("ResourceNotFoundException"), 502, "model_not_found"),
    (client_error("SomethingNew"), 502, "model_error"),
    (NoCredentialsError(), 503, "aws_credentials_missing"),
    (TimeoutError(), 504, "model_timeout"),
])
async def test_bedrock_errors_are_translated_and_sanitised(error, status, code):
    with pytest.raises(BedrockError) as exc:
        await bedrock(StubBoto(error=error)).converse(system="s", messages=[], tools=[])
    assert (exc.value.status_code, exc.value.code) == (status, code)
    assert "arn:aws" not in exc.value.message


async def test_mock_model_follows_the_same_converse_contract():
    model = MockBedrockClient()
    tools = [{"toolSpec": {"name": "add_task"}}, {"toolSpec": {"name": "list_tasks"}}]
    first = await model.converse(system="", messages=[{"role": "user", "content": [{"text": "add a task to buy milk"}]}], tools=tools)
    assert first["stopReason"] == "tool_use"
    use = first["output"]["message"]["content"][0]["toolUse"]
    assert use["name"] == "add_task" and use["input"] == {"title": "buy milk"} and use["toolUseId"].startswith("mock_")
    msgs = [
        {"role": "user", "content": [{"text": "x"}]}, first["output"]["message"],
        {"role": "user", "content": [{"toolResult": {"toolUseId": use["toolUseId"], "status": "success",
                                                      "content": [{"text": '{"message":"Task created","task":{"id":1,"title":"buy milk"}}'}]}}]},
    ]
    final = await model.converse(system="", messages=msgs, tools=tools)
    assert final["stopReason"] == "end_turn" and "Task created: #1 buy milk" in final["output"]["message"]["content"][0]["text"]
