"""cycliq API + PWA host.

Run: .venv/bin/python src/server.py  ->  http://127.0.0.1:8103
"""

from __future__ import annotations

import sqlite3
import sys
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import Depends, FastAPI, HTTPException, Response  # noqa: E402
from fastapi.responses import FileResponse, JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import assistant  # noqa: E402
import auth  # noqa: E402
import billing  # noqa: E402
import checker  # noqa: E402
import community  # noqa: E402
import content  # noqa: E402
import cycle as cyc  # noqa: E402
import db  # noqa: E402
import importer  # noqa: E402
import insights  # noqa: E402
import partner  # noqa: E402
import patterns  # noqa: E402
import predict as pr  # noqa: E402
import pregnancy  # noqa: E402
import reminders  # noqa: E402
import report  # noqa: E402
import symptoms as sym  # noqa: E402
import ttc  # noqa: E402
from deps import COOKIE, current_user  # noqa: E402

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    db.init_db()
    yield


app = FastAPI(title="cycliq", version="1.0", docs_url="/api/docs", lifespan=lifespan)


@app.middleware("http")
async def no_heuristic_caching(request, call_next):
    """Force revalidation on every app-shell asset.

    StaticFiles ships Last-Modified but no Cache-Control, which lets browsers
    apply *heuristic* freshness (commonly ~10% of file age) and reuse a stale
    copy without ever asking the server — found during the 2026-08-06 debug
    session: a JS fix did not reach an already-open tab across two ordinary
    reloads. `no-cache` still allows a cheap conditional GET (304 on no
    change) but guarantees new code is never silently skipped after a deploy.
    """
    response = await call_next(request)
    path = request.url.path
    if path == "/" or path.startswith("/static/") or path in ("/sw.js", "/manifest.json"):
        response.headers["Cache-Control"] = "no-cache"
    return response


# --------------------------------------------------------------------------
# auth + profile


class SignupIn(BaseModel):
    email: str
    password: str


class LoginIn(BaseModel):
    email: str
    password: str


class RecoveryIn(BaseModel):
    handle: str
    code: str


class ProfileIn(BaseModel):
    mode: str | None = None
    goal: str | None = None
    birth_year: int | None = None
    avg_cycle_len: int | None = None
    avg_period_len: int | None = None
    onboarded: bool | None = None


def _sign_in(response: Response, user_id: int) -> dict:
    token = auth.create_session(user_id)
    response.set_cookie(
        COOKIE, token, httponly=True, samesite="lax", max_age=auth.SESSION_DAYS * 86400
    )
    row = auth.get_user(user_id)
    return {"user": auth.public_user(row)}


@app.post("/api/auth/signup")
def signup(payload: SignupIn, response: Response) -> dict:
    try:
        user_id = auth.create_user(payload.email, payload.password)
    except auth.AuthError as exc:
        raise HTTPException(400, detail={"error": "signup_failed", "message": str(exc)}) from exc
    return _sign_in(response, user_id)


@app.post("/api/auth/anonymous")
def signup_anonymous(response: Response) -> dict:
    user_id, code = auth.create_anonymous_user()
    out = _sign_in(response, user_id)
    out["recovery_code"] = code
    out["message"] = (
        "Anonymous Mode: no email, no name. Save this recovery code — with no email "
        "there is no other way back into this account."
    )
    return out


@app.post("/api/auth/login")
def login(payload: LoginIn, response: Response) -> dict:
    try:
        row = auth.login(payload.email, payload.password)
    except auth.AuthError as exc:
        raise HTTPException(401, detail={"error": "login_failed", "message": str(exc)}) from exc
    return _sign_in(response, row["id"])


@app.post("/api/auth/login/recovery")
def login_recovery(payload: RecoveryIn, response: Response) -> dict:
    try:
        row = auth.login_recovery(payload.handle, payload.code)
    except auth.AuthError as exc:
        raise HTTPException(401, detail={"error": "login_failed", "message": str(exc)}) from exc
    return _sign_in(response, row["id"])


@app.post("/api/auth/logout")
def logout(response: Response, user: sqlite3.Row = Depends(current_user)) -> dict:
    auth.destroy_session(None)
    db.execute("DELETE FROM sessions WHERE user_id = ?", (user["id"],))
    response.delete_cookie(COOKIE)
    return {"logged_out": True}


@app.get("/api/me")
def read_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    return {"user": auth.public_user(user), "billing": billing.status(user["id"])}


@app.patch("/api/me")
def update_me(payload: ProfileIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    fields, values = [], []
    for column in ("mode", "goal", "birth_year", "avg_cycle_len", "avg_period_len"):
        value = getattr(payload, column)
        if value is not None:
            fields.append(f"{column} = ?")
            values.append(value)
    if payload.onboarded is not None:
        fields.append("onboarded = ?")
        values.append(int(payload.onboarded))
    if fields:
        db.execute(f"UPDATE users SET {', '.join(fields)} WHERE id = ?", (*values, user["id"]))
    return {"user": auth.public_user(auth.get_user(user["id"]))}


@app.get("/api/me/export")
def export_me(user: sqlite3.Row = Depends(current_user)) -> dict:
    """Everything held about this account, in one JSON document."""
    uid = user["id"]
    tables = {
        "periods": "SELECT * FROM period_events WHERE user_id = ?",
        "logs": "SELECT * FROM daily_logs WHERE user_id = ?",
        "reminders": "SELECT * FROM reminders WHERE user_id = ?",
        "checker_results": "SELECT * FROM checker_results WHERE user_id = ?",
        "assistant_messages": "SELECT * FROM assistant_messages WHERE user_id = ?",
        "community_posts": "SELECT * FROM community_posts WHERE user_id = ?",
        "community_replies": "SELECT * FROM community_replies WHERE user_id = ?",
        "partner_links": "SELECT * FROM partner_links WHERE owner_id = ? OR partner_id = ?",
        "pregnancies": "SELECT * FROM pregnancies WHERE user_id = ?",
        "content_progress": "SELECT * FROM content_progress WHERE user_id = ?",
    }
    out: dict = {"account": auth.public_user(user), "billing": billing.status(uid)}
    for key, sql in tables.items():
        params = (uid, uid) if key == "partner_links" else (uid,)
        out[key] = [dict(r) for r in db.query(sql, params)]
    return out


@app.delete("/api/me")
def delete_me(response: Response, user: sqlite3.Row = Depends(current_user)) -> dict:
    auth.delete_user(user["id"])
    response.delete_cookie(COOKIE)
    return {"deleted": True, "message": "Every row belonging to this account has been removed."}


# --------------------------------------------------------------------------
# periods, logs, predictions, calendar


class PeriodIn(BaseModel):
    start_date: str
    end_date: str | None = None


class LogIn(BaseModel):
    date: str
    code: str
    value: float | None = None
    text: str | None = None


@app.get("/api/periods")
def list_periods(user: sqlite3.Row = Depends(current_user)) -> dict:
    rows = db.query(
        "SELECT id, start_date, end_date FROM period_events WHERE user_id = ?"
        " AND excluded = 0 ORDER BY start_date DESC",
        (user["id"],),
    )
    return {"periods": [dict(r) for r in rows], "cycles": cyc.history(user["id"])}


@app.post("/api/periods")
def add_period(payload: PeriodIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    try:
        start = cyc.to_date(payload.start_date)
        end = cyc.to_date(payload.end_date) if payload.end_date else None
    except ValueError as exc:
        raise HTTPException(400, detail={"error": "bad_date"}) from exc
    if end and end < start:
        raise HTTPException(400, detail={"error": "end_before_start"})
    db.execute(
        "INSERT INTO period_events (user_id, start_date, end_date) VALUES (?, ?, ?)"
        " ON CONFLICT(user_id, start_date) DO UPDATE SET end_date = excluded.end_date",
        (user["id"], cyc.iso(start), cyc.iso(end) if end else None),
    )
    return {"prediction": pr.predict(user["id"]).as_dict()}


@app.delete("/api/periods/{period_id}")
def delete_period(period_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    db.execute(
        "DELETE FROM period_events WHERE id = ? AND user_id = ?", (period_id, user["id"])
    )
    return {"deleted": True, "prediction": pr.predict(user["id"]).as_dict()}


@app.get("/api/prediction")
def read_prediction(user: sqlite3.Row = Depends(current_user)) -> dict:
    return pr.predict(user["id"]).as_dict()


@app.get("/api/calendar")
def read_calendar(
    start: str | None = None, days: int = 42, user: sqlite3.Row = Depends(current_user)
) -> dict:
    days = max(1, min(days, 400))
    first = cyc.to_date(start) if start else date.today().replace(day=1)
    return {"start": cyc.iso(first), "days": pr.upcoming_days(user["id"], first, days)}


@app.get("/api/log/catalog")
def log_catalog() -> dict:
    return sym.catalog_payload()


@app.get("/api/log/{log_date}")
def read_log(log_date: str, user: sqlite3.Row = Depends(current_user)) -> dict:
    return sym.day_log(user["id"], log_date)


@app.post("/api/log")
def write_log(payload: LogIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    try:
        sym.log_entry(user["id"], payload.date, payload.code, payload.value, payload.text)
    except sym.LogError as exc:
        raise HTTPException(400, detail={"error": "bad_code", "message": str(exc)}) from exc
    return sym.day_log(user["id"], payload.date)


@app.delete("/api/log")
def remove_log(payload: LogIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    sym.unlog_entry(user["id"], payload.date, payload.code)
    return sym.day_log(user["id"], payload.date)


# --------------------------------------------------------------------------
# billing


class PlanIn(BaseModel):
    plan: str


@app.get("/api/billing/status")
def billing_status(user: sqlite3.Row = Depends(current_user)) -> dict:
    return billing.status(user["id"])


@app.post("/api/billing/trial")
def billing_trial(user: sqlite3.Row = Depends(current_user)) -> dict:
    try:
        return billing.start_trial(user["id"])
    except billing.BillingError as exc:
        raise HTTPException(400, detail={"error": "trial_failed", "message": str(exc)}) from exc


@app.post("/api/billing/subscribe")
def billing_subscribe(payload: PlanIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    try:
        return billing.subscribe(user["id"], payload.plan)
    except billing.BillingError as exc:
        raise HTTPException(400, detail={"error": "plan_failed", "message": str(exc)}) from exc


@app.post("/api/billing/cancel")
def billing_cancel(user: sqlite3.Row = Depends(current_user)) -> dict:
    return billing.cancel(user["id"])


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "articles": len(content.articles()), "courses": len(content.courses())}


for module in (insights, reminders, patterns, checker, assistant, content,
               community, partner, pregnancy, ttc, report, importer):
    app.include_router(module.router)


# --------------------------------------------------------------------------
# PWA


@app.get("/manifest.json")
def manifest() -> JSONResponse:
    return JSONResponse({
        "name": "cycliq",
        "short_name": "cycliq",
        "start_url": "/",
        "display": "standalone",
        "background_color": "#FFF7FA",
        "theme_color": "#B4436C",
        "description": "Cycle, fertility and pregnancy tracking that keeps your data local.",
        "icons": [
            {"src": "/static/icon.svg", "sizes": "any", "type": "image/svg+xml",
             "purpose": "any maskable"}
        ],
    })


@app.get("/favicon.ico")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "icon.svg", media_type="image/svg+xml")


@app.get("/sw.js")
def service_worker() -> FileResponse:
    return FileResponse(STATIC_DIR / "sw.js", media_type="application/javascript")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def _lan_ip() -> str | None:
    """Best-effort local network address, for the startup banner only — never
    used for anything that affects behavior. Opens no real connection."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            return probe.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    import os

    import uvicorn

    db.init_db()
    # Default stays loopback-only so running this never silently exposes
    # health data to the network. Set CYCLIQ_HOST=0.0.0.0 to reach it from a
    # phone on the same WiFi — see README's "Use it on your phone" section.
    host = os.getenv("CYCLIQ_HOST", "127.0.0.1")
    port = int(os.getenv("CYCLIQ_PORT", "8103"))

    print(f"\ncycliq running at http://127.0.0.1:{port}")
    if host != "127.0.0.1":
        lan_ip = _lan_ip()
        if lan_ip:
            print(f"On your phone (same WiFi): http://{lan_ip}:{port}")
        else:
            print("Could not detect a LAN address — check your WiFi connection.")
    print()

    uvicorn.run(app, host=host, port=port, log_level="info")
