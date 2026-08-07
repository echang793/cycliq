"""Turn logged period events into cycles, cycle days and phases.

A "cycle" is the interval between two consecutive period starts. Intervals that
are implausible as a single cycle (someone stopped logging for three months) are
excluded from the statistics rather than being allowed to poison them.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import db

MIN_CYCLE = 15   # shorter than this is almost always a double-logged period
MAX_CYCLE = 90   # longer than this is a gap in logging, not a real cycle
DEFAULT_CYCLE_LEN = 28
DEFAULT_PERIOD_LEN = 5

PHASES = ("menstrual", "follicular", "ovulatory", "luteal")


def to_date(value) -> date:
    if isinstance(value, date):
        return value
    return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()


def iso(value: date) -> str:
    return value.isoformat()


@dataclass(frozen=True)
class Period:
    start: date
    end: date | None

    @property
    def length(self) -> int | None:
        if self.end is None:
            return None
        return (self.end - self.start).days + 1


@dataclass(frozen=True)
class Cycle:
    start: date
    next_start: date
    period_len: int | None

    @property
    def length(self) -> int:
        return (self.next_start - self.start).days

    @property
    def usable(self) -> bool:
        return MIN_CYCLE <= self.length <= MAX_CYCLE


def list_periods(user_id: int) -> list[Period]:
    rows = db.query(
        "SELECT start_date, end_date FROM period_events"
        " WHERE user_id = ? AND excluded = 0 ORDER BY start_date",
        (user_id,),
    )
    return [
        Period(to_date(r["start_date"]), to_date(r["end_date"]) if r["end_date"] else None)
        for r in rows
    ]


def derive_cycles(periods: list[Period]) -> list[Cycle]:
    """Consecutive period starts become cycles. Implausible gaps are dropped."""
    cycles: list[Cycle] = []
    for current, following in zip(periods, periods[1:]):
        cycle = Cycle(current.start, following.start, current.length)
        if cycle.usable:
            cycles.append(cycle)
    return cycles


def period_lengths(periods: list[Period]) -> list[int]:
    return [p.length for p in periods if p.length and 1 <= p.length <= 14]


def typical_period_len(user_id: int, fallback: int | None = None) -> int:
    lengths = period_lengths(list_periods(user_id))
    if lengths:
        lengths.sort()
        return lengths[len(lengths) // 2]
    return fallback or DEFAULT_PERIOD_LEN


def last_period_start(user_id: int) -> date | None:
    row = db.query_one(
        "SELECT start_date FROM period_events WHERE user_id = ? AND excluded = 0"
        " ORDER BY start_date DESC LIMIT 1",
        (user_id,),
    )
    return to_date(row["start_date"]) if row else None


def cycle_day(today: date, start: date | None) -> int | None:
    """1-indexed day of the current cycle. None until a period is logged."""
    if start is None or today < start:
        return None
    return (today - start).days + 1


def phase_for_day(
    day: int,
    cycle_len: int,
    ovulation_day: int,
    period_len: int = DEFAULT_PERIOD_LEN,
) -> str:
    """Phase of a cycle day. Ovulatory covers the day of and day either side."""
    if day <= max(1, period_len):
        return "menstrual"
    if abs(day - ovulation_day) <= 1:
        return "ovulatory"
    if day < ovulation_day:
        return "follicular"
    return "luteal"


def phase_on(user_id: int, target: date, prediction=None) -> str | None:
    """Phase for an arbitrary date, using the cycle that date falls in."""
    periods = list_periods(user_id)
    if not periods:
        return None

    starts = [p.start for p in periods]
    enclosing = None
    for i, start in enumerate(starts):
        if start <= target:
            nxt = starts[i + 1] if i + 1 < len(starts) else None
            if nxt is None or target < nxt:
                enclosing = (start, nxt, periods[i].length)
                break
    if enclosing is None:
        return None

    start, nxt, plen = enclosing
    day = (target - start).days + 1
    if nxt is not None:
        cycle_len = (nxt - start).days
        if not (MIN_CYCLE <= cycle_len <= MAX_CYCLE):
            cycle_len = prediction.cycle_len if prediction else DEFAULT_CYCLE_LEN
        luteal = prediction.luteal_len if prediction else 14
    else:
        cycle_len = prediction.cycle_len if prediction else DEFAULT_CYCLE_LEN
        luteal = prediction.luteal_len if prediction else 14
        if day > cycle_len:
            return "luteal"

    return phase_for_day(day, cycle_len, max(1, cycle_len - luteal), plen or DEFAULT_PERIOD_LEN)


def history(user_id: int, limit: int = 12) -> list[dict]:
    """Recent completed cycles, newest first — the input to trends and reports."""
    cycles = derive_cycles(list_periods(user_id))
    out = [
        {
            "start": iso(c.start),
            "next_start": iso(c.next_start),
            "length": c.length,
            "period_len": c.period_len,
        }
        for c in cycles
    ]
    return list(reversed(out))[:limit]
