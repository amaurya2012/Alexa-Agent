"""Inventory tools: check_inventory, update_inventory."""
from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from mcp.server.mcpserver import MCPServer
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app import database as db
from mcp_server.tools import (
    CONFIRM_DESCRIPTION,
    SafeStr,
    confirmation_required,
    guarded,
    parse_input,
    read_only_annotations,
    write_annotations,
)

ITEM_MAX = 80
UNIT_MAX = 20
QTY_MAX = 100_000


def _normalise_name(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


class CheckInventoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_name: SafeStr | None = Field(default=None, max_length=ITEM_MAX)

    @field_validator("item_name")
    @classmethod
    def _norm(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = _normalise_name(value)
        return value or None


class UpdateInventoryInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    item_name: SafeStr = Field(min_length=1, max_length=ITEM_MAX)
    operation: Literal["add", "remove", "set"]
    quantity: int = Field(strict=True, ge=0, le=QTY_MAX)
    unit: SafeStr | None = Field(default=None, max_length=UNIT_MAX)
    confirm: bool = Field(default=False, strict=True)

    @field_validator("item_name")
    @classmethod
    def _norm(cls, value: str) -> str:
        value = _normalise_name(value)
        if not value:
            raise ValueError("must not be blank")
        return value

    @model_validator(mode="after")
    def _check_quantity(self) -> "UpdateInventoryInput":
        if self.operation in ("add", "remove") and self.quantity < 1:
            raise ValueError("quantity must be at least 1 for add/remove")
        return self


def _with_flags(item: dict[str, Any]) -> dict[str, Any]:
    return {**item, "low_stock": item["quantity"] <= item["low_stock_threshold"]}


@guarded
def check_inventory(
    item_name: Annotated[
        str | None,
        Field(description="Item to look up (partial names match). Omit to list the whole inventory.", max_length=ITEM_MAX),
    ] = None,
) -> dict[str, Any]:
    """Check stock levels for one item, or list everything in the inventory."""
    data = parse_input(CheckInventoryInput, item_name=item_name)
    items = db.search_inventory(data.item_name) if data.item_name else db.list_inventory()
    items = [_with_flags(i) for i in items]
    if data.item_name and not items:
        return {
            "ok": True,
            "found": False,
            "message": f"No inventory item matching '{data.item_name}'",
            "count": 0,
            "items": [],
        }
    return {"ok": True, "found": True, "message": f"{len(items)} item(s) found", "count": len(items), "items": items}


@guarded
def update_inventory(
    item_name: Annotated[str, Field(description="Inventory item name.", max_length=ITEM_MAX)],
    operation: Annotated[
        Literal["add", "remove", "set"],
        Field(description="add = increase stock, remove = decrease stock, set = overwrite the quantity."),
    ],
    quantity: Annotated[int, Field(description="Quantity to add/remove, or the new total for 'set'.", ge=0, le=QTY_MAX)],
    unit: Annotated[
        str | None, Field(description="Unit label, used only when a NEW item is created.", max_length=UNIT_MAX)
    ] = None,
    confirm: Annotated[bool, Field(description=CONFIRM_DESCRIPTION)] = False,
) -> dict[str, Any]:
    """Add, remove or set stock for an item. 'remove' and 'set' need explicit user confirmation."""
    data = parse_input(
        UpdateInventoryInput, item_name=item_name, operation=operation, quantity=quantity, unit=unit, confirm=confirm
    )
    if data.operation in ("remove", "set") and not data.confirm:
        verb = "Remove" if data.operation == "remove" else "Set stock of"
        tail = f"{data.quantity} from '{data.item_name}'" if data.operation == "remove" else f"'{data.item_name}' to {data.quantity}"
        return confirmation_required(f"{verb} {tail}")
    result = db.apply_inventory_update(data.item_name, data.operation, data.quantity, data.unit)
    item = _with_flags(result["item"])
    before = result["previous_quantity"]
    change = f"{before} -> {item['quantity']}" if before is not None else f"new item, {item['quantity']}"
    return {
        "ok": True,
        "executed": True,
        "message": f"Inventory updated: {item['item_name']} ({change} {item['unit']})",
        "created": result["created"],
        "previous_quantity": before,
        "item": item,
    }


def register(mcp: MCPServer) -> None:
    mcp.tool(name="check_inventory", annotations=read_only_annotations())(check_inventory)
    mcp.tool(name="update_inventory", annotations=write_annotations(destructive=True))(update_inventory)
