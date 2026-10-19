"""Test setup. Tests NEVER call AWS: demo mode is on and boto3.Session is blocked."""
import os
import socket
import tempfile
import threading
import time
from contextlib import contextmanager
from pathlib import Path

import pytest

_TMP = tempfile.mkdtemp(prefix="alexa_backend_tests_")


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


MCP_PORT = _free_port()
os.environ.update(
    {
        "MOCK_MODE": "true",
        "APP_ENV": "test",
        "LOG_LEVEL": "WARNING",
        "DATABASE_PATH": str(Path(_TMP) / "test.db"),
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(MCP_PORT),
        "MCP_SERVER_URL": f"http://127.0.0.1:{MCP_PORT}/mcp",
        "MCP_AUTH_TOKEN": "test-token",
        "API_KEY": "",
        "BEDROCK_MODEL_ID": "",
        "AGENT_TIMEOUT_SECONDS": "30",
        "TOOL_TIMEOUT_SECONDS": "10",
    }
)

from app.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def _settings_cache():
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _forbid_aws(monkeypatch):
    """Fail loudly if anything tries to create a real AWS session."""
    import boto3

    def _blocked(*args, **kwargs):
        raise AssertionError("Tests must not create AWS sessions / paid Bedrock calls.")

    monkeypatch.setattr(boto3, "Session", _blocked)


@pytest.fixture(autouse=True)
def clean_db():
    from app import database as db

    db.init_db()
    with db.get_connection() as conn:
        conn.executescript(
            "DELETE FROM tasks; DELETE FROM reminders; DELETE FROM inventory; "
            "DELETE FROM pending_actions; DELETE FROM sqlite_sequence;"
        )
        db.seed_demo_inventory(conn)


@pytest.fixture(scope="session")
def mcp_server():
    """A real MCP server (Streamable HTTP) running in a background thread."""
    import uvicorn

    from mcp_server.server import create_app

    server = uvicorn.Server(uvicorn.Config(create_app(), host="127.0.0.1", port=MCP_PORT, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 20
    while not server.started and time.time() < deadline:
        time.sleep(0.05)
    assert server.started, "MCP test server failed to start"
    yield f"http://127.0.0.1:{MCP_PORT}"
    server.should_exit = True
    thread.join(timeout=10)


@contextmanager
def _client_ctx(monkeypatch, **env):
    from fastapi.testclient import TestClient

    for key, value in env.items():
        monkeypatch.setenv(key, value)
    get_settings.cache_clear()
    from app.main import create_app

    with TestClient(create_app(), raise_server_exceptions=False) as client:
        yield client


@pytest.fixture
def make_client(monkeypatch, mcp_server):
    """Factory: make_client(ENV_VAR='x') -> context manager yielding a TestClient with that env."""
    return lambda **env: _client_ctx(monkeypatch, **env)


@pytest.fixture
def client(make_client):
    with make_client() as c:
        yield c
