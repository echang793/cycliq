"""The six-month report to take to a clinician.

Appointments are short and symptoms are hard to recall accurately. This turns
the log into one page of dated facts: cycle lengths, bleeding pattern, and which
symptoms cluster in which phase — the things that change a clinical decision.
"""

from __future__ import annotations

import io
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

import cycle as cyc
import db
import patterns
import predict as pr
import symptoms as sym
from deps import require_premium

router = APIRouter(tags=["report"])

MONTHS = 6
ACCENT = colors.HexColor("#B4436C")
MUTED = colors.HexColor("#6B6470")

DISCLAIMER = (
    "This report summarises self-tracked data from a consumer app. It is not a medical "
    "record and has not been reviewed by a clinician. Dates are as entered by the user."
)


def gather(user_id: int, today: date | None = None, months: int = MONTHS) -> dict:
    today = today or date.today()
    since = today - timedelta(days=months * 31)

    periods = [p for p in cyc.list_periods(user_id) if p.start >= since]
    cycles = [c for c in cyc.derive_cycles(cyc.list_periods(user_id)) if c.start >= since]
    lengths = [float(c.length) for c in cycles]
    prediction = pr.predict(user_id, today)

    rows = db.query(
        "SELECT log_date, code FROM daily_logs WHERE user_id = ? AND log_date >= ?",
        (user_id, cyc.iso(since)),
    )
    counts: dict[str, int] = defaultdict(int)
    by_phase: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    logged_days: set[str] = set()
    for row in rows:
        code = row["code"]
        day = str(row["log_date"])[:10]
        logged_days.add(day)
        if code not in sym.PATTERN_CODES:
            continue
        counts[code] += 1
        phase = cyc.phase_on(user_id, cyc.to_date(day), prediction)
        if phase:
            by_phase[code][phase] += 1

    top = sorted(counts.items(), key=lambda kv: -kv[1])[:12]
    checkers = db.query(
        "SELECT tool, band, created_at FROM checker_results WHERE user_id = ? AND created_at >= ?"
        " ORDER BY id DESC",
        (user_id, cyc.iso(since)),
    )

    return {
        "generated": cyc.iso(today),
        "from": cyc.iso(since),
        "to": cyc.iso(today),
        "months": months,
        "periods": [
            {"start": cyc.iso(p.start), "end": cyc.iso(p.end) if p.end else None,
             "length": p.length}
            for p in periods
        ],
        "cycles": [
            {"start": cyc.iso(c.start), "length": c.length, "period_len": c.period_len}
            for c in cycles
        ],
        "median_cycle": round(pr.median(lengths), 1) if lengths else None,
        "shortest": int(min(lengths)) if lengths else None,
        "longest": int(max(lengths)) if lengths else None,
        "variability": round(pr.mad(lengths, pr.median(lengths)), 1) if lengths else None,
        "irregular": bool(lengths) and pr.mad(lengths, pr.median(lengths)) > pr.IRREGULAR_MAD,
        "median_period_len": cyc.typical_period_len(user_id),
        "logged_days": len(logged_days),
        "top_symptoms": [
            {
                "label": sym.CODE_LABELS.get(code, code),
                "count": count,
                "phases": dict(by_phase.get(code, {})),
            }
            for code, count in top
        ],
        "patterns": patterns.compute(user_id, today).get("patterns", [])[:6],
        "checkers": [dict(r) for r in checkers],
        "disclaimer": DISCLAIMER,
    }


def _styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle("t", parent=base["Title"], fontSize=18, textColor=ACCENT,
                                spaceAfter=2),
        "sub": ParagraphStyle("s", parent=base["Normal"], fontSize=9, textColor=MUTED,
                              spaceAfter=14),
        "h": ParagraphStyle("h", parent=base["Heading2"], fontSize=12, textColor=ACCENT,
                            spaceBefore=14, spaceAfter=6),
        "p": ParagraphStyle("p", parent=base["Normal"], fontSize=9.5, leading=13),
        "small": ParagraphStyle("sm", parent=base["Normal"], fontSize=8, textColor=MUTED,
                                leading=11),
    }


def _table(data: list[list[str]], widths: list[float]) -> Table:
    table = Table(data, colWidths=widths, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F6EDF1")),
        ("TEXTCOLOR", (0, 0), (-1, 0), ACCENT),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#E3D8DE")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return table


def build_pdf(user_id: int, handle: str, today: date | None = None) -> bytes:
    data = gather(user_id, today)
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=LETTER,
        leftMargin=0.75 * inch, rightMargin=0.75 * inch,
        topMargin=0.7 * inch, bottomMargin=0.7 * inch,
        title="Cycle and symptom report",
    )
    story: list = [
        Paragraph("Cycle and symptom report", styles["title"]),
        Paragraph(
            f"{data['months']} months · {data['from']} to {data['to']} · account {handle}",
            styles["sub"],
        ),
    ]

    story.append(Paragraph("Summary", styles["h"]))
    summary = [
        ["Cycles recorded", str(len(data["cycles"]))],
        ["Median cycle length", f"{data['median_cycle']} days" if data["median_cycle"] else "—"],
        ["Range", f"{data['shortest']}–{data['longest']} days" if data["shortest"] else "—"],
        ["Variability (MAD)", f"±{data['variability']} days" if data["variability"] is not None else "—"],
        ["Typical bleed length", f"{data['median_period_len']} days"],
        ["Days with entries", str(data["logged_days"])],
    ]
    if data["irregular"]:
        summary.append(["Flag", "Cycle length varies by more than 7 days"])
    story.append(_table([["Measure", "Value"], *summary], [2.6 * inch, 3.4 * inch]))

    story.append(Paragraph("Cycles", styles["h"]))
    if data["cycles"]:
        rows = [["Period start", "Cycle length", "Bleed length"]]
        for c in reversed(data["cycles"]):
            rows.append([c["start"], f"{c['length']} days",
                         f"{c['period_len']} days" if c["period_len"] else "—"])
        story.append(_table(rows, [2.0 * inch, 2.0 * inch, 2.0 * inch]))
    else:
        story.append(Paragraph("No complete cycles in this window.", styles["p"]))

    story.append(Paragraph("Most-logged symptoms", styles["h"]))
    if data["top_symptoms"]:
        rows = [["Symptom", "Days logged", "Distribution by phase"]]
        for item in data["top_symptoms"]:
            spread = ", ".join(f"{k}: {v}" for k, v in sorted(item["phases"].items())) or "—"
            rows.append([item["label"], str(item["count"]), spread])
        story.append(_table(rows, [2.0 * inch, 1.0 * inch, 3.0 * inch]))
    else:
        story.append(Paragraph("No symptoms logged in this window.", styles["p"]))

    if data["patterns"]:
        story.append(Paragraph("Phase associations", styles["h"]))
        for item in data["patterns"]:
            story.append(Paragraph("• " + item["sentence"], styles["p"]))
            story.append(Spacer(1, 3))

    if data["checkers"]:
        story.append(Paragraph("Screener results", styles["h"]))
        rows = [["Screener", "Match", "Date"]]
        for row in data["checkers"]:
            rows.append([row["tool"], row["band"], row["created_at"][:10]])
        story.append(_table(rows, [2.0 * inch, 2.0 * inch, 2.0 * inch]))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            "Screeners indicate symptom-pattern overlap only. They are not diagnostic.",
            styles["small"],
        ))

    story.append(Spacer(1, 16))
    story.append(Paragraph(DISCLAIMER, styles["small"]))

    doc.build(story)
    return buffer.getvalue()


@router.get("/api/report/preview")
def preview(user: sqlite3.Row = Depends(require_premium("Six-month report"))) -> dict:
    return gather(user["id"])


@router.get("/api/report.pdf")
def download(user: sqlite3.Row = Depends(require_premium("Six-month report"))) -> StreamingResponse:
    pdf = build_pdf(user["id"], user["handle"])
    return StreamingResponse(
        io.BytesIO(pdf),
        media_type="application/pdf",
        headers={"Content-Disposition": 'attachment; filename="cycle-report.pdf"'},
    )
