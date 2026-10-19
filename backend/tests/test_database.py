import pytest

from app import database as db


def test_task_lifecycle():
    t = db.insert_task("Buy milk", "2 liters", "high", "2026-12-01")
    assert t["id"] == 1 and t["status"] == "pending" and t["priority"] == "high"
    assert [x["id"] for x in db.list_tasks("pending")] == [1]

    done, changed = db.complete_task(1)
    assert changed and done["status"] == "completed" and done["completed_at"]
    _, changed_again = db.complete_task(1)
    assert changed_again is False
    assert db.list_tasks("pending") == [] and len(db.list_tasks("completed")) == 1

    deleted = db.delete_task(1)
    assert deleted["title"] == "Buy milk"
    assert db.get_task(1) is None


def test_missing_task_raises_domain_error():
    with pytest.raises(db.DomainError):
        db.complete_task(999)
    with pytest.raises(db.DomainError):
        db.delete_task(999)


def test_list_tasks_orders_pending_first():
    a = db.insert_task("a", None, "normal", None)
    db.insert_task("b", None, "normal", None)
    db.complete_task(a["id"])
    assert [t["title"] for t in db.list_tasks(None)] == ["b", "a"]


def test_reminders_are_stored_ordered_by_time():
    db.insert_reminder("later", "2030-01-02T09:00:00+00:00")
    db.insert_reminder("sooner", "2030-01-01T09:00:00+00:00")
    reminders = db.list_reminders()
    assert [r["text"] for r in reminders] == ["sooner", "later"]
    assert all(r["status"] == "stored" for r in reminders)


def test_inventory_seeded_and_seed_is_idempotent():
    before = db.list_inventory()
    assert len(before) >= 8 and any(i["item_name"] == "milk" for i in before)
    db.init_db()
    assert len(db.list_inventory()) == len(before)


def test_inventory_search_exact_partial_and_wildcards():
    assert [i["item_name"] for i in db.search_inventory("MILK")] == ["milk"]  # case-insensitive exact
    assert [i["item_name"] for i in db.search_inventory("batter")] == ["batteries AA"]  # partial
    assert db.search_inventory("%") == []  # LIKE wildcards are escaped


def test_inventory_add_remove_set_and_create():
    r = db.apply_inventory_update("eggs", "add", 6, None)
    assert r["previous_quantity"] == 12 and r["item"]["quantity"] == 18 and not r["created"]
    r = db.apply_inventory_update("eggs", "remove", 8, None)
    assert r["item"]["quantity"] == 10
    r = db.apply_inventory_update("eggs", "set", 3, None)
    assert r["item"]["quantity"] == 3
    r = db.apply_inventory_update("Dish Soap", "add", 2, "bottles")
    assert r["created"] and r["item"]["unit"] == "bottles"


def test_inventory_rejects_overdraw_and_unknown_removal():
    with pytest.raises(db.DomainError, match="Insufficient stock"):
        db.apply_inventory_update("milk", "remove", 99, None)
    with pytest.raises(db.DomainError, match="not in the inventory"):
        db.apply_inventory_update("unobtainium", "remove", 1, None)
    assert next(i for i in db.list_inventory() if i["item_name"] == "milk")["quantity"] == 2  # unchanged


def test_pending_actions_expire_cancel_and_resolve():
    live = db.create_pending_action("delete_task", {"task_id": 1}, "Delete task #1", 300)
    db.create_pending_action("delete_task", {"task_id": 2}, "Delete task #2", -5)  # already expired
    active = db.get_active_pending_actions()
    assert [a["id"] for a in active] == [live["id"]]
    assert active[0]["arguments"] == {"task_id": 1}

    db.resolve_pending_action(live["id"], "executed")
    assert db.get_active_pending_actions() == []

    db.create_pending_action("delete_task", {"task_id": 3}, "Delete task #3", 300)
    assert db.cancel_pending_actions() == 1
    assert db.get_active_pending_actions() == []
