"""Application error types. Messages here are safe to show to API clients."""
from __future__ import annotations


class ApiError(Exception):
    """Base class for errors that map to a clean JSON error response."""

    status_code: int = 500
    code: str = "internal_error"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code


class BedrockError(ApiError):
    """Amazon Bedrock call failed (message is already sanitised)."""

    status_code = 502
    code = "model_error"


class McpUnavailableError(ApiError):
    """The MCP tool server could not be reached or did not answer in time."""

    status_code = 503
    code = "tool_server_unavailable"


class AgentTimeoutError(ApiError):
    status_code = 504
    code = "agent_timeout"
