"""Partner Mode.

The owner grants named scopes; the partner view is assembled *from the scope
list*, never filtered client-side. A free-tier owner is additionally capped to
BASIC_SCOPES at read time, so downgrading a subscription immediately narrows
what a partner can already see.
"""

from __future__ import annotations

import json
import secrets
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import billing
import cycle as cyc
import db
import predict as pr
import symptoms as sym
from deps import current_user

router = APIRouter(prefix="/api/partner", tags=["partner"])

SCOPES = {
    "cycle_phase": "Current cycle phase and day",
    "period_dates": "When the next period is expected",
    "fertile_window": "Fertile window and ovulation",
    "symptoms": "Symptoms logged today",
    "mood": "Mood logged today",
    "pregnancy": "Pregnancy progress",
}
BASIC_SCOPES = {"cycle_phase", "period_dates"}

TIPS = {
    "menstrual": [
        "Cramps and fatigue are common right now — offer the boring, useful help: a hot pack, dinner handled.",
        "Energy is often lowest in the first two days. Plans that can move, should be able to move.",
    ],
    "follicular": [
        "Energy usually climbs after the period ends. Good stretch for plans that need momentum.",
    ],
    "ovulatory": [
        "This is the fertile window. If you're trying to conceive, this is the time; if you're avoiding it, it's the time to be careful.",
    ],
    "luteal": [
        "PMS symptoms tend to show up in the days before a period — mood shifts here are hormonal, not a verdict on you.",
        "Cravings and bloating are typical late-luteal. Not the week to comment on either.",
    ],
}


class InviteIn(BaseModel):
    scopes: list[str] = ["cycle_phase", "period_dates"]


class JoinIn(BaseModel):
    code: str


class ScopesIn(BaseModel):
    scopes: list[str]


def _clean_scopes(scopes: list[str]) -> list[str]:
    return [s for s in dict.fromkeys(scopes) if s in SCOPES]


def effective_scopes(owner_id: int, stored: list[str]) -> list[str]:
    """Premium unlocks the full scope set; free owners share the basics only."""
    if billing.is_premium(owner_id):
        return stored
    return [s for s in stored if s in BASIC_SCOPES]


def _link_public(row: sqlite3.Row, role: str) -> dict:
    stored = json.loads(row["scopes"])
    return {
        "id": row["id"],
        "role": role,
        "status": row["status"],
        "invite_code": row["invite_code"] if row["status"] == "pending" else None,
        "scopes": stored,
        "effective_scopes": effective_scopes(row["owner_id"], stored),
        "created_at": row["created_at"],
    }


@router.get("/scopes")
def scope_catalog(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {
        "scopes": [{"key": k, "label": v, "basic": k in BASIC_SCOPES} for k, v in SCOPES.items()],
        "basic_scopes": sorted(BASIC_SCOPES),
    }


@router.get("/links")
def list_links(user: sqlite3.Row = Depends(current_user)) -> dict:
    owned = db.query("SELECT * FROM partner_links WHERE owner_id = ?", (user["id"],))
    joined = db.query("SELECT * FROM partner_links WHERE partner_id = ?", (user["id"],))
    return {
        "owned": [_link_public(r, "owner") for r in owned],
        "following": [
            {**_link_public(r, "partner"), "owner_handle": _handle(r["owner_id"])}
            for r in joined
        ],
    }


def _handle(user_id: int) -> str:
    row = db.query_one("SELECT handle FROM users WHERE id = ?", (user_id,))
    return row["handle"] if row else "member"


@router.post("/invite")
def create_invite(payload: InviteIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    scopes = _clean_scopes(payload.scopes) or ["cycle_phase"]
    code = "-".join(secrets.token_hex(2) for _ in range(2))
    link_id = db.execute(
        "INSERT INTO partner_links (owner_id, invite_code, scopes, status, created_at)"
        " VALUES (?, ?, ?, 'pending', ?)",
        (user["id"], code, json.dumps(scopes), auth.now_iso()),
    )
    row = db.query_one("SELECT * FROM partner_links WHERE id = ?", (link_id,))
    return {"link": _link_public(row, "owner"), "invite_code": code}


@router.post("/join")
def join(payload: JoinIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one(
        "SELECT * FROM partner_links WHERE invite_code = ?", (payload.code.strip(),)
    )
    if row is None or row["status"] != "pending":
        raise HTTPException(404, detail={"error": "invalid_code"})
    if row["owner_id"] == user["id"]:
        raise HTTPException(400, detail={"error": "cannot_partner_self"})
    db.execute(
        "UPDATE partner_links SET partner_id = ?, status = 'active' WHERE id = ?",
        (user["id"], row["id"]),
    )
    updated = db.query_one("SELECT * FROM partner_links WHERE id = ?", (row["id"],))
    return {"link": {**_link_public(updated, "partner"), "owner_handle": _handle(row["owner_id"])}}


@router.post("/links/{link_id}/scopes")
def update_scopes(
    link_id: int, payload: ScopesIn, user: sqlite3.Row = Depends(current_user)
) -> dict:
    row = db.query_one(
        "SELECT * FROM partner_links WHERE id = ? AND owner_id = ?", (link_id, user["id"])
    )
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    db.execute(
        "UPDATE partner_links SET scopes = ? WHERE id = ?",
        (json.dumps(_clean_scopes(payload.scopes)), link_id),
    )
    return {"link": _link_public(db.query_one("SELECT * FROM partner_links WHERE id = ?", (link_id,)), "owner")}


@router.delete("/links/{link_id}")
def revoke(link_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one(
        "SELECT * FROM partner_links WHERE id = ? AND (owner_id = ? OR partner_id = ?)",
        (link_id, user["id"], user["id"]),
    )
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    db.execute("DELETE FROM partner_links WHERE id = ?", (link_id,))
    return {"revoked": True}


def partner_view(link: sqlite3.Row, today: date | None = None) -> dict:
    """Build the partner payload strictly from the granted scopes."""
    today = today or date.today()
    owner_id = link["owner_id"]
    scopes = set(effective_scopes(owner_id, json.loads(link["scopes"])))
    prediction = pr.predict(owner_id, today)

    view: dict = {
        "owner_handle": _handle(owner_id),
        "scopes": sorted(scopes),
        "date": cyc.iso(today),
    }

    if "cycle_phase" in scopes:
        view["cycle_day"] = prediction.cycle_day
        view["phase"] = prediction.phase
        view["tips"] = TIPS.get(prediction.phase or "", [])
    if "period_dates" in scopes:
        view["next_period"] = prediction.next_period
        view["next_period_low"] = prediction.next_period_low
        view["next_period_high"] = prediction.next_period_high
        view["days_to_period"] = prediction.days_to_period
    if "fertile_window" in scopes:
        view["fertile_start"] = prediction.fertile_start
        view["fertile_end"] = prediction.fertile_end
        view["ovulation"] = prediction.ovulation
    if "symptoms" in scopes or "mood" in scopes:
        entries = sym.day_log(owner_id, today)["entries"]
        wanted = set()
        if "symptoms" in scopes:
            wanted |= {"symptoms", "flow"}
        if "mood" in scopes:
            wanted |= {"mood"}
        view["today_logged"] = [
            {"label": e["label"], "category": e["category"]}
            for e in entries
            if e["category"] in wanted
        ]
    if "pregnancy" in scopes:
        row = db.query_one(
            "SELECT due_date FROM pregnancies WHERE user_id = ? AND active = 1"
            " ORDER BY id DESC LIMIT 1",
            (owner_id,),
        )
        if row:
            due = cyc.to_date(row["due_date"])
            days_along = 280 - (due - today).days
            view["pregnancy"] = {
                "due_date": row["due_date"],
                "week": max(0, days_along // 7),
                "days_to_due": (due - today).days,
            }
    return view


@router.get("/view/{link_id}")
def read_partner_view(link_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one(
        "SELECT * FROM partner_links WHERE id = ? AND partner_id = ? AND status = 'active'",
        (link_id, user["id"]),
    )
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return partner_view(row)
