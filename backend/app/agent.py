"""The agent: Amazon Bedrock Converse tool-use loop over MCP tools, with confirmation safeguards.

Flow per /api/chat request
  1. Discover tools from the MCP server and translate their schemas to Bedrock `toolSpec`s.
  2. Call Converse. While the model stops with `tool_use`: run every requested tool through MCP
     (sequentially, in order) and return ALL results in ONE user message keyed by `toolUseId`.
  3. Stop at the first normal answer, or at the iteration / tool-call / time limits.
Only concise operational events are returned; model reasoning is never exposed.

Confirmation: if an MCP tool answers `confirmation_required` (delete_task, update_inventory
remove/set) nothing has been executed. The backend stores a pending action. The next user message
"confirm" executes it deterministically (the model is not involved and the `confirm` argument is
only ever set here); "cancel" discards it. Any other message supersedes pending actions.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from app import database as db
from app.bedrock_client import ModelClient
from app.config import Settings
from app.errors import AgentTimeoutError
from app.mcp_client import HIDDEN_ARGUMENTS, McpCallResult, McpCallTimeout, McpTool, to_bedrock_tool_spec
from app.schemas import ToolEvent

logger = logging.getLogger(__name__)

MAX_ARGS_CHARS = 5_000
MAX_RESULT_CHARS = 8_000
TOOL_CACHE_SECONDS = 30

CONFIRM_PHRASES = {
    "confirm", "confirmed", "yes", "y", "yes confirm", "yes please", "yes do it", "yes go ahead",
    "go ahead", "proceed", "do it", "ok confirm", "okay confirm",
}
CANCEL_PHRASES = {"cancel", "no", "n", "nope", "abort", "stop", "never mind", "nevermind", "no cancel", "no thanks", "dont", "don t"}


class ToolBackend(Protocol):
    async def list_tools(self) -> list[McpTool]: ...
    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpCallResult: ...


@dataclass
class ChatResult:
    response: str
    events: list[ToolEvent] = field(default_factory=list)


def classify_reply(message: str) -> str | None:
    """Return 'confirm' / 'cancel' if the whole message is a bare confirmation reply, else None."""
    normalised = re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", message.lower())).strip()
    if normalised in CONFIRM_PHRASES:
        return "confirm"
    if normalised in CANCEL_PHRASES:
        return "cancel"
    return None


def build_system_prompt(now: datetime) -> str:
    return (
        "You are the assistant behind a home-assistant app. You manage tasks, reminders and a household "
        "inventory using the provided tools.\n"
        f"Current UTC time: {now.isoformat(timespec='seconds')}.\n"
        "Rules:\n"
        "- Use tools for anything about tasks, reminders or inventory. Never invent data.\n"
        "- You may call several tools in one turn when the request needs it.\n"
        "- Reminders are STORED ONLY. No notification is ever sent. Never claim that the user will be notified.\n"
        "- For create_reminder, give remind_at as ISO 8601 with a timezone offset (use UTC unless told otherwise).\n"
        "- Destructive or consequential actions (deleting a task, removing or overwriting stock) are not executed "
        "until the user confirms. If a tool result says confirmation is required, tell the user exactly what is "
        "pending and ask them to reply 'confirm' or 'cancel'. Do not call that tool again.\n"
        "- Keep replies short and plain. Do not describe your reasoning.\n"
        "- You cannot run code, shell commands, SQL or browse the web; decline such requests politely."
    )


def _truncate(text: str, limit: int) -> str:
    return text if len(text) <= limit else text[: limit - 20] + '..."truncated"}'


def _tool_result(tool_use_id: str, payload: dict[str, Any], *, error: bool = False) -> dict[str, Any]:
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "status": "error" if error else "success",
            "content": [{"text": _truncate(json.dumps(payload, default=str), MAX_RESULT_CHARS)}],
        }
    }


class Agent:
    def __init__(self, *, model: ModelClient, tools: ToolBackend, settings: Settings, response_prefix: str = ""):
        self.model = model
        self.tools = tools
        self.settings = settings
        self.prefix = response_prefix
        self._tool_cache: tuple[float, list[McpTool]] | None = None

    # ------------------------------------------------------------------ public API
    async def handle_message(self, message: str) -> ChatResult:
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.settings.agent_timeout_seconds):
                result = await self._handle(message)
        except TimeoutError:
            logger.warning("agent timeout after %ss", self.settings.agent_timeout_seconds)
            raise AgentTimeoutError("The request took too long to complete. Please try again.") from None
        result.response = f"{self.prefix}{result.response}"
        logger.info(
            "chat done duration_ms=%d events=%s",
            int((time.perf_counter() - started) * 1000),
            [f"{e.tool}:{e.status}" for e in result.events],
        )
        return result

    async def list_tools(self) -> list[McpTool]:
        now = time.monotonic()
        if self._tool_cache and now - self._tool_cache[0] < TOOL_CACHE_SECONDS:
            return self._tool_cache[1]
        tools = await self.tools.list_tools()
        self._tool_cache = (now, tools)
        return tools

    # ------------------------------------------------------------------ internals
    async def _handle(self, message: str) -> ChatResult:
        intent = classify_reply(message)
        pending = await asyncio.to_thread(db.get_active_pending_actions)
        if intent and pending:
            return await self._resolve_pending(intent, pending)
        if intent:
            return ChatResult("There is nothing waiting for confirmation.")
        if pending:  # a new request supersedes anything still awaiting confirmation
            await asyncio.to_thread(db.cancel_pending_actions)
        return await self._run_model_loop(message)

    async def _resolve_pending(self, intent: str, pending: list[dict[str, Any]]) -> ChatResult:
        if intent == "cancel":
            for p in pending:
                await asyncio.to_thread(db.resolve_pending_action, p["id"], "cancelled")
            return ChatResult("Cancelled. Nothing was changed.")

        events: list[ToolEvent] = []
        lines: list[str] = []
        for p in pending:
            args = {**p["arguments"], "confirm": True}  # the only place `confirm` is ever set
            try:
                result = await self.tools.call_tool(p["tool"], args)
            except McpCallTimeout:
                await asyncio.to_thread(db.resolve_pending_action, p["id"], "failed")
                events.append(ToolEvent(tool=p["tool"], status="error", message="Tool call timed out"))
                lines.append(f"{p['summary']}: timed out, nothing was confirmed as done.")
                continue
            if result.is_error:
                msg = str(result.data.get("error", "Tool failed."))
                await asyncio.to_thread(db.resolve_pending_action, p["id"], "failed")
                events.append(ToolEvent(tool=p["tool"], status="error", message=msg))
                lines.append(f"{p['summary']}: failed - {msg}")
                continue
            await asyncio.to_thread(db.resolve_pending_action, p["id"], "executed")
            msg = str(result.data.get("message", "Done"))[:300]
            events.append(ToolEvent(tool=p["tool"], status="success", message=msg))
            lines.append(f"{p['summary']}: {msg}")
        return ChatResult("\n".join(lines), events)

    async def _run_model_loop(self, message: str) -> ChatResult:
        tools = await self.list_tools()
        tools_by_name = {t.name: t for t in tools}
        specs = [to_bedrock_tool_spec(t) for t in tools]
        system = build_system_prompt(datetime.now(timezone.utc))
        messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": message}]}]
        events: list[ToolEvent] = []
        tool_calls = 0

        for step in range(1, self.settings.agent_max_iterations + 1):
            response = await self.model.converse(system=system, messages=messages, tools=specs)
            assistant = response["output"]["message"]
            messages.append(assistant)
            stop_reason = response.get("stopReason")
            tool_uses = [b["toolUse"] for b in assistant.get("content", []) if "toolUse" in b]

            if stop_reason == "tool_use" and tool_uses:
                result_blocks: list[dict[str, Any]] = []
                for tool_use in tool_uses:  # every toolUse id must get exactly one toolResult
                    if tool_calls >= self.settings.agent_max_tool_calls:
                        result_blocks.append(
                            _tool_result(
                                str(tool_use.get("toolUseId", "")),
                                {"error": "Tool call limit reached for this request."},
                                error=True,
                            )
                        )
                        events.append(
                            ToolEvent(tool=str(tool_use.get("name", "unknown"))[:64], status="error", message="Skipped: tool call limit reached")
                        )
                        continue
                    tool_calls += 1
                    result_blocks.append(await self._execute_tool_use(tool_use, tools_by_name, events))
                messages.append({"role": "user", "content": result_blocks})
                continue

            return ChatResult(self._final_text(assistant, stop_reason), events)

        logger.warning("agent hit iteration limit (%d)", self.settings.agent_max_iterations)
        events.append(
            ToolEvent(tool="agent", status="error", message=f"Stopped after {self.settings.agent_max_iterations} steps (iteration limit)")
        )
        return ChatResult(
            "I couldn't finish this request within the allowed number of steps. "
            "Check the activity list for what was completed, then try a simpler request.",
            events,
        )

    @staticmethod
    def _final_text(assistant: dict[str, Any], stop_reason: str | None) -> str:
        if stop_reason in ("guardrail_intervened", "content_filtered"):
            return "I can't help with that request."
        text = "\n".join(b["text"] for b in assistant.get("content", []) if "text" in b).strip()
        if not text:
            return "I wasn't able to produce a response. Please try rephrasing."
        if stop_reason == "max_tokens":
            text += "\n(The response was cut short.)"
        return text

    async def _execute_tool_use(
        self, tool_use: dict[str, Any], tools_by_name: dict[str, McpTool], events: list[ToolEvent]
    ) -> dict[str, Any]:
        tool_use_id = str(tool_use.get("toolUseId", ""))
        name = str(tool_use.get("name", ""))
        label = name[:64] or "unknown"

        def fail(message: str) -> dict[str, Any]:
            events.append(ToolEvent(tool=label, status="error", message=message[:300]))
            return _tool_result(tool_use_id, {"error": message}, error=True)

        if name not in tools_by_name:
            return fail("Unknown tool requested.")
        raw = tool_use.get("input")
        if not isinstance(raw, dict):
            return fail("Tool input must be a JSON object.")
        args = {k: v for k, v in raw.items() if k not in HIDDEN_ARGUMENTS}  # model may never set `confirm`
        if len(json.dumps(args, default=str)) > MAX_ARGS_CHARS:
            return fail("Tool input is too large.")

        try:
            result = await self.tools.call_tool(name, args)
        except McpCallTimeout:
            return fail("Tool call timed out.")
        if result.is_error:
            return fail(str(result.data.get("error", "Tool failed.")))

        data = result.data
        if data.get("confirmation_required") is True:
            summary = str(data.get("summary") or f"Run {name}")[:300]
            await asyncio.to_thread(db.create_pending_action, name, args, summary, self.settings.confirmation_ttl_seconds)
            events.append(ToolEvent(tool=name, status="confirmation_required", message=f"{summary} - awaiting confirmation"))
            return _tool_result(
                tool_use_id,
                {
                    "executed": False,
                    "confirmation_required": True,
                    "summary": summary,
                    "instruction": "NOT executed. Tell the user exactly what is pending and ask them to reply "
                    "'confirm' to proceed or 'cancel' to abort. Do not call this tool again.",
                },
            )
        events.append(ToolEvent(tool=name, status="success", message=str(data.get("message") or "Completed")[:300]))
        return _tool_result(tool_use_id, data)
