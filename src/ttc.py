"""Trying-to-conceive mode: the fertility chart and the fertile window.

The per-day probabilities are population estimates relative to ovulation day,
not a prediction about an individual cycle. They are here to make one point
concrete: the days *before* ovulation carry most of the chance, so timing sex
across the window beats aiming at a single date.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends

import cycle as cyc
import db
import predict as pr
from deps import current_user

router = APIRouter(prefix="/api/ttc", tags=["ttc"])

# Offset from ovulation day -> approximate probability of conception from a
# single act of intercourse on that day. Rounded from published cohort data.
DAY_PROBABILITY = {-5: 0.10, -4: 0.16, -3: 0.14, -2: 0.27, -1: 0.31, 0: 0.33, 1: 0.10}

MUCUS_ORDER = ["dis_none", "dis_sticky", "dis_creamy", "dis_watery", "dis_egg_white"]
MUCUS_FERTILITY = {
    "dis_none": 0, "dis_sticky": 1, "dis_creamy": 2, "dis_watery": 3, "dis_egg_white": 4,
}

NOTE = (
    "These are population averages, not your odds. Sex every one to two days across the "
    "window gives close to the maximum chance without needing to identify the right day."
)


def current_cycle_bounds(user_id: int, today: date | None = None) -> tuple[date, date]:
    today = today or date.today()
    prediction = pr.predict(user_id, today)
    start = cyc.last_period_start(user_id) or today - timedelta(days=prediction.cycle_len)
    while (today - start).days >= prediction.cycle_len * 2:
        start = start + timedelta(days=prediction.cycle_len)
    return start, today + timedelta(days=1)


def chart(user_id: int, today: date | None = None) -> dict:
    """Everything the fertility chart draws, for the current cycle."""
    today = today or date.today()
    start, end = current_cycle_bounds(user_id, today)
    prediction = pr.predict(user_id, today)

    rows = db.query(
        "SELECT log_date, code, value FROM daily_logs"
        " WHERE user_id = ? AND log_date >= ? AND log_date < ? ORDER BY log_date",
        (user_id, cyc.iso(start), cyc.iso(end)),
    )

    temps: dict[str, float] = {}
    mucus: dict[str, str] = {}
    lh: dict[str, str] = {}
    sex: dict[str, bool] = {}
    for row in rows:
        day = str(row["log_date"])[:10]
        code = row["code"]
        if code == "bbt" and row["value"] is not None:
            temps[day] = float(row["value"])
        elif code in MUCUS_FERTILITY:
            mucus[day] = code
        elif code in ("ovulation_test_pos", "ovulation_test_neg"):
            lh[day] = code
        elif code in ("sex_unprotected", "sex_protected"):
            sex[day] = code == "sex_unprotected"

    observed = pr.ovulation_marker(user_id, start, end)
    days = []
    cursor = start
    while cursor < end:
        key = cyc.iso(cursor)
        days.append({
            "date": key,
            "cycle_day": (cursor - start).days + 1,
            "bbt": temps.get(key),
            "mucus": mucus.get(key),
            "mucus_score": MUCUS_FERTILITY.get(mucus.get(key, ""), None),
            "lh": lh.get(key),
            "unprotected_sex": sex.get(key),
        })
        cursor += timedelta(days=1)

    return {
        "cycle_start": cyc.iso(start),
        "days": days,
        "observed_ovulation": cyc.iso(observed) if observed else None,
        "predicted_ovulation": prediction.ovulation,
        "luteal_len": prediction.luteal_len,
        "luteal_measured": observed is not None,
        "readings": len(temps),
        "note": (
            "A sustained temperature rise confirms ovulation after it happens. "
            "A positive LH test predicts it about a day ahead."
        ),
    }


def window(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    prediction = pr.predict(user_id, today)
    if not prediction.ovulation:
        return {
            "ready": False,
            "message": "Log a period to get a fertile window.",
            "days": [],
        }

    ovulation = cyc.to_date(prediction.ovulation)
    days = []
    for offset, probability in sorted(DAY_PROBABILITY.items()):
        day = ovulation + timedelta(days=offset)
        days.append({
            "date": cyc.iso(day),
            "offset": offset,
            "probability": probability,
            "label": (
                "Ovulation day" if offset == 0
                else f"{abs(offset)} day{'s' if abs(offset) != 1 else ''} "
                     f"{'before' if offset < 0 else 'after'} ovulation"
            ),
            "is_today": day == today,
        })

    in_window = any(d["is_today"] for d in days)
    peak = max(days, key=lambda d: d["probability"])
    return {
        "ready": True,
        "ovulation": prediction.ovulation,
        "ovulation_low": prediction.ovulation_low,
        "ovulation_high": prediction.ovulation_high,
        "fertile_start": prediction.fertile_start,
        "fertile_end": prediction.fertile_end,
        "in_window": in_window,
        "peak_date": peak["date"],
        "confidence": prediction.confidence,
        "irregular": prediction.irregular,
        "days": days,
        "note": NOTE,
    }


@router.get("/chart")
def read_chart(user: sqlite3.Row = Depends(current_user)) -> dict:
    return chart(user["id"])


@router.get("/window")
def read_window(user: sqlite3.Row = Depends(current_user)) -> dict:
    return window(user["id"])
