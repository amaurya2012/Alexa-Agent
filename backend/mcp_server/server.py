"""MCP tool server (official Python MCP SDK, Streamable HTTP transport).

Run from the backend/ folder:   python -m mcp_server.server
Endpoint:                        http://127.0.0.1:8765/mcp   (override with MCP_HOST / MCP_PORT)

Security: binds to loopback by default; optional bearer token (MCP_AUTH_TOKEN) is enforced on every
request except /healthz. This server is an internal component and must not be exposed publicly.
"""
from __future__ import annotations

import hmac
import logging

import uvicorn
from mcp.server.mcpserver import MCPServer
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse

from app.config import get_settings
from app.database import init_db
from app.logging_config import setup_logging
from mcp_server.tools import inventory, reminders, tasks

logger = logging.getLogger("mcp_server")

SERVER_INSTRUCTIONS = (
    "Tools for a personal assistant: tasks, reminders and a household inventory. "
    "Reminders are stored only; no notifications are sent. delete_task and update_inventory "
    "(remove/set) return confirmation_required until the backend passes confirm=true."
)


class BearerTokenMiddleware:
    """Pure-ASGI shared-secret check (safe for streaming responses)."""

    def __init__(self, app, token: str, exempt_paths: tuple[str, ...] = ("/healthz",)):
        self.app = app
        self.expected = f"Bearer {token}".encode() if token else b""
        self.exempt_paths = exempt_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.expected or scope["path"] in self.exempt_paths:
            await self.app(scope, receive, send)
            return
        supplied = dict(scope["headers"]).get(b"authorization", b"")
        if not hmac.compare_digest(supplied, self.expected):
            response = JSONResponse(
                {"error": "unauthorized"}, status_code=401, headers={"WWW-Authenticate": "Bearer"}
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def build_mcp_server() -> MCPServer:
    mcp = MCPServer("alexa-plus-tools", instructions=SERVER_INSTRUCTIONS)
    tasks.register(mcp)
    reminders.register(mcp)
    inventory.register(mcp)

    @mcp.custom_route("/healthz", methods=["GET"])
    async def healthz(_: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    return mcp


def create_app() -> Starlette:
    """ASGI app serving MCP at /mcp (stateless Streamable HTTP, JSON responses)."""
    settings = get_settings()
    init_db()
    mcp = build_mcp_server()
    app = mcp.streamable_http_app(stateless_http=True, json_response=True, host=settings.mcp_host)
    app.add_middleware(BearerTokenMiddleware, token=settings.mcp_auth_token)
    return app


def main() -> None:
    settings = get_settings()
    settings.validate()
    setup_logging(settings.log_level)
    logger.info(
        "Starting MCP server on http://%s:%s/mcp (auth=%s, db=%s)",
        settings.mcp_host,
        settings.mcp_port,
        "token" if settings.mcp_auth_token else "none",
        settings.database_path.name,
    )
    uvicorn.run(create_app(), host=settings.mcp_host, port=settings.mcp_port, log_level="warning")


if __name__ == "__main__":
    main()
