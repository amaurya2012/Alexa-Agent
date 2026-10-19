"""FastAPI dependencies."""
from __future__ import annotations

import hmac

from fastapi import Header, Request

from app.agent import Agent
from app.errors import ApiError


def get_agent(request: Request) -> Agent:
    return request.app.state.agent


async def require_api_key(request: Request, x_api_key: str | None = Header(default=None)) -> None:
    """Optional shared-secret guard for /api/*. Disabled when API_KEY is empty."""
    expected = request.app.state.settings.api_key
    if expected and not (x_api_key and hmac.compare_digest(x_api_key.encode(), expected.encode())):
        raise ApiError("Missing or invalid API key.", status_code=401, code="unauthorized")
