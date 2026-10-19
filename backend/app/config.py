"""Environment-driven configuration. All tunables, including model IDs, come from env vars."""
from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BACKEND_DIR / ".env", override=False)  # real environment variables win

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}

REMINDER_NOTICE = (
    "Reminders are stored only. No notification (push, SMS, email or voice) is sent "
    "unless a notification provider is integrated."
)


class ConfigError(RuntimeError):
    """Invalid or missing configuration."""


def _str(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    value = raw.strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false.")


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = _str(name)
    if raw == "":
        return default
    try:
        value = int(raw)
    except ValueError:
        raise ConfigError(f"{name} must be an integer.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _float(name: str, default: float, minimum: float, maximum: float) -> float:
    raw = _str(name)
    if raw == "":
        return default
    try:
        value = float(raw)
    except ValueError:
        raise ConfigError(f"{name} must be a number.") from None
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _path(name: str, default: str) -> Path:
    raw = _str(name, default) or default
    path = Path(raw)
    return path if path.is_absolute() else (BACKEND_DIR / path).resolve()


@dataclass(frozen=True)
class Settings:
    app_env: str
    log_level: str
    mock_mode: bool
    # Bedrock
    aws_region: str
    aws_profile: str
    bedrock_model_id: str
    bedrock_max_tokens: int
    bedrock_temperature: float
    bedrock_connect_timeout: float
    bedrock_read_timeout: float
    bedrock_max_retries: int
    # MCP
    mcp_host: str
    mcp_port: int
    mcp_server_url: str
    mcp_auth_token: str
    # Agent
    agent_max_iterations: int
    agent_max_tool_calls: int
    agent_timeout_seconds: float
    tool_timeout_seconds: float
    max_message_chars: int
    confirmation_ttl_seconds: int
    # Storage / API
    database_path: Path
    cors_origins: tuple[str, ...]
    api_key: str

    @property
    def mcp_base_url(self) -> str:
        parsed = urlparse(self.mcp_server_url)
        return f"{parsed.scheme}://{parsed.netloc}"

    @classmethod
    def from_env(cls) -> "Settings":
        origins = tuple(
            o.strip()
            for o in _str("CORS_ORIGINS", "http://localhost:5173,http://localhost:3000").split(",")
            if o.strip()
        )
        return cls(
            app_env=_str("APP_ENV", "development"),
            log_level=_str("LOG_LEVEL", "INFO").upper(),
            mock_mode=_bool("MOCK_MODE", True),
            aws_region=_str("AWS_REGION", "us-east-1"),
            aws_profile=_str("AWS_PROFILE"),
            bedrock_model_id=_str("BEDROCK_MODEL_ID"),
            bedrock_max_tokens=_int("BEDROCK_MAX_TOKENS", 1024, 64, 8192),
            bedrock_temperature=_float("BEDROCK_TEMPERATURE", 0.2, 0.0, 1.0),
            bedrock_connect_timeout=_float("BEDROCK_CONNECT_TIMEOUT_SECONDS", 5, 1, 60),
            bedrock_read_timeout=_float("BEDROCK_READ_TIMEOUT_SECONDS", 60, 5, 300),
            bedrock_max_retries=_int("BEDROCK_MAX_RETRIES", 2, 0, 5),
            mcp_host=_str("MCP_HOST", "127.0.0.1"),
            mcp_port=_int("MCP_PORT", 8765, 1, 65535),
            mcp_server_url=_str("MCP_SERVER_URL", "http://127.0.0.1:8765/mcp"),
            mcp_auth_token=_str("MCP_AUTH_TOKEN"),
            agent_max_iterations=_int("AGENT_MAX_ITERATIONS", 6, 1, 20),
            agent_max_tool_calls=_int("AGENT_MAX_TOOL_CALLS", 8, 1, 50),
            agent_timeout_seconds=_float("AGENT_TIMEOUT_SECONDS", 90, 5, 600),
            tool_timeout_seconds=_float("TOOL_TIMEOUT_SECONDS", 15, 1, 120),
            max_message_chars=_int("MAX_MESSAGE_CHARS", 2000, 10, 20000),
            confirmation_ttl_seconds=_int("CONFIRMATION_TTL_SECONDS", 300, 10, 3600),
            database_path=_path("DATABASE_PATH", "data/alexa_agent.db"),
            cors_origins=origins,
            api_key=_str("API_KEY"),
        )

    def validate(self) -> None:
        """Fail fast on configuration that cannot work."""
        if not self.mock_mode and not self.bedrock_model_id:
            raise ConfigError("BEDROCK_MODEL_ID is required when MOCK_MODE=false.")
        if urlparse(self.mcp_server_url).scheme not in {"http", "https"}:
            raise ConfigError("MCP_SERVER_URL must start with http:// or https://")
        if self.mcp_host not in LOOPBACK_HOSTS and not self.mcp_auth_token:
            raise ConfigError("MCP_AUTH_TOKEN is required when MCP_HOST is not a loopback address.")


@lru_cache
def get_settings() -> Settings:
    return Settings.from_env()
