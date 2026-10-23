"""Amazon Bedrock Converse client, plus a clearly-labelled MOCK model for demo mode.

Both expose the same async interface:
    await client.converse(system=str, messages=list, tools=list) -> Converse-shaped dict
so the agent loop is identical in demo mode and with real Bedrock.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

from app.config import Settings
from app.errors import BedrockError

logger = logging.getLogger(__name__)


class ModelClient(Protocol):
    mock: bool

    async def converse(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]: ...


# --------------------------------------------------------------------------- real Bedrock
_ERROR_MAP: dict[str, tuple[int, str, str]] = {
    "ThrottlingException": (503, "model_throttled", "The model is busy right now. Please try again shortly."),
    "ServiceQuotaExceededException": (503, "model_throttled", "Model quota exceeded. Please try again later."),
    "AccessDeniedException": (
        502, "model_access_denied",
        "Access to the configured Bedrock model was denied. Check IAM permissions and model access.",
    ),
    "ResourceNotFoundException": (
        502, "model_not_found", "The configured Bedrock model was not found in this region. Check BEDROCK_MODEL_ID.",
    ),
    "ValidationException": (
        502, "model_request_invalid",
        "Bedrock rejected the request. Check BEDROCK_MODEL_ID and that the model supports tool use.",
    ),
    "ModelTimeoutException": (504, "model_timeout", "The model took too long to respond."),
    "ModelNotReadyException": (503, "model_not_ready", "The model is not ready yet. Please retry."),
    "ServiceUnavailableException": (503, "model_unavailable", "Bedrock is temporarily unavailable."),
    "InternalServerException": (502, "model_error", "Bedrock reported an internal error."),
    "ModelErrorException": (502, "model_error", "The model reported an error."),
}


class BedrockClient:
    mock = False

    def __init__(self, settings: Settings, client: Any | None = None):
        self.settings = settings
        self._client = client

    def _get_client(self) -> Any:
        if self._client is None:
            import boto3  # imported lazily so mock mode never needs AWS setup
            from botocore.config import Config

            session = boto3.Session(
                profile_name=self.settings.aws_profile or None, region_name=self.settings.aws_region
            )
            self._client = session.client(
                "bedrock-runtime",
                config=Config(
                    connect_timeout=self.settings.bedrock_connect_timeout,
                    read_timeout=self.settings.bedrock_read_timeout,
                    retries={"max_attempts": self.settings.bedrock_max_retries + 1, "mode": "standard"},
                ),
            )
        return self._client

    async def converse(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        params: dict[str, Any] = {
            "modelId": self.settings.bedrock_model_id,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {
                "maxTokens": self.settings.bedrock_max_tokens,
                "temperature": self.settings.bedrock_temperature,
            },
        }
        if tools:
            params["toolConfig"] = {"tools": tools}
        try:
            client = self._get_client()
            return await asyncio.to_thread(client.converse, **params)
        except BedrockError:
            raise
        except Exception as exc:  # noqa: BLE001 - translated into a safe error below
            raise self._translate(exc) from None

    @staticmethod
    def _translate(exc: Exception) -> BedrockError:
        from botocore.exceptions import (
            BotoCoreError, ClientError, ConnectTimeoutError, EndpointConnectionError,
            NoCredentialsError, NoRegionError, PartialCredentialsError, ProfileNotFound, ReadTimeoutError,
        )

        if isinstance(exc, ClientError):
            code = exc.response.get("Error", {}).get("Code", "")
            status, error_code, message = _ERROR_MAP.get(
                code, (502, "model_error", "Bedrock returned an unexpected error.")
            )
            logger.warning("Bedrock ClientError code=%s", code)
            return BedrockError(message, status_code=status, code=error_code)
        if isinstance(exc, (NoCredentialsError, PartialCredentialsError, ProfileNotFound)):
            return BedrockError(
                "AWS credentials are not configured. Configure the AWS credential chain or set MOCK_MODE=true.",
                status_code=503, code="aws_credentials_missing",
            )
        if isinstance(exc, NoRegionError):
            return BedrockError("AWS_REGION is not configured.", status_code=503, code="aws_region_missing")
        if isinstance(exc, (ReadTimeoutError, ConnectTimeoutError, TimeoutError)):
            return BedrockError("The model request timed out.", status_code=504, code="model_timeout")
        if isinstance(exc, (EndpointConnectionError, BotoCoreError)):
            return BedrockError("Could not reach Amazon Bedrock.", status_code=503, code="model_unreachable")
        logger.exception("Unexpected error calling Bedrock")
        return BedrockError("Unexpected error while calling the model.")


# --------------------------------------------------------------------------- MOCK model (demo mode)
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds")


def _parse_when(when: str, now: datetime) -> datetime | None:
    """Parse the few time phrases the demo planner supports (UTC)."""
    when = when.lower().strip()
    if m := re.fullmatch(r"in\s+(\d+)\s*(minutes?|mins?|hours?|hrs?|days?)", when):
        n, unit = int(m.group(1)), m.group(2)
        if unit.startswith("m"):
            return now + timedelta(minutes=n)
        if unit.startswith("h"):
            return now + timedelta(hours=n)
        return now + timedelta(days=n)
    m = re.fullmatch(r"(?P<tomorrow>tomorrow)?\s*(?:at\s+)?(?:(?P<h>\d{1,2})(?::(?P<min>\d{2}))?\s*(?P<ap>am|pm)?)?", when)
    if not m or not (m.group("tomorrow") or m.group("h")):
        return None
    hour = int(m.group("h")) if m.group("h") else 9
    minute = int(m.group("min") or 0)
    if m.group("ap") == "pm" and hour < 12:
        hour += 12
    if m.group("ap") == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if m.group("tomorrow") or target <= now:
        target += timedelta(days=1)
    return target


_WHEN = r"in\s+\d+\s*(?:minutes?|mins?|hours?|hrs?|days?)|tomorrow(?:\s+at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?)?|at\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)"


def plan_tool_calls(text: str, now: datetime) -> tuple[list[tuple[str, dict[str, Any]]], str | None]:
    """Tiny rule-based planner standing in for the model in demo mode. Returns (calls, note)."""
    calls: list[tuple[str, dict[str, Any]]] = []
    notes: list[str] = []
    clauses = [c.strip(" .!?") for c in re.split(r"\s*;\s*|\s+and then\s+|\s+then\s+", text, flags=re.I) if c.strip(" .!?")]
    for clause in clauses:
        low = clause.lower()
        m = re.match(rf"^(?:please\s+)?remind me\s+(?:to\s+)?(?P<text>.+?)\s+(?P<when>{_WHEN})$", clause, re.I)
        if m:
            when = _parse_when(m.group("when"), now)
            if when:
                calls.append(("create_reminder", {"text": m.group("text").strip(), "remind_at": _iso(when)}))
                continue
        if low.startswith(("remind me", "please remind me")):
            notes.append("I couldn't work out when to remind you. Try: 'remind me to call mom in 2 hours' or 'remind me to submit the report tomorrow at 9am'.")
            continue
        if m := re.match(r"^(?:please\s+)?(?:delete|remove|cancel)\s+task\s+#?(\d+)$", clause, re.I):
            calls.append(("delete_task", {"task_id": int(m.group(1))}))
        elif m := re.match(r"^(?:please\s+)?(?:complete|finish|mark(?: off)?|done with)\s+task\s+#?(\d+)$", clause, re.I):
            calls.append(("complete_task", {"task_id": int(m.group(1))}))
        elif re.match(r"^(?:please\s+)?(?:list|show|what are|what's|get)\s+(?:me\s+)?(?:all\s+|my\s+|the\s+|completed\s+|pending\s+|open\s+)*(?:reminders)$", low):
            calls.append(("list_reminders", {}))
        elif re.match(r"^(?:please\s+)?(?:list|show|what are|what's on|get)\s+(?:me\s+)?(?:all\s+|my\s+|the\s+|completed\s+|pending\s+|open\s+)*(?:tasks?|to-?do(?:s| list)?)$", low):
            status = "completed" if "completed" in low else "all" if re.search(r"\ball\b", low) else "pending"
            calls.append(("list_tasks", {"status": status}))
        elif m := re.match(r"^(?:please\s+)?(?:add|create|new)\s+(?:a\s+|an\s+)?(?:new\s+)?task(?:\s+(?:to|called|named))?\s*:?\s*(?P<t>.+)$", clause, re.I):
            calls.append(("add_task", {"title": m.group("t").strip()}))
        elif m := re.match(r"^(?:please\s+)?add\s+(?P<t>.+?)\s+to\s+(?:my\s+)?(?:tasks?|to-?do(?:\s+list)?)$", clause, re.I):
            calls.append(("add_task", {"title": m.group("t").strip()}))
        elif m := re.match(r"^(?:please\s+)?(?:add|restock)\s+(\d+)\s+(?P<i>.+?)\s+(?:to|in)\s+(?:the\s+)?(?:inventory|stock)$", clause, re.I):
            calls.append(("update_inventory", {"item_name": m.group("i"), "operation": "add", "quantity": int(m.group(1))}))
        elif m := re.match(r"^(?:please\s+)?(?:remove|use|used|consume|consumed|took)\s+(\d+)\s+(?P<i>.+?)(?:\s+from\s+(?:the\s+)?(?:inventory|stock))?$", clause, re.I):
            calls.append(("update_inventory", {"item_name": m.group("i"), "operation": "remove", "quantity": int(m.group(1))}))
        elif m := re.match(r"^(?:please\s+)?set\s+(?P<i>.+?)\s+(?:stock|inventory|quantity)\s+to\s+(\d+)$", clause, re.I):
            calls.append(("update_inventory", {"item_name": m.group("i"), "operation": "set", "quantity": int(m.group(2))}))
        elif re.match(r"^(?:please\s+)?(?:show|list|what's|what is|get)\s+(?:me\s+)?(?:the\s+|my\s+|all\s+)*(?:inventory|stock)$", low):
            calls.append(("check_inventory", {}))
        elif m := re.match(r"^(?:please\s+)?(?:do we have|have we got|how many|how much|check(?:\s+the)?(?:\s+stock|\s+inventory)?(?:\s+of|\s+for)?|stock of|inventory of)\s+(?:any\s+)?(?P<i>.+)$", clause, re.I):
            item = re.sub(r"\s+(?:left|in stock|do we have(?: left)?)$", "", m.group("i").strip(), flags=re.I)
            calls.append(("check_inventory", {"item_name": item}))
        # Weather ke liye rule add karein
        elif re.match(
            r"^(?:please\s+)?(?:what's|what is|how's|how is|get|check|tell me)?(?:\s+the)?\s*weather(?:\s+(?:like|in|at|today))?.*$",
            low,
        ):
          calls.append(("get_weather", {"city": "Delhi NCR"}))
        else:
            notes.append(f"I didn't understand '{clause}'.")
    return calls, (" ".join(notes) or None)


_HELP = (
    "In demo mode I understand simple requests such as: 'add a task to buy milk', 'list my tasks', "
    "'complete task 1', 'delete task 2', 'remind me to call mom in 2 hours', 'show reminders', "
    "'do we have eggs', 'show inventory', 'add 6 eggs to inventory', 'remove 2 milk from inventory', 'what is the weather in Delhi?'."
)


class MockBedrockClient:
    """Deterministic stand-in for Bedrock. It emits real Converse-shaped toolUse/text blocks, so the
    agent loop, MCP calls and SQLite writes are exercised for real; only the language model is fake."""

    mock = True

    async def converse(self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> dict[str, Any]:
        last = messages[-1]
        results = [b["toolResult"] for b in last["content"] if "toolResult" in b]
        if results:
            return self._final(messages, results)
        text = " ".join(b["text"] for b in last["content"] if "text" in b)
        available = {t["toolSpec"]["name"] for t in tools}
        calls, note = plan_tool_calls(text, datetime.now(timezone.utc))
        calls = [(n, a) for n, a in calls if n in available]
        if not calls:
            return self._text(f"{note}\n{_HELP}" if note else _HELP)
        content = [
            {"toolUse": {"toolUseId": f"mock_{uuid.uuid4().hex[:16]}", "name": n, "input": a}} for n, a in calls
        ]
        if note:
            content.insert(0, {"text": note})
        return {
            "output": {"message": {"role": "assistant", "content": content}},
            "stopReason": "tool_use",
            "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
        }

    @staticmethod
    def _text(text: str) -> dict[str, Any]:
        return {
            "output": {"message": {"role": "assistant", "content": [{"text": text}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 0, "outputTokens": 0, "totalTokens": 0},
        }

    def _final(self, messages: list[dict[str, Any]], results: list[dict[str, Any]]) -> dict[str, Any]:
        names = {
            b["toolUse"]["toolUseId"]: b["toolUse"]["name"]
            for b in messages[-2]["content"] if "toolUse" in b
        }
        lead = " ".join(b["text"] for b in messages[-2]["content"] if "text" in b)
        lines = [lead] if lead else []
        for r in results:
            name = names.get(r["toolUseId"], "tool")
            raw = "".join(c.get("text", "") for c in r["content"])
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                data = {"message": raw}
            lines.append(self._describe(name, data, r.get("status") == "error"))
        return self._text("\n".join(lines))

    @staticmethod
    def _describe(name: str, data: dict[str, Any], failed: bool) -> str:
        if failed:
            return f"{name} failed: {data.get('error', 'unknown error')}"
        if data.get("confirmation_required"):
            return f"{data.get('summary', name)} - this needs your confirmation. Reply 'confirm' to proceed or 'cancel' to abort."
        if name == "list_tasks":
            tasks = data.get("tasks", [])
            if not tasks:
                return "You have no matching tasks."
            return "Tasks:\n" + "\n".join(
                f"- #{t['id']} {t['title']} ({t['status']}, {t['priority']}{', due ' + t['due_date'] if t.get('due_date') else ''})"
                for t in tasks
            )
        if name == "list_reminders":
            items = data.get("reminders", [])
            body = "You have no reminders." if not items else "Reminders:\n" + "\n".join(
                f"- #{r['id']} {r['text']} at {r['remind_at']}" for r in items
            )
            return f"{body}\nNote: {data.get('notice', 'Reminders are stored only; no notifications are sent.')}"
        if name == "check_inventory":
            items = data.get("items", [])
            if not items:
                return data.get("message", "No matching items.")
            return "Inventory:\n" + "\n".join(
                f"- {i['item_name']}: {i['quantity']} {i['unit']}{' (low stock)' if i.get('low_stock') else ''}" for i in items
            )
        if name == "add_task" and data.get("task"):
            return f"Task created: #{data['task']['id']} {data['task']['title']}"
        if name == "create_reminder":
            r = data.get("reminder", {})
            return f"Reminder #{r.get('id')} stored for {r.get('remind_at')}. Note: {data.get('notice', '')}"
        if name == "get_weather":
          return f"The current weather in {data.get('city', 'your area')} is {data.get('temp', '28°C')}, {data.get('condition', 'Clear Skies')} with {data.get('humidity', '42%')} humidity."
        return data.get("message", "Done.")


def build_model_client(settings: Settings) -> ModelClient:
    return MockBedrockClient() if settings.mock_mode else BedrockClient(settings)