"""Cycle prediction.

Deliberately calendar-based and deliberately honest about it. Every output
carries an interval and a confidence, because a single predicted day is a claim
the data does not support: in a classic study only ~14% of people with 28-day
cycles ovulated on day 14 (mode day 16, range day 11-20). We therefore predict
a *window*, widen it when a user's cycles vary, and refine the luteal length
from that user's own BBT or LH data when they log it.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta

import cycle as cyc
import db

RECENCY_DECAY = 0.80    # weight of each older cycle relative to the next newer
MAX_CYCLES = 12         # older than this says little about the next cycle
LUTEAL_DEFAULT = 14
LUTEAL_MIN, LUTEAL_MAX = 10, 16
FERTILE_BEFORE = 5      # sperm survival
FERTILE_AFTER = 1       # oocyte lifespan
IRREGULAR_MAD = 7.0
IRREGULAR_SPREAD = 14.0  # shortest-to-longest gap that counts as irregular on its own
BBT_SHIFT_C = 0.20


@dataclass
class Prediction:
    cycle_len: int
    period_len: int
    luteal_len: int
    variability: float
    interval: int
    n_cycles: int
    source: str            # 'history' | 'profile' | 'default'
    confidence: str        # 'high' | 'medium' | 'low'
    irregular: bool
    last_period: str | None
    next_period: str | None
    next_period_low: str | None
    next_period_high: str | None
    period_end: str | None
    ovulation: str | None
    ovulation_low: str | None
    ovulation_high: str | None
    fertile_start: str | None
    fertile_end: str | None
    cycle_day: int | None
    phase: str | None
    days_to_period: int | None
    note: str

    def as_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------
# statistics


def median(values: list[float]) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def weighted_median(values: list[float], weights: list[float]) -> float:
    """Median of the weight distribution — robust to one outlier cycle."""
    if not values:
        return 0.0
    pairs = sorted(zip(values, weights))
    total = sum(weights)
    if total <= 0:
        return median(values)
    running = 0.0
    for value, weight in pairs:
        running += weight
        if running >= total / 2.0:
            return float(value)
    return float(pairs[-1][0])


def mad(values: list[float], center: float) -> float:
    """Median absolute deviation. Not stdev — one 45-day cycle shouldn't
    double the width of every future prediction."""
    if len(values) < 2:
        return 0.0
    return median([abs(v - center) for v in values])


def _weights(count: int) -> list[float]:
    """Oldest first, matching the order cycles are stored in."""
    return [RECENCY_DECAY ** (count - 1 - i) for i in range(count)]


# --------------------------------------------------------------------------
# luteal phase, refined from the user's own data


def _logged_series(user_id: int, code: str, start: date, end: date) -> list[tuple[date, float]]:
    rows = db.query(
        "SELECT log_date, value FROM daily_logs"
        " WHERE user_id = ? AND code = ? AND log_date >= ? AND log_date < ?"
        " ORDER BY log_date",
        (user_id, code, cyc.iso(start), cyc.iso(end)),
    )
    return [(cyc.to_date(r["log_date"]), float(r["value"])) for r in rows if r["value"] is not None]


def _bbt_shift_day(series: list[tuple[date, float]]) -> date | None:
    """First day whose 3-day mean clears the prior 6-day mean by BBT_SHIFT_C.
    Ovulation is taken as the day before that rise."""
    if len(series) < 9:
        return None
    temps = [t for _, t in series]
    for i in range(6, len(series) - 2):
        baseline = sum(temps[i - 6:i]) / 6.0
        post = sum(temps[i:i + 3]) / 3.0
        if post - baseline >= BBT_SHIFT_C:
            return series[i][0] - timedelta(days=1)
    return None


def ovulation_marker(user_id: int, start: date, end: date) -> date | None:
    """An observed ovulation day inside one cycle, if the user logged evidence.
    A positive LH test precedes ovulation by roughly a day."""
    lh = db.query_one(
        "SELECT log_date FROM daily_logs"
        " WHERE user_id = ? AND code = 'ovulation_test_pos'"
        " AND log_date >= ? AND log_date < ? ORDER BY log_date DESC LIMIT 1",
        (user_id, cyc.iso(start), cyc.iso(end)),
    )
    if lh:
        return cyc.to_date(lh["log_date"]) + timedelta(days=1)
    return _bbt_shift_day(_logged_series(user_id, "bbt", start, end))


def estimate_luteal(user_id: int, cycles: list[cyc.Cycle]) -> tuple[int, int]:
    """Median observed luteal length, clamped. Returns (length, n_observations)."""
    observed: list[float] = []
    for c in cycles:
        marker = ovulation_marker(user_id, c.start, c.next_start)
        if marker is None:
            continue
        luteal = (c.next_start - marker).days
        if LUTEAL_MIN <= luteal <= LUTEAL_MAX:
            observed.append(float(luteal))
    if not observed:
        return LUTEAL_DEFAULT, 0
    value = int(round(median(observed)))
    return max(LUTEAL_MIN, min(LUTEAL_MAX, value)), len(observed)


# --------------------------------------------------------------------------
# the prediction itself


def is_irregular(lengths: list[float], variability: float) -> bool:
    """MAD alone misses bimodal cycles — 23, 48, 25, 52, 22 has a small MAD but
    is plainly irregular — so the shortest-to-longest spread is checked too."""
    if len(lengths) < 2:
        return False
    spread = (max(lengths) - min(lengths)) if len(lengths) >= 3 else 0.0
    return variability > IRREGULAR_MAD or spread > IRREGULAR_SPREAD


def _confidence(n: int, variability: float, source: str, irregular: bool) -> str:
    if source != "history" or irregular:
        return "low"
    if n >= 6 and variability <= 2.0:
        return "high"
    if n >= 3 and variability <= 4.0:
        return "medium"
    return "low"


def predict(user_id: int, today: date | None = None) -> Prediction:
    today = today or date.today()
    user = db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))
    profile_len = (user["avg_cycle_len"] if user else None) or 0
    profile_period = (user["avg_period_len"] if user else None) or 0

    periods = cyc.list_periods(user_id)
    cycles = cyc.derive_cycles(periods)[-MAX_CYCLES:]
    lengths = [float(c.length) for c in cycles]

    if lengths:
        weights = _weights(len(lengths))
        center = weighted_median(lengths, weights)
        variability = mad(lengths, center)
        source = "history"
    elif profile_len:
        center, variability, source = float(profile_len), 3.0, "profile"
    else:
        center, variability, source = float(cyc.DEFAULT_CYCLE_LEN), 4.0, "default"

    cycle_len = int(round(center))
    interval = max(1, min(7, int(round(1.25 * variability)) if source == "history" else 3))
    irregular = source == "history" and is_irregular(lengths, variability)
    if irregular:
        interval = 7

    period_len = cyc.typical_period_len(user_id, profile_period or None)
    luteal_len, luteal_n = estimate_luteal(user_id, cycles)
    confidence = _confidence(len(lengths), variability, source, irregular)

    last = periods[-1].start if periods else None
    fields: dict = dict(
        last_period=cyc.iso(last) if last else None,
        next_period=None, next_period_low=None, next_period_high=None,
        period_end=None, ovulation=None, ovulation_low=None, ovulation_high=None,
        fertile_start=None, fertile_end=None, cycle_day=None, phase=None,
        days_to_period=None,
    )

    if last is not None:
        # Roll forward if the user is late or simply hasn't logged in a while,
        # so "day 63 of your cycle" never shows up on the Today screen.
        anchor = last
        while (today - anchor).days >= cycle_len + interval + 1:
            anchor = anchor + timedelta(days=cycle_len)
        next_period = anchor + timedelta(days=cycle_len)
        ovulation = next_period - timedelta(days=luteal_len)
        ov_slack = max(1, interval)

        fields.update(
            next_period=cyc.iso(next_period),
            next_period_low=cyc.iso(next_period - timedelta(days=interval)),
            next_period_high=cyc.iso(next_period + timedelta(days=interval)),
            period_end=cyc.iso(next_period + timedelta(days=period_len - 1)),
            ovulation=cyc.iso(ovulation),
            ovulation_low=cyc.iso(ovulation - timedelta(days=ov_slack)),
            ovulation_high=cyc.iso(ovulation + timedelta(days=ov_slack)),
            fertile_start=cyc.iso(ovulation - timedelta(days=FERTILE_BEFORE + (ov_slack - 1))),
            fertile_end=cyc.iso(ovulation + timedelta(days=FERTILE_AFTER + (ov_slack - 1))),
            cycle_day=cyc.cycle_day(today, anchor),
            days_to_period=(next_period - today).days,
        )
        day = fields["cycle_day"]
        if day:
            fields["phase"] = cyc.phase_for_day(
                day, cycle_len, max(1, cycle_len - luteal_len), period_len
            )

    return Prediction(
        cycle_len=cycle_len,
        period_len=period_len,
        luteal_len=luteal_len,
        variability=round(variability, 2),
        interval=interval,
        n_cycles=len(lengths),
        source=source,
        confidence=confidence,
        irregular=irregular,
        note=_note(source, confidence, irregular, len(lengths), luteal_n),
        **fields,
    )


def _note(source: str, confidence: str, irregular: bool, n: int, luteal_n: int) -> str:
    if source == "default":
        return "Using a 28-day placeholder. Log a period to get predictions from your own data."
    if source == "profile":
        return "Based on the cycle length you entered. Predictions sharpen after two logged periods."
    if irregular:
        return (
            "Your cycles vary a lot, so this is a wide window rather than a date. "
            "Cycle-length swings are common and have many causes — worth raising with a clinician if new."
        )
    parts = [f"Based on your last {n} cycle{'s' if n != 1 else ''}."]
    if luteal_n:
        parts.append(f"Luteal length measured from {luteal_n} of your own cycles.")
    else:
        parts.append("Ovulation assumes a 14-day luteal phase; log BBT or LH tests to measure yours.")
    if confidence == "low":
        parts.append("Confidence is low until more cycles are logged.")
    return " ".join(parts)


def upcoming_days(user_id: int, start: date, days: int) -> dict[str, dict]:
    """Day-by-day map for the calendar: logged period, predicted period,
    fertile window and ovulation, for `days` days from `start`."""
    pred = predict(user_id, start)
    logged: set[str] = set()
    for period in cyc.list_periods(user_id):
        end = period.end or period.start + timedelta(days=pred.period_len - 1)
        cursor = period.start
        while cursor <= end:
            logged.add(cyc.iso(cursor))
            cursor += timedelta(days=1)

    def span(a: str | None, b: str | None) -> set[str]:
        if not a or not b:
            return set()
        first, last = cyc.to_date(a), cyc.to_date(b)
        out, cursor = set(), first
        while cursor <= last:
            out.add(cyc.iso(cursor))
            cursor += timedelta(days=1)
        return out

    predicted = span(pred.next_period, pred.period_end)
    fertile = span(pred.fertile_start, pred.fertile_end)

    out: dict[str, dict] = {}
    for offset in range(days):
        d = cyc.iso(start + timedelta(days=offset))
        out[d] = {
            "logged_period": d in logged,
            "predicted_period": d in predicted and d not in logged,
            "fertile": d in fertile,
            "ovulation": d == pred.ovulation,
        }
    return out
