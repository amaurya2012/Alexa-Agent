"""Shared helpers for MCP tool modules: independent input validation, safe errors, confirmation."""
from __future__ import annotations

import functools
import logging
import sqlite3
import time
from typing import Annotated, Any, Callable, TypeVar

from mcp.server.mcpserver.exceptions import ToolError
from mcp_types import ToolAnnotations
from pydantic import AfterValidator, BaseModel, Field, ValidationError

from app.database import DomainError

logger = logging.getLogger("mcp_server.tools")

F = TypeVar("F", bound=Callable[..., Any])

CONFIRM_DESCRIPTION = (
    "Set only by the backend after the human user has explicitly confirmed. "
    "Never set this yourself."
)


def _no_control_chars(value: str) -> str:
    if any((ord(c) < 32 and c not in "\n\t") or ord(c) == 127 for c in value):
        raise ValueError("must not contain control characters")
    return value


# A string with no control characters. Combine with Field(min_length=..., max_length=...).
SafeStr = Annotated[str, AfterValidator(_no_control_chars)]
# Strict integer id: rejects bools/floats/strings even if an upstream layer let them through.
RecordId = Annotated[int, Field(strict=True, ge=1, le=2_147_483_647)]


def read_only_annotations() -> ToolAnnotations:
    return ToolAnnotations(read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False)


def write_annotations(*, destructive: bool = False, idempotent: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        read_only_hint=False, destructive_hint=destructive, idempotent_hint=idempotent, open_world_hint=False
    )


def parse_input(model: type[BaseModel], **data: Any) -> Any:
    """Validate tool arguments with Pydantic, independent of the MCP layer's own checks."""
    try:
        return model(**data)
    except ValidationError as exc:
        parts = []
        for err in exc.errors()[:5]:
            loc = ".".join(str(p) for p in err["loc"]) or "input"
            parts.append(f"{loc}: {err['msg']}")
        raise ToolError("Invalid arguments - " + "; ".join(parts)) from None


def confirmation_required(summary: str, **extra: Any) -> dict[str, Any]:
    """Result returned instead of executing a destructive/consequential call.

    The call succeeded at the protocol level, but nothing was changed (executed=False).
    The backend turns this into a pending action that the human must confirm.
    """
    return {
        "ok": True,
        "executed": False,
        "confirmation_required": True,
        "message": f"Confirmation required: {summary}",
        "summary": summary,
        **extra,
    }


def guarded(fn: F) -> F:
    """Map domain/database errors to safe ToolErrors and log tool name, status and duration only."""

    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        started = time.perf_counter()
        status = "success"
        try:
            result = fn(*args, **kwargs)
            if isinstance(result, dict) and result.get("confirmation_required"):
                status = "confirmation_required"
            return result
        except ToolError:
            status = "rejected"
            raise
        except DomainError as exc:
            status = "rejected"
            raise ToolError(str(exc)) from None
        except sqlite3.Error:
            status = "db_error"
            logger.exception("tool=%s database error", fn.__name__)
            raise ToolError("A database error occurred while running the tool.") from None
        except Exception:
            status = "internal_error"
            logger.exception("tool=%s unexpected error", fn.__name__)
            raise ToolError("An internal error occurred while running the tool.") from None
        finally:
            logger.info(
                "tool=%s status=%s duration_ms=%d", fn.__name__, status, int((time.perf_counter() - started) * 1000)
            )

    return wrapper  # type: ignore[return-value]
