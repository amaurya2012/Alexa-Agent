"""FastAPI application. Run from backend/:  uvicorn app.main:app --port 8000"""
from __future__ import annotations

import json
import logging
import re
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from ask_sdk_core.skill_builder import SkillBuilder
from app.alexa_handler import AlexaAgentIntentHandler

from app import __version__
from app.agent import Agent
from app.bedrock_client import build_model_client
from app.config import get_settings
from app.database import init_db
from app.errors import ApiError
from app.logging_config import request_id_var, setup_logging
from app.mcp_client import McpToolClient
from app.routes import chat, health, tools
from app.schemas import ErrorDetail, ErrorResponse

logger = logging.getLogger("app")

DEMO_PREFIX = "[DEMO MODE - mock model, no AWS call] "
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    settings.validate()
    setup_logging(settings.log_level)
    init_db()
    model = build_model_client(settings)
    app.state.settings = settings
    app.state.agent = Agent(
        model=model,
        tools=McpToolClient(settings),
        settings=settings,
        response_prefix=DEMO_PREFIX if settings.mock_mode else "",
    )
    if "*" in settings.cors_origins:
        logger.warning("CORS_ORIGINS contains '*' - restrict it before deploying")
    logger.info("Backend started mode=%s mcp=%s", "mock" if settings.mock_mode else "bedrock", settings.mcp_server_url)
    yield


def _error_response(status: int, code: str, message: str, request: Request, details=None) -> JSONResponse:
    body = ErrorResponse(
        error=code, message=message, details=details, request_id=getattr(request.state, "request_id", None)
    )
    return JSONResponse(status_code=status, content=body.model_dump(exclude_none=True))


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(
        title="Next-Gen Alexa+ Agent API",
        version=__version__,
        description="Chat endpoint backed by Amazon Bedrock (or a labelled mock model) that calls tools over MCP.",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.cors_origins),
        allow_credentials=False,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        incoming = request.headers.get("x-request-id", "")
        rid = incoming if _REQUEST_ID_RE.match(incoming) else uuid.uuid4().hex[:12]
        request.state.request_id = rid
        token = request_id_var.set(rid)
        started = time.perf_counter()
        try:
            response = await call_next(request)
            response.headers["X-Request-ID"] = rid
            logger.info(
                "%s %s -> %d (%dms)",
                request.method, request.url.path, response.status_code, int((time.perf_counter() - started) * 1000),
            )
            return response
        finally:
            request_id_var.reset(token)

    # --- ALEXA WEBHOOK ENDPOINT ---
    @app.post("/api/alexa")
    async def alexa_endpoint(request: Request):
        agent = request.app.state.agent
        
        sb = SkillBuilder()
        sb.add_request_handler(AlexaAgentIntentHandler(agent))
        skill = sb.create()

        payload = await request.body()
        data = json.loads(payload.decode("utf-8"))
        
        response_payload = skill.invoke(data, None)
        return Response(content=json.dumps(response_payload), media_type="application/json")

    @app.exception_handler(ApiError)
    async def api_error_handler(request: Request, exc: ApiError):
        return _error_response(exc.status_code, exc.code, exc.message, request)

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        details = [
            ErrorDetail(field=".".join(str(p) for p in e["loc"]), message=str(e["msg"])) for e in exc.errors()
        ]
        return _error_response(422, "validation_error", "The request is invalid.", request, details)

    @app.exception_handler(StarletteHTTPException)
    async def http_handler(request: Request, exc: StarletteHTTPException):
        return _error_response(exc.status_code, "http_error", str(exc.detail), request)

    @app.exception_handler(Exception)
    async def unhandled_handler(request: Request, exc: Exception):
        logger.exception("Unhandled error on %s %s", request.method, request.url.path)
        return _error_response(500, "internal_error", "An unexpected error occurred.", request)

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(tools.router)
    return app


app = create_app()