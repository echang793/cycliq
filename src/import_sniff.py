"""Parsers for exports whose schema we do not know: JSON and CSV.

Flo has no published export format — you request a copy through in-app support
and receive a password-protected JSON whose keys have changed over time. So
rather than hard-coding a mapping that will be wrong, this walks the document
for anything date-shaped, classifies the surrounding keys and values by name,
and *reports what it could not place* so the preview can show it. A guess that
announces itself is useful; a silent one is not.

The same machinery reads CSV, where every cell arrives as a string.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import timedelta
from typing import Any, Iterator

import cycle as cyc
import symptoms as sym
from import_staging import ImportError_, Staged, as_number, derive_starts, parse_day

PERIOD_KEY = re.compile(r"period|menstrua|bleed|cycle_start|cyclestart", re.I)
START_KEY = re.compile(r"start|begin|first|^date$|day", re.I)
DATE_KEY = re.compile(r"date|day|time|stamp", re.I)
# Keys whose value classifies the rest of the record rather than being data itself.
DISCRIMINATOR_KEY = re.compile(r"categor|type|kind|group|event|name|subtype", re.I)

# Words that appear in another app's value strings -> our codes.
VALUE_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"heavy", re.I), "flow_heavy"),
    (re.compile(r"medium|moderate|normal.*flow", re.I), "flow_medium"),
    (re.compile(r"light", re.I), "flow_light"),
    (re.compile(r"spot", re.I), "flow_spotting"),
    (re.compile(r"clot", re.I), "flow_clots"),
    (re.compile(r"cramp", re.I), "sym_cramps"),
    (re.compile(r"headache", re.I), "sym_headache"),
    (re.compile(r"migraine", re.I), "sym_migraine"),
    (re.compile(r"bloat", re.I), "sym_bloating"),
    (re.compile(r"tender.*breast|breast.*tender|sore.*breast", re.I), "sym_tender_breasts"),
    (re.compile(r"acne", re.I), "sym_acne"),
    (re.compile(r"fatigue|tired|exhaust", re.I), "sym_fatigue"),
    (re.compile(r"insomnia|sleepless", re.I), "sym_insomnia"),
    (re.compile(r"nausea", re.I), "sym_nausea"),
    (re.compile(r"backache|back.*pain", re.I), "sym_backache"),
    (re.compile(r"crav", re.I), "sym_cravings"),
    (re.compile(r"hot.*flash", re.I), "sym_hot_flashes"),
    (re.compile(r"night.*sweat", re.I), "sym_night_sweats"),
    (re.compile(r"dizz", re.I), "sym_dizziness"),
    (re.compile(r"diarrh", re.I), "sym_diarrhea"),
    (re.compile(r"constipat", re.I), "sym_constipation"),
    (re.compile(r"egg.?white", re.I), "dis_egg_white"),
    (re.compile(r"watery", re.I), "dis_watery"),
    (re.compile(r"creamy", re.I), "dis_creamy"),
    (re.compile(r"sticky", re.I), "dis_sticky"),
    (re.compile(r"dry|no.*discharge", re.I), "dis_none"),
    (re.compile(r"happy", re.I), "mood_happy"),
    (re.compile(r"calm", re.I), "mood_calm"),
    (re.compile(r"energetic", re.I), "mood_energetic"),
    (re.compile(r"irritab|angry", re.I), "mood_irritable"),
    (re.compile(r"mood.*swing|swing", re.I), "mood_swings"),
    (re.compile(r"anxious|anxiety", re.I), "mood_anxious"),
    (re.compile(r"^sad$|depress|low.*mood", re.I), "mood_sad"),
    (re.compile(r"apathetic", re.I), "mood_apathetic"),
    (re.compile(r"unprotected", re.I), "sex_unprotected"),
    (re.compile(r"protected", re.I), "sex_protected"),
    (re.compile(r"masturbat", re.I), "sex_masturbation"),
    (re.compile(r"high.*(drive|libido)", re.I), "sex_drive_high"),
    (re.compile(r"low.*(drive|libido)", re.I), "sex_drive_low"),
    (re.compile(r"ovulation.*(pos|surge|peak)|lh.*pos", re.I), "ovulation_test_pos"),
    (re.compile(r"ovulation.*neg|lh.*neg", re.I), "ovulation_test_neg"),
    (re.compile(r"pregnan.*pos", re.I), "pregnancy_test_pos"),
    (re.compile(r"pregnan.*neg", re.I), "pregnancy_test_neg"),
]

NUMERIC_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"basal|bbt|temperature|temp", re.I), "bbt"),
    (re.compile(r"weight|mass", re.I), "weight"),
    (re.compile(r"water|hydration", re.I), "water"),
    (re.compile(r"sleep", re.I), "sleep"),
    (re.compile(r"steps", re.I), "steps"),
]

CSV_DATE_COLUMNS = ("date", "day", "start_date", "start", "period_start", "log_date")


def match_value(text: str) -> str | None:
    if text in sym.CODE_TO_CATEGORY:  # already one of ours
        return text
    for pattern, code in VALUE_HINTS:
        if pattern.search(text):
            return code
    return None


def _walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            yield from _walk(value, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item, path)
    else:
        yield path, node


def _flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            out.extend(_flatten_strings(item))
        return out
    if isinstance(value, dict):
        out = []
        for key, item in value.items():
            for leaf in _flatten_strings(item):
                out.append(f"{key} {leaf}")
        return out
    return []


def _dict_records(node: Any) -> Iterator[dict]:
    """Every dict in the document that could plausibly be one day's record."""
    if isinstance(node, dict):
        if any(DATE_KEY.search(str(k)) for k in node):
            yield node
        for value in node.values():
            yield from _dict_records(value)
    elif isinstance(node, list):
        for item in node:
            yield from _dict_records(item)


def _record_day(record: dict) -> str | None:
    """The date this record is about. Prefer keys that look like a start date."""
    candidates = [(k, v) for k, v in record.items() if DATE_KEY.search(str(k))]
    candidates.sort(key=lambda kv: (0 if START_KEY.search(str(kv[0])) else 1, str(kv[0])))
    for _, value in candidates:
        day = parse_day(value)
        if day:
            return day
    # Some exports put the date in an unlabelled field.
    for value in record.values():
        day = parse_day(value)
        if day:
            return day
    return None


def _classify(key: Any, leaf: str, discriminators: list[str]) -> tuple[str | None, str | None]:
    """Returns (code, the discriminator that made it readable — if one was needed)."""
    if len(leaf) > 60:
        return None, None
    code = match_value(leaf) or match_value(f"{key} {leaf}")
    if code:
        return code, None
    for context in discriminators:
        if context == leaf:
            continue
        code = match_value(f"{context} {leaf}")
        if code:
            return code, context
    return None, None


def absorb_record(record: dict, staged: Staged) -> bool:
    day = _record_day(record)
    if day is None:
        return False

    # Exports routinely split the meaning across two fields —
    # {"category": "ovulation_test", "subtype": "Positive"} means nothing until
    # the two are read together. Collect the classifying fields up front so any
    # value in the record can be matched against them.
    discriminators = [
        v.strip()
        for k, v in record.items()
        if DISCRIMINATOR_KEY.search(str(k)) and isinstance(v, str) and 0 < len(v.strip()) < 40
    ]

    matched = False
    used_context: set[str] = set()
    pending_unknown: list[str] = []
    texts = [str(k) for k in record] + [
        leaf for value in record.values() for leaf in _flatten_strings(value)
    ]
    looks_like_period = any(PERIOD_KEY.search(t) for t in texts)

    for key, value in record.items():
        if DATE_KEY.search(str(key)) and parse_day(value):
            continue

        number = as_number(value)
        if number is not None:
            for pattern, code in NUMERIC_HINTS:
                if pattern.search(str(key)):
                    staged.log(day, code, number)
                    matched = True
                    break
            continue

        if isinstance(value, bool):
            if value and PERIOD_KEY.search(str(key)):
                staged.period_days.add(day)
                matched = True
            continue

        for leaf in _flatten_strings(value):
            code, context = _classify(key, leaf, discriminators)
            if code:
                staged.log(day, code)
                matched = True
                if context:
                    used_context.add(context)
                if code.startswith("flow_") and code != "flow_none":
                    staged.period_days.add(day)
            else:
                pending_unknown.append(f"unrecognised value: {key} = {leaf[:40]}")

    # A classifying field that was consumed to interpret a sibling ("category":
    # "ovulation_test" next to "subtype": "Positive") is not unrecognised data.
    # One that was never used is, and the preview has to say so.
    for reason in pending_unknown:
        if not any(reason.endswith(context) for context in used_context):
            staged.skipped[reason] += 1

    if looks_like_period and not matched:
        staged.period_days.add(day)
        staged.period_starts.add(day)
        matched = True
    return matched


def parse_json(raw: bytes) -> Staged:
    try:
        document = json.loads(raw.decode("utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        raise ImportError_(
            f"That file is not valid JSON ({exc.msg} at line {exc.lineno})."
        ) from exc

    # Our own export round-trips exactly; no guessing needed.
    if isinstance(document, dict) and "periods" in document and "logs" in document:
        return parse_cycliq_export(document)

    staged = Staged(source="json")
    absorbed = sum(1 for record in _dict_records(document) if absorb_record(record, staged))

    if not absorbed:
        keys = sorted({path for path, _ in _walk(document)})[:25]
        raise ImportError_(
            "Nothing date-shaped was recognised in that file. Top-level paths found: "
            + ", ".join(keys)
        )

    if not staged.period_starts:
        staged.period_starts = derive_starts(staged.period_days)
        if staged.period_days:
            staged.warnings.append(
                "Period starts were inferred from runs of bleeding days — the export "
                "did not label them explicitly."
            )
    staged.warnings.append(
        "This file's format is not documented, so the mapping is a best guess. "
        "Check the counts below against what you remember before applying."
    )
    return staged


def parse_cycliq_export(document: dict) -> Staged:
    staged = Staged(source="cycliq_export")
    for row in document.get("periods", []):
        day = parse_day(row.get("start_date"))
        if not day:
            continue
        staged.period_starts.add(day)
        staged.period_days.add(day)
        end = parse_day(row.get("end_date"))
        if end:
            cursor, last = cyc.to_date(day), cyc.to_date(end)
            while cursor <= last:
                staged.period_days.add(cursor.isoformat())
                cursor += timedelta(days=1)
    for row in document.get("logs", []):
        day = parse_day(row.get("log_date"))
        code = row.get("code")
        if day and code:
            staged.log(day, code, row.get("value"), row.get("text"))
    return staged


def parse_csv(raw: bytes) -> Staged:
    staged = Staged(source="csv")
    text = raw.decode("utf-8-sig", errors="replace")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise ImportError_("That CSV has no header row.")

    lowered = {name: (name or "").strip().lower() for name in reader.fieldnames}
    date_column = next(
        (name for name, low in lowered.items() if low in CSV_DATE_COLUMNS), None
    ) or next((name for name, low in lowered.items() if DATE_KEY.search(low)), None)
    if date_column is None:
        raise ImportError_("No date column found. Expected one of: " + ", ".join(CSV_DATE_COLUMNS))

    rows = 0
    for row in reader:
        day = parse_day(row.get(date_column))
        if day is None:
            staged.skipped["row with an unreadable date"] += 1
            continue
        rows += 1
        absorb_record({k: v for k, v in row.items() if v not in (None, "")}, staged)

    if not rows:
        raise ImportError_("No rows in that CSV had a readable date.")
    if not staged.period_starts:
        staged.period_starts = derive_starts(staged.period_days)
    return staged
