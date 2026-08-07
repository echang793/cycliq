"""Custom reminders (free tier).

There is no push infrastructure here: `due()` returns what should fire today and
the client shows it. That keeps notification data on the device instead of
routing cycle information through a push service.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import cycle as cyc
import db
import predict as pr
from deps import current_user

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

KINDS = {
    "period_soon": {"label": "Period is coming", "anchor": "next_period", "default_offset": -2},
    "period_late": {"label": "Period is late", "anchor": "next_period", "default_offset": 2},
    "ovulation_soon": {"label": "Ovulation is coming", "anchor": "ovulation", "default_offset": -2},
    "fertile_window": {"label": "Fertile window opens", "anchor": "fertile_start", "default_offset": 0},
    "pill": {"label": "Take contraception", "anchor": "daily", "default_offset": 0},
    "log": {"label": "Log today", "anchor": "daily", "default_offset": 0},
    "water": {"label": "Drink water", "anchor": "daily", "default_offset": 0},
    "custom": {"label": "Custom reminder", "anchor": "daily", "default_offset": 0},
}


class ReminderIn(BaseModel):
    kind: str
    label: str | None = None
    offset_days: int | None = None
    time_of_day: str = "09:00"
    enabled: bool = True


def _public(row: sqlite3.Row) -> dict:
    spec = KINDS.get(row["kind"], KINDS["custom"])
    return {
        "id": row["id"],
        "kind": row["kind"],
        "label": row["label"] or spec["label"],
        "anchor": spec["anchor"],
        "offset_days": row["offset_days"],
        "time_of_day": row["time_of_day"],
        "enabled": bool(row["enabled"]),
    }


@router.get("/kinds")
def kinds(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {"kinds": [{"key": k, **v} for k, v in KINDS.items()]}


@router.get("")
def list_reminders(user: sqlite3.Row = Depends(current_user)) -> dict:
    rows = db.query("SELECT * FROM reminders WHERE user_id = ? ORDER BY id", (user["id"],))
    return {"reminders": [_public(r) for r in rows]}


@router.post("")
def create(payload: ReminderIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    if payload.kind not in KINDS:
        raise HTTPException(400, detail={"error": "unknown_kind"})
    offset = payload.offset_days
    if offset is None:
        offset = KINDS[payload.kind]["default_offset"]
    reminder_id = db.execute(
        "INSERT INTO reminders (user_id, kind, label, enabled, offset_days, time_of_day, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (user["id"], payload.kind, payload.label, int(payload.enabled), offset,
         payload.time_of_day, auth.now_iso()),
    )
    row = db.query_one("SELECT * FROM reminders WHERE id = ?", (reminder_id,))
    return {"reminder": _public(row)}


@router.patch("/{reminder_id}")
def update(reminder_id: int, payload: ReminderIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one(
        "SELECT * FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user["id"])
    )
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    db.execute(
        "UPDATE reminders SET label = ?, enabled = ?, offset_days = ?, time_of_day = ?"
        " WHERE id = ?",
        (payload.label, int(payload.enabled),
         payload.offset_days if payload.offset_days is not None else row["offset_days"],
         payload.time_of_day, reminder_id),
    )
    return {"reminder": _public(db.query_one("SELECT * FROM reminders WHERE id = ?", (reminder_id,)))}


@router.delete("/{reminder_id}")
def delete(reminder_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one(
        "SELECT 1 FROM reminders WHERE id = ? AND user_id = ?", (reminder_id, user["id"])
    )
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    db.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
    return {"deleted": True}


def due(user_id: int, today: date | None = None) -> list[dict]:
    """Reminders that should fire today, resolved against current predictions."""
    today = today or date.today()
    prediction = pr.predict(user_id, today)
    anchors = {
        "next_period": prediction.next_period,
        "ovulation": prediction.ovulation,
        "fertile_start": prediction.fertile_start,
    }
    out = []
    for row in db.query("SELECT * FROM reminders WHERE user_id = ? AND enabled = 1", (user_id,)):
        spec = KINDS.get(row["kind"], KINDS["custom"])
        anchor = spec["anchor"]
        if anchor == "daily":
            out.append({**_public(row), "fires_on": cyc.iso(today)})
            continue
        anchor_date = anchors.get(anchor)
        if not anchor_date:
            continue
        fires = cyc.to_date(anchor_date) + timedelta(days=row["offset_days"])
        if fires == today:
            out.append({**_public(row), "fires_on": cyc.iso(fires)})
    return out


@router.get("/due")
def read_due(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {"due": due(user["id"])}
