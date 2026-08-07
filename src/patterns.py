"""Premium analytics: which symptoms cluster in which phase, how cycles are
trending, and what to expect in the days ahead.

The whole file is one long argument against overclaiming. Every statistic has a
minimum-sample gate, lift is reported against the user's *own* baseline rather
than a population, and nothing is surfaced from fewer than two cycles of data.
"""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends

import cycle as cyc
import db
import predict as pr
import symptoms as sym
from deps import require_premium

router = APIRouter(prefix="/api/patterns", tags=["patterns"])

MIN_CYCLES = 2          # below this, "patterns" would be noise with a label
MIN_TOTAL_LOGS = 4      # times a symptom must appear at all
MIN_PHASE_LOGS = 2      # times it must appear in the phase being claimed
LIFT_THRESHOLD = 1.4    # how much more often than baseline before we say anything

PHASE_LABELS = {
    "menstrual": "your period",
    "follicular": "your follicular phase",
    "ovulatory": "your ovulation window",
    "luteal": "your luteal phase",
}


def _phase_index(user_id: int, prediction: pr.Prediction) -> dict[str, str]:
    """date -> phase, for every date the user has logged anything on."""
    rows = db.query(
        "SELECT DISTINCT log_date FROM daily_logs WHERE user_id = ? ORDER BY log_date",
        (user_id,),
    )
    index: dict[str, str] = {}
    for row in rows:
        day = cyc.to_date(row["log_date"])
        phase = cyc.phase_on(user_id, day, prediction)
        if phase:
            index[cyc.iso(day)] = phase
    return index


def compute(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    prediction = pr.predict(user_id, today)
    cycles = cyc.derive_cycles(cyc.list_periods(user_id))
    if len(cycles) < MIN_CYCLES:
        return {
            "ready": False,
            "cycles_logged": len(cycles),
            "cycles_needed": MIN_CYCLES,
            "message": (
                f"Patterns need at least {MIN_CYCLES} complete cycles of logging. "
                f"You have {len(cycles)}."
            ),
            "patterns": [],
        }

    phase_of = _phase_index(user_id, prediction)
    days_in_phase: dict[str, int] = defaultdict(int)
    for phase in phase_of.values():
        days_in_phase[phase] += 1
    total_days = sum(days_in_phase.values())
    if total_days == 0:
        return {"ready": False, "cycles_logged": len(cycles), "patterns": [],
                "message": "No logged days fall inside a completed cycle yet."}

    marks = ",".join("?" for _ in sym.PATTERN_CODES)
    rows = db.query(
        f"SELECT log_date, code FROM daily_logs WHERE user_id = ? AND code IN ({marks})",
        (user_id, *sym.PATTERN_CODES),
    )

    per_code: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    totals: dict[str, int] = defaultdict(int)
    for row in rows:
        phase = phase_of.get(str(row["log_date"])[:10])
        if phase is None:
            continue
        per_code[row["code"]][phase] += 1
        totals[row["code"]] += 1

    findings = []
    for code, by_phase in per_code.items():
        if totals[code] < MIN_TOTAL_LOGS:
            continue
        baseline = totals[code] / total_days
        for phase, count in by_phase.items():
            if count < MIN_PHASE_LOGS or days_in_phase[phase] == 0:
                continue
            rate = count / days_in_phase[phase]
            lift = rate / baseline if baseline else 0.0
            if lift < LIFT_THRESHOLD:
                continue
            findings.append({
                "code": code,
                "label": sym.CODE_LABELS.get(code, code),
                "phase": phase,
                "phase_label": PHASE_LABELS[phase],
                "lift": round(lift, 2),
                "occurrences": count,
                "phase_days": days_in_phase[phase],
                "rate_pct": round(100 * rate),
                "baseline_pct": round(100 * baseline),
                "sentence": (
                    f"You log {sym.CODE_LABELS.get(code, code).lower()} "
                    f"{lift:.1f}× more often during {PHASE_LABELS[phase]} "
                    f"than on an average logged day ({count} of {days_in_phase[phase]} days)."
                ),
                "strength": round(abs(lift - 1) * (count ** 0.5), 3),
            })

    findings.sort(key=lambda f: f["strength"], reverse=True)
    return {
        "ready": True,
        "cycles_logged": len(cycles),
        "logged_days": total_days,
        "days_in_phase": dict(days_in_phase),
        "patterns": findings[:20],
        "message": (
            "Associations in your own logs, not causes. A pattern here is a prompt to "
            "pay attention, not a diagnosis."
        ),
    }


def trends(user_id: int, limit: int = 12) -> dict:
    cycles = cyc.derive_cycles(cyc.list_periods(user_id))[-limit:]
    lengths = [float(c.length) for c in cycles]
    if not lengths:
        return {"ready": False, "cycles": [], "message": "No completed cycles logged yet."}

    center = pr.median(lengths)
    variability = pr.mad(lengths, center)
    direction = "steady"
    if len(lengths) >= 4:
        older = pr.median(lengths[: len(lengths) // 2])
        newer = pr.median(lengths[len(lengths) // 2:])
        if newer - older >= 2:
            direction = "lengthening"
        elif older - newer >= 2:
            direction = "shortening"

    return {
        "ready": True,
        "cycles": [
            {
                "start": cyc.iso(c.start),
                "length": c.length,
                "period_len": c.period_len,
                "typical": abs(c.length - center) <= max(2.0, variability),
            }
            for c in cycles
        ],
        "median_length": round(center, 1),
        "shortest": int(min(lengths)),
        "longest": int(max(lengths)),
        "variability": round(variability, 2),
        "direction": direction,
        "irregular": pr.is_irregular(lengths, variability),
        "message": _trend_message(direction, variability, len(lengths),
                                  pr.is_irregular(lengths, variability)),
    }


def _trend_message(direction: str, variability: float, n: int, irregular: bool) -> str:
    if irregular:
        return (
            f"Your cycle length varies by about {variability:.0f} days either side of typical. "
            "Persistent irregularity is worth a conversation with a clinician."
        )
    if direction == "lengthening":
        return f"Across your last {n} cycles the recent half runs longer than the earlier half."
    if direction == "shortening":
        return f"Across your last {n} cycles the recent half runs shorter than the earlier half."
    return f"Your last {n} cycles are consistent, varying by about {variability:.0f} days."


def forecast(user_id: int, today: date | None = None, days: int = 14) -> dict:
    """What the patterns imply for the days ahead — the 'symptom predictions'
    half of the premium tier."""
    today = today or date.today()
    prediction = pr.predict(user_id, today)
    found = compute(user_id, today)
    if not found.get("ready") or prediction.cycle_day is None:
        return {"ready": False, "days": [], "message": found.get("message", "Not enough data yet.")}

    by_phase: dict[str, list[dict]] = defaultdict(list)
    for item in found["patterns"]:
        by_phase[item["phase"]].append(item)

    ovulation_day = max(1, prediction.cycle_len - prediction.luteal_len)
    out = []
    for offset in range(days):
        day_date = today + timedelta(days=offset)
        day_num = prediction.cycle_day + offset
        while day_num > prediction.cycle_len:
            day_num -= prediction.cycle_len
        phase = cyc.phase_for_day(day_num, prediction.cycle_len, ovulation_day, prediction.period_len)
        likely = [
            {"label": p["label"], "lift": p["lift"], "rate_pct": p["rate_pct"]}
            for p in by_phase.get(phase, [])[:3]
        ]
        out.append({
            "date": cyc.iso(day_date),
            "cycle_day": day_num,
            "phase": phase,
            "likely": likely,
        })
    return {
        "ready": True,
        "days": out,
        "message": "Based on how often you logged each symptom in that phase before.",
    }


@router.get("")
def read_patterns(user: sqlite3.Row = Depends(require_premium("Cycle patterns"))) -> dict:
    return compute(user["id"])


@router.get("/trends")
def read_trends(user: sqlite3.Row = Depends(require_premium("Cycle trends"))) -> dict:
    return trends(user["id"])


@router.get("/forecast")
def read_forecast(user: sqlite3.Row = Depends(require_premium("Symptom predictions"))) -> dict:
    return forecast(user["id"])
