"""SQLite persistence shared by the MCP server (writes) and the FastAPI app (read-only views).

Every public function opens a short-lived connection, so it is safe to call from any thread or
process. WAL mode lets the two processes use the same file concurrently.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator

from app.config import get_settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL CHECK (length(title) BETWEEN 1 AND 200),
    notes TEXT,
    priority TEXT NOT NULL DEFAULT 'normal' CHECK (priority IN ('low', 'normal', 'high')),
    due_date TEXT,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'completed')),
    created_at TEXT NOT NULL,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS reminders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 300),
    remind_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'stored',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS inventory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_name TEXT NOT NULL COLLATE NOCASE UNIQUE CHECK (length(item_name) BETWEEN 1 AND 80),
    quantity INTEGER NOT NULL CHECK (quantity >= 0),
    unit TEXT NOT NULL DEFAULT 'units',
    low_stock_threshold INTEGER NOT NULL DEFAULT 1 CHECK (low_stock_threshold >= 0),
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pending_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    tool TEXT NOT NULL,
    arguments TEXT NOT NULL,
    summary TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'executed', 'failed', 'cancelled', 'expired')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);
"""

# (item_name, quantity, unit, low_stock_threshold)
DEMO_INVENTORY: list[tuple[str, int, str, int]] = [
    ("milk", 2, "liters", 2),
    ("eggs", 12, "pcs", 6),
    ("bread", 1, "loaves", 1),
    ("coffee beans", 500, "grams", 200),
    ("paper towels", 4, "rolls", 2),
    ("batteries AA", 8, "pcs", 4),
    ("olive oil", 1, "bottles", 1),
    ("rice", 3, "kg", 1),
    ("laundry detergent", 1, "bottles", 1),
    ("light bulbs", 5, "pcs", 2),
]

MAX_QUANTITY = 1_000_000


class DomainError(Exception):
    """A business-rule failure whose message is safe to show to the model and the user."""

    def __init__(self, message: str, code: str = "domain_error"):
        super().__init__(message)
        self.code = code


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def utcnow_iso() -> str:
    return utcnow().isoformat(timespec="seconds")


@contextmanager
def get_connection() -> Iterator[sqlite3.Connection]:
    conn = sqlite3.connect(str(get_settings().database_path), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def _row(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def _rows(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


# --------------------------------------------------------------------------- setup
def seed_demo_inventory(conn: sqlite3.Connection) -> None:
    """Insert demo inventory only when the table is empty."""
    if conn.execute("SELECT COUNT(*) FROM inventory").fetchone()[0] == 0:
        now = utcnow_iso()
        conn.executemany(
            "INSERT OR IGNORE INTO inventory (item_name, quantity, unit, low_stock_threshold, updated_at) "
            "VALUES (?, ?, ?, ?, ?)",
            [(n, q, u, t, now) for n, q, u, t in DEMO_INVENTORY],
        )


def init_db() -> None:
    """Create tables and seed demo inventory. Idempotent; safe to call from both processes."""
    path = Path(get_settings().database_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with get_connection() as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(SCHEMA)
        seed_demo_inventory(conn)


def check_database() -> bool:
    try:
        with get_connection() as conn:
            conn.execute("SELECT 1").fetchone()
        return True
    except sqlite3.Error:
        return False


# --------------------------------------------------------------------------- tasks
def insert_task(title: str, notes: str | None, priority: str, due_date: str | None) -> dict[str, Any]:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO tasks (title, notes, priority, due_date, status, created_at) "
            "VALUES (?, ?, ?, ?, 'pending', ?)",
            (title, notes, priority, due_date, utcnow_iso()),
        )
        return _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_tasks(status: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
    sql = "SELECT * FROM tasks"
    params: list[Any] = []
    if status in ("pending", "completed"):
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY CASE status WHEN 'pending' THEN 0 ELSE 1 END, id ASC LIMIT ?"
    params.append(limit)
    with get_connection() as conn:
        return _rows(conn.execute(sql, params).fetchall())


def get_task(task_id: int) -> dict[str, Any] | None:
    with get_connection() as conn:
        return _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())


def complete_task(task_id: int) -> tuple[dict[str, Any], bool]:
    """Returns (task, changed). changed is False if the task was already completed."""
    with get_connection() as conn:
        task = _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
        if task is None:
            raise DomainError(f"Task {task_id} not found.", "not_found")
        if task["status"] == "completed":
            return task, False
        conn.execute(
            "UPDATE tasks SET status = 'completed', completed_at = ? WHERE id = ?",
            (utcnow_iso(), task_id),
        )
        return _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()), True  # type: ignore[return-value]


def delete_task(task_id: int) -> dict[str, Any]:
    with get_connection() as conn:
        task = _row(conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone())
        if task is None:
            raise DomainError(f"Task {task_id} not found.", "not_found")
        conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        return task


# --------------------------------------------------------------------------- reminders
def insert_reminder(text: str, remind_at_iso: str) -> dict[str, Any]:
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO reminders (text, remind_at, status, created_at) VALUES (?, ?, 'stored', ?)",
            (text, remind_at_iso, utcnow_iso()),
        )
        return _row(conn.execute("SELECT * FROM reminders WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def list_reminders(limit: int = 100) -> list[dict[str, Any]]:
    with get_connection() as conn:
        return _rows(
            conn.execute("SELECT * FROM reminders ORDER BY remind_at ASC, id ASC LIMIT ?", (limit,)).fetchall()
        )


# --------------------------------------------------------------------------- inventory
def list_inventory() -> list[dict[str, Any]]:
    with get_connection() as conn:
        return _rows(conn.execute("SELECT * FROM inventory ORDER BY item_name COLLATE NOCASE").fetchall())


def search_inventory(query: str) -> list[dict[str, Any]]:
    """Exact (case-insensitive) match first; otherwise substring matches."""
    with get_connection() as conn:
        exact = conn.execute("SELECT * FROM inventory WHERE item_name = ?", (query,)).fetchall()
        if exact:
            return _rows(exact)
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        like = conn.execute(
            "SELECT * FROM inventory WHERE item_name LIKE ? ESCAPE '\\' ORDER BY item_name COLLATE NOCASE LIMIT 25",
            (f"%{escaped}%",),
        ).fetchall()
        return _rows(like)


def apply_inventory_update(
    item_name: str, operation: str, quantity: int, unit: str | None
) -> dict[str, Any]:
    """Atomically add / remove / set stock. Returns {item, previous_quantity, created}."""
    with get_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        existing = _row(conn.execute("SELECT * FROM inventory WHERE item_name = ?", (item_name,)).fetchone())
        now = utcnow_iso()
        if existing is None:
            if operation == "remove":
                raise DomainError(f"'{item_name}' is not in the inventory.", "not_found")
            cur = conn.execute(
                "INSERT INTO inventory (item_name, quantity, unit, low_stock_threshold, updated_at) "
                "VALUES (?, ?, ?, 1, ?)",
                (item_name, quantity, unit or "units", now),
            )
            item = _row(conn.execute("SELECT * FROM inventory WHERE id = ?", (cur.lastrowid,)).fetchone())
            return {"item": item, "previous_quantity": None, "created": True}

        previous = existing["quantity"]
        if operation == "add":
            new_qty = previous + quantity
        elif operation == "remove":
            if quantity > previous:
                raise DomainError(
                    f"Insufficient stock: only {previous} {existing['unit']} of '{existing['item_name']}' available.",
                    "insufficient_stock",
                )
            new_qty = previous - quantity
        else:  # set
            new_qty = quantity
        if new_qty > MAX_QUANTITY:
            raise DomainError(f"Quantity would exceed the maximum of {MAX_QUANTITY}.", "quantity_limit")
        conn.execute(
            "UPDATE inventory SET quantity = ?, updated_at = ? WHERE id = ?", (new_qty, now, existing["id"])
        )
        item = _row(conn.execute("SELECT * FROM inventory WHERE id = ?", (existing["id"],)).fetchone())
        return {"item": item, "previous_quantity": previous, "created": False}


# --------------------------------------------------------------------------- pending confirmations
def create_pending_action(tool: str, arguments: dict[str, Any], summary: str, ttl_seconds: int) -> dict[str, Any]:
    now = utcnow()
    with get_connection() as conn:
        cur = conn.execute(
            "INSERT INTO pending_actions (tool, arguments, summary, status, created_at, expires_at) "
            "VALUES (?, ?, ?, 'pending', ?, ?)",
            (
                tool,
                json.dumps(arguments, separators=(",", ":")),
                summary,
                now.isoformat(timespec="seconds"),
                (now + timedelta(seconds=ttl_seconds)).isoformat(timespec="seconds"),
            ),
        )
        return _row(conn.execute("SELECT * FROM pending_actions WHERE id = ?", (cur.lastrowid,)).fetchone())  # type: ignore[return-value]


def get_active_pending_actions() -> list[dict[str, Any]]:
    """Pending actions that have not expired (expired ones are flagged as a side effect)."""
    now = utcnow_iso()
    with get_connection() as conn:
        conn.execute(
            "UPDATE pending_actions SET status = 'expired' WHERE status = 'pending' AND expires_at <= ?", (now,)
        )
        rows = _rows(
            conn.execute("SELECT * FROM pending_actions WHERE status = 'pending' ORDER BY id ASC").fetchall()
        )
    for r in rows:
        r["arguments"] = json.loads(r["arguments"])
    return rows


def resolve_pending_action(action_id: int, status: str) -> None:
    with get_connection() as conn:
        conn.execute("UPDATE pending_actions SET status = ? WHERE id = ? AND status = 'pending'", (status, action_id))


def cancel_pending_actions() -> int:
    with get_connection() as conn:
        cur = conn.execute("UPDATE pending_actions SET status = 'cancelled' WHERE status = 'pending'")
        return cur.rowcount
