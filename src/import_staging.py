"""Shared pieces of the import pipeline: what a parser produces, and dates.

Split out from `importer` so the three format parsers can depend on it without
importing each other. `importer` re-exports everything here, so callers only
ever need that one module.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import cycle as cyc
import symptoms as sym

MIN_YEAR, MAX_YEAR = 1990, 2100


class ImportError_(Exception):
    """Input we cannot parse at all. The message is shown to the user."""


@dataclass
class Staged:
    """Parsed, not yet written. Every parser produces one of these, and nothing
    reaches the database until the user has seen its summary."""

    period_starts: set[str] = field(default_factory=set)
    period_days: set[str] = field(default_factory=set)
    # (log_date, code) -> (value, text)
    logs: dict[tuple[str, str], tuple[float | None, str | None]] = field(default_factory=dict)
    skipped: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    source: str = "unknown"

    def log(self, day: str, code: str, value: float | None = None, text: str | None = None) -> None:
        if code not in sym.CODE_TO_CATEGORY:
            self.skipped[f"unmapped code: {code}"] += 1
            return
        self.logs[(day, code)] = (value, text)

    def summary(self) -> dict:
        by_code = Counter(code for _, code in self.logs)
        days = {day for day, _ in self.logs} | self.period_days
        return {
            "source": self.source,
            "period_starts": sorted(self.period_starts),
            "period_start_count": len(self.period_starts),
            "period_days": len(self.period_days),
            "log_entries": len(self.logs),
            "logged_days": len(days),
            "date_range": [min(days), max(days)] if days else None,
            "by_symptom": [
                {"code": code, "label": sym.CODE_LABELS.get(code, code), "count": n}
                for code, n in by_code.most_common(40)
            ],
            "skipped": [{"reason": k, "count": v} for k, v in self.skipped.most_common(20)],
            "warnings": self.warnings,
        }


_EPOCH_RE = re.compile(r"^\d{10}(\d{3})?$")


def parse_day(value: Any) -> str | None:
    """Accept ISO strings, Apple's '2026-03-04 08:12:00 +0000', epoch seconds
    and epoch milliseconds. Returns YYYY-MM-DD, or None if it isn't a date."""
    if value is None or isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds > 1e11:  # milliseconds
            seconds /= 1000.0
        if not 6e8 < seconds < 4e9:
            return None
        try:
            return datetime.fromtimestamp(seconds, timezone.utc).date().isoformat()
        except (OverflowError, OSError, ValueError):
            return None

    text = str(value).strip()
    if not text:
        return None
    if _EPOCH_RE.match(text):
        return parse_day(int(text))

    try:
        parsed = datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y", "%Y/%m/%d"):
            try:
                parsed = datetime.strptime(text[:10], fmt).date()
                break
            except ValueError:
                continue
        else:
            return None
    if not MIN_YEAR <= parsed.year <= MAX_YEAR:
        return None
    return parsed.isoformat()


def as_number(value: Any) -> float | None:
    """CSV gives every cell as a string, so numbers have to be recovered."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return None


def derive_starts(days: set[str], gap: int = 2) -> set[str]:
    """First day of each run of bleeding days. A break of more than `gap` days
    starts a new period."""
    if not days:
        return set()
    ordered = sorted(cyc.to_date(d) for d in days)
    starts = {ordered[0]}
    for previous, current in zip(ordered, ordered[1:]):
        if (current - previous).days > gap:
            starts.add(current)
    return {d.isoformat() for d in starts}
