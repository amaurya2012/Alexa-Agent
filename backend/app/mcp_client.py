"""MCP client: tool discovery + execution over Streamable HTTP, and schema translation for Bedrock.

Each operation opens a short-lived MCP session. The server is stateless, so this is simple and
robust, and keeps AnyIO task-group exception groups away from the agent loop.
"""
from __future__ import annotations

import asyncio
import copy
import json
import logging
import re
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

import httpx2  # installed together with the official `mcp` SDK (2.x)
from mcp.client import Client
from mcp.client.streamable_http import streamable_http_client

from app.config import Settings
from app.errors import McpUnavailableError

logger = logging.getLogger(__name__)

# Arguments that only the backend may set (never exposed to the model, always stripped from its input).
HIDDEN_ARGUMENTS = frozenset({"confirm"})


class McpCallTimeout(Exception):
    """A single tool call exceeded TOOL_TIMEOUT_SECONDS."""


@dataclass(frozen=True)
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool = False
    destructive: bool = False
    requires_confirmation: bool = False


@dataclass
class McpCallResult:
    is_error: bool
    data: dict[str, Any] = field(default_factory=dict)
    text: str = ""


# --------------------------------------------------------------------------- schema translation
def _clean_schema(node: Any) -> Any:
    """Drop JSON-Schema 'title' annotations and collapse Optional[X] (anyOf with null) to X."""
    if isinstance(node, list):
        return [_clean_schema(n) for n in node]
    if not isinstance(node, dict):
        return node
    out: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue  # annotation only (a *property* called "title" lives under "properties")
        if key in ("properties", "$defs", "definitions") and isinstance(value, dict):
            out[key] = {name: _clean_schema(sub) for name, sub in value.items()}
        else:
            out[key] = _clean_schema(value)
    variants = out.get("anyOf")
    if isinstance(variants, list):
        non_null = [v for v in variants if not (isinstance(v, dict) and v.get("type") == "null")]
        if len(non_null) == 1 and len(non_null) < len(variants) and isinstance(non_null[0], dict):
            merged = {k: v for k, v in out.items() if k != "anyOf"}
            merged.update(non_null[0])
            return merged
    return out


def public_input_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """The schema shown to the model / frontend: cleaned, with backend-only arguments removed."""
    cleaned = _clean_schema(copy.deepcopy(schema or {}))
    cleaned["type"] = "object"
    props = cleaned.get("properties")
    cleaned["properties"] = {k: v for k, v in (props or {}).items() if k not in HIDDEN_ARGUMENTS}
    required = [r for r in cleaned.get("required", []) if r not in HIDDEN_ARGUMENTS]
    if required:
        cleaned["required"] = required
    else:
        cleaned.pop("required", None)
    return cleaned


def to_bedrock_tool_spec(tool: McpTool) -> dict[str, Any]:
    """Translate an MCP tool into a Bedrock Converse `toolSpec`."""
    return {
        "toolSpec": {
            "name": tool.name,
            "description": (tool.description or tool.name)[:1000],
            "inputSchema": {"json": public_input_schema(tool.input_schema)},
        }
    }


# --------------------------------------------------------------------------- helpers
def _flatten(exc: BaseException) -> list[BaseException]:
    if isinstance(exc, BaseExceptionGroup):
        out: list[BaseException] = []
        for inner in exc.exceptions:
            out.extend(_flatten(inner))
        return out
    return [exc]


def _is_timeout(exc: BaseException) -> bool:
    return any(isinstance(e, TimeoutError) for e in _flatten(exc))


def clean_error_text(text: str, limit: int = 300) -> str:
    """Make an MCP/Pydantic error message short and free of tool-framework noise."""
    text = re.sub(r"^Error executing tool [\w-]+:\s*", "", text.strip())
    text = re.sub(r"\s*For further information visit \S+", "", text)
    text = re.sub(r"\s*\[type=[^\]]*\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:limit] or "Tool failed."


# --------------------------------------------------------------------------- client
class McpToolClient:
    def __init__(self, settings: Settings):
        self.url = settings.mcp_server_url
        self.token = settings.mcp_auth_token
        self.tool_timeout = settings.tool_timeout_seconds

    @asynccontextmanager
    async def _session(self) -> AsyncIterator[Client]:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        timeout = httpx2.Timeout(self.tool_timeout, connect=min(5.0, self.tool_timeout))
        async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http:
            async with Client(streamable_http_client(self.url, http_client=http)) as client:
                yield client

    async def list_tools(self) -> list[McpTool]:
        try:
            async with asyncio.timeout(self.tool_timeout + 2):
                async with self._session() as client:
                    result = await client.list_tools()
        except Exception as exc:
            logger.warning("MCP list_tools failed: %s", [type(e).__name__ for e in _flatten(exc)])
            raise McpUnavailableError("The tool server is not reachable. Is the MCP server running?") from None
        tools = []
        for t in result.tools:
            ann = t.annotations
            destructive = bool(ann and ann.destructive_hint)
            tools.append(
                McpTool(
                    name=t.name,
                    description=t.description or "",
                    input_schema=dict(t.input_schema or {}),
                    read_only=bool(ann and ann.read_only_hint),
                    destructive=destructive,
                    # Any tool that exposes the hidden `confirm` argument can ask for confirmation.
                    requires_confirmation="confirm" in (t.input_schema or {}).get("properties", {}),
                )
            )
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> McpCallResult:
        try:
            async with asyncio.timeout(self.tool_timeout + 2):
                async with self._session() as client:
                    result = await client.call_tool(name, arguments, read_timeout_seconds=self.tool_timeout)
        except Exception as exc:
            if _is_timeout(exc):
                raise McpCallTimeout(f"Tool '{name}' timed out.") from None
            logger.warning("MCP call_tool(%s) failed: %s", name, [type(e).__name__ for e in _flatten(exc)])
            raise McpUnavailableError("The tool server is not reachable. Is the MCP server running?") from None

        text = "\n".join(c.text for c in result.content if getattr(c, "type", None) == "text").strip()
        if result.is_error:
            return McpCallResult(is_error=True, data={"error": clean_error_text(text)}, text=text)
        try:
            parsed = json.loads(text)
            data = parsed if isinstance(parsed, dict) else {"result": parsed}
        except json.JSONDecodeError:
            data = {"message": text}
        return McpCallResult(is_error=False, data=data, text=text)
