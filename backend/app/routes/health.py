from __future__ import annotations

import asyncio

import httpx
from fastapi import APIRouter, Request

from app import __version__
from app.database import check_database
from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Liveness and dependency check")
async def health(request: Request) -> HealthResponse:
    settings = request.app.state.settings
    db_ok = await asyncio.to_thread(check_database)
    mcp_ok = False
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            mcp_ok = (await client.get(f"{settings.mcp_base_url}/healthz")).status_code == 200
    except httpx.HTTPError:
        mcp_ok = False
    return HealthResponse(
        status="ok" if db_ok and mcp_ok else "degraded",
        mode="mock" if settings.mock_mode else "bedrock",
        database="ok" if db_ok else "error",
        mcp_server="ok" if mcp_ok else "unreachable",
        version=__version__,
    )
