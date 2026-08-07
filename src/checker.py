"""Symptom Checker: PCOS, endometriosis and perimenopause.

These are *screeners*, not diagnostics. Each returns how closely the answers
match the pattern commonly reported with a condition, and every single result
ends at the same place: talk to a clinician. There is deliberately no
probability of disease anywhere in this file, and results are only stored when
the user explicitly consents.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import cycle as cyc
import db
import predict as pr
from deps import require_premium

router = APIRouter(prefix="/api/checker", tags=["checker"])

DISCLAIMER = (
    "This is an educational screener, not a diagnosis. It cannot rule a condition "
    "in or out. Only a clinician can do that, using an exam and tests."
)

STRONG, MODERATE = 0.60, 0.35


def _q(key: str, text: str, options: list[tuple[str, int]], prefill_from: str | None = None) -> dict:
    return {
        "key": key,
        "text": text,
        "options": [{"value": label, "score": score} for label, score in options],
        "prefill_from": prefill_from,
    }


TOOLS: dict[str, dict] = {
    "pcos": {
        "title": "PCOS pattern check",
        "blurb": "Polycystic ovary syndrome is usually considered when two of three "
                 "features are present: irregular or absent ovulation, signs of excess "
                 "androgens, and polycystic-appearing ovaries on ultrasound.",
        "questions": [
            _q("cycle_length", "How many days usually pass between your periods?",
               [("21-35 days", 0), ("36-90 days", 2), ("More than 90 days", 3),
                ("It varies a lot", 2)], prefill_from="cycle_length"),
            _q("missed", "In the last year, have you gone three months or more without a period?",
               [("No", 0), ("Once", 1), ("More than once", 2)]),
            _q("excess_hair", "Coarse dark hair growing on your face, chest or back?",
               [("No", 0), ("A little", 1), ("Noticeably", 2)]),
            _q("acne", "Persistent acne along the jaw, chin or back as an adult?",
               [("No", 0), ("Sometimes", 1), ("Persistently", 2)]),
            _q("hair_thinning", "Thinning hair at the crown or temples?",
               [("No", 0), ("Some", 1), ("Marked", 2)]),
            _q("weight", "Difficulty managing weight, especially around the middle?",
               [("No", 0), ("Some", 1)]),
            _q("skin_darkening", "Velvety darkened skin on the neck, armpits or groin?",
               [("No", 0), ("Yes", 2)]),
            _q("family", "PCOS or type 2 diabetes in a parent or sibling?",
               [("No or unsure", 0), ("Yes", 1)]),
            _q("ultrasound", "Has a scan ever shown polycystic-appearing ovaries?",
               [("No or never scanned", 0), ("Yes", 3)]),
            _q("conception", "Trying to conceive for over a year without success?",
               [("Not applicable", 0), ("No", 0), ("Yes", 2)]),
        ],
        # Rotterdam needs two of three features; without any ovulatory sign the
        # match cannot honestly be called strong.
        "gate": {"keys": ["cycle_length", "missed"], "message":
                 "Your cycles look regular, which makes PCOS less likely — the pattern "
                 "usually includes irregular or absent ovulation."},
    },
    "endometriosis": {
        "title": "Endometriosis pattern check",
        "blurb": "Endometriosis is tissue similar to the uterine lining growing outside "
                 "the uterus. Diagnosis is often delayed for years, so a strong match "
                 "here is a reason to push for a referral.",
        "questions": [
            _q("pain_severity", "How much does period pain interfere with your day?",
               [("Not at all", 0), ("Mildly", 1), ("A lot", 2),
                ("I miss work, school or plans", 3)]),
            _q("painkillers", "Do over-the-counter painkillers control the pain?",
               [("Not applicable", 0), ("Yes", 0), ("Partly", 1), ("No", 2)]),
            _q("pain_before", "Does the pain start days before the bleeding does?",
               [("No", 0), ("Yes", 2)]),
            _q("painful_sex", "Deep pain during or after sex?",
               [("No", 0), ("Sometimes", 1), ("Often", 2)]),
            _q("bowel", "Pain passing stool around your period?",
               [("No", 0), ("Sometimes", 1), ("Often", 2)]),
            _q("urinary", "Pain passing urine around your period?",
               [("No", 0), ("Yes", 1)]),
            _q("chronic_pelvic", "Pelvic pain on days you are not bleeding?",
               [("No", 0), ("Sometimes", 1), ("Often", 2)]),
            _q("heavy", "Heavy bleeding, or clots larger than a coin?",
               [("No", 0), ("Yes", 1)]),
            _q("bloating", "Severe bloating that comes and goes with your cycle?",
               [("No", 0), ("Yes", 1)]),
            _q("fatigue", "Fatigue that floors you around your period?",
               [("No", 0), ("Yes", 1)]),
            _q("family", "Endometriosis in a parent, sibling or child?",
               [("No or unsure", 0), ("Yes", 1)]),
            _q("conception", "Trying to conceive for over a year without success?",
               [("Not applicable", 0), ("No", 0), ("Yes", 2)]),
        ],
    },
    "perimenopause": {
        "title": "Perimenopause pattern check",
        "blurb": "Perimenopause is the transition before periods stop. The first sign is "
                 "usually a persistent change in cycle length, alongside symptoms driven "
                 "by fluctuating oestrogen.",
        "questions": [
            _q("age", "How old are you?",
               [("Under 35", 0), ("35-39", 1), ("40-44", 2), ("45-55", 3), ("Over 55", 2)],
               prefill_from="age"),
            _q("cycle_change", "Has your cycle length changed by a week or more, and stayed changed?",
               [("No", 0), ("Once or twice", 1), ("Yes, persistently", 3)],
               prefill_from="cycle_change"),
            _q("skipped", "Have you skipped two or more periods in a row this year?",
               [("No", 0), ("Yes", 3)], prefill_from="skipped"),
            _q("hot_flashes", "Hot flashes?",
               [("No", 0), ("Occasionally", 1), ("Frequently", 2)]),
            _q("night_sweats", "Night sweats?",
               [("No", 0), ("Occasionally", 1), ("Frequently", 2)]),
            _q("sleep", "New trouble falling or staying asleep?",
               [("No", 0), ("Yes", 2)]),
            _q("mood", "New irritability, low mood or anxiety?",
               [("No", 0), ("Yes", 1)]),
            _q("dryness", "Vaginal dryness or discomfort during sex?",
               [("No", 0), ("Yes", 2)]),
            _q("flow_change", "Has your flow become much heavier or much lighter?",
               [("No", 0), ("Yes", 1)]),
            _q("brain_fog", "Word-finding trouble or brain fog?",
               [("No", 0), ("Yes", 1)]),
        ],
        "gate": {"keys": ["cycle_change", "skipped"], "message":
                 "Your cycle length has not persistently changed, which is usually the "
                 "first sign of the transition."},
    },
}

# Answers that warrant a clinician regardless of the overall band.
RED_FLAGS = {
    ("endometriosis", "pain_severity", "I miss work, school or plans"):
        "Pain that stops you working or studying is not something to manage alone — ask for a referral.",
    ("endometriosis", "painkillers", "No"):
        "Period pain that over-the-counter painkillers do not touch should be assessed.",
    ("pcos", "cycle_length", "More than 90 days"):
        "Cycles longer than 90 days should be looked at, whatever the cause.",
    ("perimenopause", "flow_change", "Yes"):
        "A big change in flow is usually hormonal, but is worth ruling other causes out.",
}


def max_score(tool: str) -> int:
    return sum(max(o["score"] for o in q["options"]) for q in TOOLS[tool]["questions"])


def prefill(user_id: int, tool: str, today: date | None = None) -> dict:
    """Answer what the app already knows, so the user confirms rather than recalls."""
    today = today or date.today()
    out: dict[str, str] = {}
    prediction = pr.predict(user_id, today)
    cycles = cyc.derive_cycles(cyc.list_periods(user_id))
    user = db.query_one("SELECT birth_year FROM users WHERE id = ?", (user_id,))

    for question in TOOLS[tool]["questions"]:
        source = question["prefill_from"]
        if source == "cycle_length" and prediction.source == "history":
            if prediction.irregular:
                out[question["key"]] = "It varies a lot"
            elif prediction.cycle_len > 90:
                out[question["key"]] = "More than 90 days"
            elif prediction.cycle_len > 35:
                out[question["key"]] = "36-90 days"
            else:
                out[question["key"]] = "21-35 days"
        elif source == "age" and user and user["birth_year"]:
            age = today.year - int(user["birth_year"])
            for label, low, high in [("Under 35", 0, 34), ("35-39", 35, 39), ("40-44", 40, 44),
                                     ("45-55", 45, 55), ("Over 55", 56, 200)]:
                if low <= age <= high:
                    out[question["key"]] = label
                    break
        elif source == "cycle_change" and len(cycles) >= 4:
            recent = pr.median([float(c.length) for c in cycles[-3:]])
            older = pr.median([float(c.length) for c in cycles[:-3]])
            out[question["key"]] = "Yes, persistently" if abs(recent - older) >= 7 else "No"
        elif source == "skipped" and cycles:
            out[question["key"]] = "Yes" if any(c.length >= 60 for c in cycles[-6:]) else "No"
    return out


def score(tool: str, answers: dict[str, str]) -> dict:
    if tool not in TOOLS:
        raise KeyError(tool)
    spec = TOOLS[tool]
    total, answered, flags = 0, 0, []
    for question in spec["questions"]:
        choice = answers.get(question["key"])
        if choice is None:
            continue
        option = next((o for o in question["options"] if o["value"] == choice), None)
        if option is None:
            raise ValueError(f"'{choice}' is not an option for {question['key']}")
        total += option["score"]
        answered += 1
        flag = RED_FLAGS.get((tool, question["key"], choice))
        if flag:
            flags.append(flag)

    if answered < len(spec["questions"]):
        missing = len(spec["questions"]) - answered
        raise ValueError(f"{missing} question(s) still unanswered.")

    ratio = total / max_score(tool)
    band = "strong" if ratio >= STRONG else "moderate" if ratio >= MODERATE else "low"

    gate = spec.get("gate")
    gated = False
    if gate and band == "strong":
        if all(_score_of(tool, k, answers.get(k)) == 0 for k in gate["keys"]):
            band, gated = "moderate", True

    return {
        "tool": tool,
        "title": spec["title"],
        "band": band,
        "score": total,
        "max_score": max_score(tool),
        "ratio": round(ratio, 3),
        "headline": _headline(spec["title"], band),
        "explanation": _explanation(tool, band, gate["message"] if (gate and gated) else None),
        "red_flags": flags,
        "next_steps": _next_steps(band),
        "disclaimer": DISCLAIMER,
    }


def _score_of(tool: str, key: str, choice: str | None) -> int:
    if choice is None:
        return 0
    question = next((q for q in TOOLS[tool]["questions"] if q["key"] == key), None)
    if question is None:
        return 0
    option = next((o for o in question["options"] if o["value"] == choice), None)
    return option["score"] if option else 0


def _headline(title: str, band: str) -> str:
    return {
        "strong": "Your answers closely match the pattern people with this condition commonly report.",
        "moderate": "Your answers partly match the pattern people with this condition commonly report.",
        "low": "Your answers do not closely match the pattern people with this condition commonly report.",
    }[band]


def _explanation(tool: str, band: str, gate_message: str | None) -> str:
    parts = [TOOLS[tool]["blurb"]]
    if gate_message:
        parts.append(gate_message)
    if band == "low":
        parts.append(
            "A low match does not rule anything out — symptoms change, and this screener "
            "only sees what you told it today."
        )
    return " ".join(parts)


def _next_steps(band: str) -> list[str]:
    common = [
        "Bring your logged cycle and symptom history to the appointment — a six-month "
        "report is easier to act on than a description from memory.",
        "Write down when symptoms started and what makes them worse.",
    ]
    if band == "strong":
        return ["Book an appointment with a doctor or gynecologist and share this result.", *common]
    if band == "moderate":
        return ["Worth raising at your next appointment.", *common]
    return ["Keep logging. If symptoms change or worsen, retake this and see a clinician.", *common]


# --------------------------------------------------------------------------
# routes


class SubmitIn(BaseModel):
    answers: dict[str, str]
    save: bool = False


@router.get("/tools")
def list_tools(user: sqlite3.Row = Depends(require_premium("Symptom Checker"))) -> dict:
    return {
        "tools": [
            {"key": k, "title": v["title"], "blurb": v["blurb"], "questions": len(v["questions"])}
            for k, v in TOOLS.items()
        ],
        "disclaimer": DISCLAIMER,
    }


@router.get("/{tool}")
def read_tool(tool: str, user: sqlite3.Row = Depends(require_premium("Symptom Checker"))) -> dict:
    if tool not in TOOLS:
        raise HTTPException(404, detail={"error": "unknown_tool"})
    spec = TOOLS[tool]
    return {
        "tool": tool,
        "title": spec["title"],
        "blurb": spec["blurb"],
        "questions": [
            {"key": q["key"], "text": q["text"], "options": [o["value"] for o in q["options"]]}
            for q in spec["questions"]
        ],
        "prefill": prefill(user["id"], tool),
        "disclaimer": DISCLAIMER,
    }


@router.post("/{tool}")
def submit(tool: str, payload: SubmitIn,
           user: sqlite3.Row = Depends(require_premium("Symptom Checker"))) -> dict:
    if tool not in TOOLS:
        raise HTTPException(404, detail={"error": "unknown_tool"})
    try:
        result = score(tool, payload.answers)
    except ValueError as exc:
        raise HTTPException(400, detail={"error": "incomplete", "message": str(exc)}) from exc

    if payload.save:
        db.execute(
            "INSERT INTO checker_results (user_id, tool, band, score, answers, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (user["id"], tool, result["band"], result["score"],
             json.dumps(payload.answers), auth.now_iso()),
        )
    result["saved"] = payload.save
    return result


@router.get("/history/all")
def history(user: sqlite3.Row = Depends(require_premium("Symptom Checker"))) -> dict:
    rows = db.query(
        "SELECT id, tool, band, score, created_at FROM checker_results"
        " WHERE user_id = ? ORDER BY id DESC",
        (user["id"],),
    )
    return {"results": [dict(r) for r in rows]}
