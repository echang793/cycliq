"""Import history from another tracking app.

Three routes in, because the one people ask for first is the worst supported:

1. **Apple Health export** (`export.xml`, or the `.zip` Health hands you). Best
   path. Flo and most other trackers write cycle data to HealthKit
   continuously, the identifiers are documented and stable, and you can export
   it yourself in two minutes. See `import_apple`.
2. **Flo's GDPR JSON.** Flo has no export button — you request a copy through
   in-app support and get a password-protected JSON by email, typically inside
   a month. Its schema is undocumented and has changed over time, so the parser
   sniffs rather than assumes and reports what it could not place. Decrypt the
   archive yourself first; this never takes a password. See `import_sniff`.
3. **CSV**, for hand-rolled exports and third-party converters.

Everything runs as a preview first. Nothing is written until the user looks at
what was found and confirms. Applying twice is safe: period starts and daily
logs both upsert on their natural keys.

This module is the façade — detection, writing, routes — and re-exports the
parser internals so callers and tests only need `importer`.
"""

from __future__ import annotations

import sqlite3
import zipfile
from xml.etree import ElementTree

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile

import auth
import cycle as cyc
import db
import import_apple
import import_sniff
import symptoms as sym
from deps import current_user
from import_apple import (  # noqa: F401  (re-exported for callers and tests)
    APPLE_ABSENT,
    APPLE_FLOW,
    APPLE_MUCUS,
    APPLE_OVULATION,
    APPLE_PREGNANCY,
    APPLE_SYMPTOMS,
)
from import_sniff import NUMERIC_HINTS, VALUE_HINTS  # noqa: F401  (re-exported)
from import_staging import ImportError_, Staged, derive_starts, parse_day  # noqa: F401

router = APIRouter(prefix="/api/import", tags=["import"])

MAX_UPLOAD_MB = 250

PARSERS = {
    "apple_health": import_apple.parse,
    "json": import_sniff.parse_json,
    "csv": import_sniff.parse_csv,
}


# --------------------------------------------------------------------------
# detection


def detect(raw: bytes, filename: str = "") -> str:
    head = raw[:400].lstrip()
    name = filename.lower()
    if raw[:2] == b"PK":
        return "apple_health"
    if head.startswith(b"<?xml") or head.startswith(b"<HealthData"):
        return "apple_health"
    if head[:1] in (b"{", b"["):
        return "json"
    if name.endswith(".csv") or b"," in head or b";" in head:
        return "csv"
    raise ImportError_(
        "Unrecognised file. Give me an Apple Health export (.zip or export.xml), "
        "a JSON export, or a CSV."
    )


def parse(raw: bytes, filename: str = "") -> Staged:
    kind = detect(raw, filename)
    try:
        return PARSERS[kind](raw)
    except ImportError_:
        raise
    except (ElementTree.ParseError, zipfile.BadZipFile, UnicodeDecodeError) as exc:
        raise ImportError_(f"That file could not be read as {kind}: {exc}") from exc


# --------------------------------------------------------------------------
# writing


def existing_counts(user_id: int) -> dict:
    return {
        "periods": len(cyc.list_periods(user_id)),
        "logs": db.query_one(
            "SELECT COUNT(*) AS n FROM daily_logs WHERE user_id = ?", (user_id,)
        )["n"],
    }


def apply(user_id: int, staged: Staged, period_len: int = 5) -> dict:
    """Write the staged data. Both tables upsert on their natural key, so
    importing the same file twice changes nothing the second time."""
    before = existing_counts(user_id)

    ends = _period_ends(staged)
    for start in sorted(staged.period_starts):
        db.execute(
            "INSERT INTO period_events (user_id, start_date, end_date) VALUES (?, ?, ?)"
            " ON CONFLICT(user_id, start_date) DO UPDATE SET end_date = excluded.end_date",
            (user_id, start, ends.get(start)),
        )

    for (day, code), (value, text) in sorted(staged.logs.items()):
        db.execute(
            "INSERT INTO daily_logs (user_id, log_date, category, code, value, text, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id, log_date, category, code)"
            " DO UPDATE SET value = excluded.value, text = excluded.text",
            (user_id, day, sym.CODE_TO_CATEGORY[code], code, value, text, auth.now_iso()),
        )

    after = existing_counts(user_id)
    return {
        "imported": True,
        "periods_added": after["periods"] - before["periods"],
        "logs_added": after["logs"] - before["logs"],
        "periods_total": after["periods"],
        "logs_total": after["logs"],
    }


def _period_ends(staged: Staged) -> dict[str, str | None]:
    """Last bleeding day of each run, so imported periods carry a length."""
    if not staged.period_days:
        return {}
    days = sorted(cyc.to_date(d) for d in staged.period_days)
    ends: dict[str, str | None] = {}
    for start_iso in staged.period_starts:
        start = cyc.to_date(start_iso)
        cursor = last = start
        for day in days:
            if day < start:
                continue
            if (day - cursor).days > 2:
                break
            cursor = last = day
        ends[start_iso] = last.isoformat() if last != start else None
    return ends


# --------------------------------------------------------------------------
# routes


# Staged results waiting on a confirmation, keyed by user. In memory on purpose:
# a rejected import should leave no trace on disk.
_PENDING: dict[int, Staged] = {}


async def _read(upload: UploadFile) -> bytes:
    raw = await upload.read()
    if len(raw) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, detail={
            "error": "too_large",
            "message": f"That file is over {MAX_UPLOAD_MB} MB.",
        })
    if not raw:
        raise HTTPException(400, detail={"error": "empty", "message": "That file is empty."})
    return raw


def _parse_or_400(raw: bytes, filename: str) -> Staged:
    try:
        return parse(raw, filename)
    except ImportError_ as exc:
        raise HTTPException(400, detail={"error": "parse_failed", "message": str(exc)}) from exc


@router.get("/guide")
def guide() -> dict:
    """How to get an export out of each app. Rendered in the import sheet."""
    return {
        "sources": [
            {
                "key": "apple_health",
                "title": "Apple Health (recommended)",
                "why": "Flo writes cycle data to Health continuously, the format is "
                       "documented, and you can export it yourself in two minutes.",
                "steps": [
                    "Health app → your photo, top right → Export All Health Data",
                    "Save the zip, then upload it here (no need to unzip it)",
                ],
                "brings": "Period dates and flow, symptoms, cervical mucus, LH and "
                          "pregnancy tests, basal body temperature, weight, sexual activity.",
            },
            {
                "key": "flo_json",
                "title": "Flo's own export",
                "why": "Flo has no export button. You request a copy through in-app "
                       "support and it arrives by email, usually within a month.",
                "steps": [
                    "In Flo: avatar → Help → Contact us → ask for a data export",
                    "You get two emails: the archive, and its password",
                    "Unlock the archive yourself, then upload the JSON here",
                ],
                "caveat": "Flo's schema is undocumented, so this app has to guess at the "
                          "mapping. The preview shows exactly what was recognised and what "
                          "was skipped — check it before applying.",
                "brings": "Whatever the export contains that can be matched by name.",
            },
            {
                "key": "csv",
                "title": "CSV",
                "why": "For hand-made exports and third-party converters.",
                "steps": [
                    "One row per day, a date column, and one column per thing tracked",
                ],
                "brings": "Anything whose column or value name matches a tracked item.",
            },
        ],
        "notes": [
            "Nothing is written until you confirm the preview.",
            "Importing the same file twice is safe — entries upsert on date and type.",
            "The file is parsed in memory on this machine and never uploaded anywhere.",
        ],
    }


@router.post("/preview")
async def preview(
    file: UploadFile = File(...), user: sqlite3.Row = Depends(current_user)
) -> dict:
    raw = await _read(file)
    staged = _parse_or_400(raw, file.filename or "")
    _PENDING[user["id"]] = staged
    return {
        "preview": staged.summary(),
        "existing": existing_counts(user["id"]),
        "filename": file.filename,
        "bytes": len(raw),
    }


@router.post("/apply")
def apply_pending(user: sqlite3.Row = Depends(current_user)) -> dict:
    staged = _PENDING.pop(user["id"], None)
    if staged is None:
        raise HTTPException(400, detail={
            "error": "nothing_staged",
            "message": "Upload a file for preview first.",
        })
    result = apply(user["id"], staged)
    result["source"] = staged.source
    return result


@router.post("/upload")
async def upload_and_apply(
    file: UploadFile = File(...),
    confirm: bool = Form(False),
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    """One-shot for scripts. `confirm=false` previews without writing."""
    raw = await _read(file)
    staged = _parse_or_400(raw, file.filename or "")
    if not confirm:
        return {"preview": staged.summary(), "applied": False}
    return {"preview": staged.summary(), "applied": True, **apply(user["id"], staged)}
