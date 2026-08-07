"""Health Assistant.

Three backends, tried in order, so the feature never hard-fails:

  1. Ollama on localhost — free, and health data never leaves the machine.
  2. Anthropic API — only if ANTHROPIC_API_KEY is set. Sent context is
     *aggregate only*: cycle day, phase, cycle length. No identifiers, no raw
     logs, no free-text notes.
  3. Deterministic retrieval over the local library — always available.

Every answer is grounded in the library articles and ends in the same place a
responsible health app has to: this is education, and a clinician is the one
who can diagnose.
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.error
import urllib.request
from datetime import date

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

import auth
import content
import db
import predict as pr
from deps import require_premium

router = APIRouter(prefix="/api/assistant", tags=["assistant"])

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6").strip()
HISTORY_TURNS = 8
TIMEOUT_S = 45

DISCLAIMER = (
    "I can explain how things generally work and what the guidance says, but I can't "
    "diagnose you or replace a clinician who knows your history."
)

SYSTEM_PROMPT = """You are the health assistant inside a menstrual and reproductive health app.

Rules you follow without exception:
- Educate, never diagnose. Do not estimate the probability that someone has a condition.
- Ground answers in the reference passages provided. If they do not cover the question,
  say what is generally known and be explicit that it is general.
- Name red flags plainly and tell the user to seek care when the situation warrants it:
  severe or worsening pain, heavy bleeding soaking a pad hourly, bleeding in pregnancy,
  fever with pelvic pain, reduced fetal movement, fainting, or thoughts of self-harm.
- Be concrete and brief. Three short paragraphs at most. No bullet-point lectures.
- Never moralise about sex, contraception, abortion, weight or lifestyle choices.
- The user's cycle context is aggregate. Do not invent details you were not given.
"""

URGENT_TERMS = {
    "suicide": "If you're thinking about harming yourself, please contact a crisis line or emergency services now. In the US you can call or text 988.",
    "kill myself": "If you're thinking about harming yourself, please contact a crisis line or emergency services now. In the US you can call or text 988.",
    "self harm": "If you're thinking about harming yourself, please contact a crisis line or emergency services now. In the US you can call or text 988.",
    "soaking a pad": "Bleeding that soaks a pad or tampon every hour for several hours needs urgent medical assessment.",
    "fainting": "Fainting with heavy bleeding or severe pain needs urgent medical assessment.",
    "no movement": "Reduced or absent fetal movement needs same-day contact with your midwife or maternity unit.",
    "not moving": "Reduced or absent fetal movement needs same-day contact with your midwife or maternity unit.",
}


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


def cycle_context(user_id: int, today: date | None = None) -> dict:
    """Aggregates only. Nothing here identifies a person."""
    prediction = pr.predict(user_id, today or date.today())
    return {
        "cycle_day": prediction.cycle_day,
        "phase": prediction.phase,
        "typical_cycle_length": prediction.cycle_len,
        "days_to_next_period": prediction.days_to_period,
        "cycles_logged": prediction.n_cycles,
        "cycles_irregular": prediction.irregular,
    }


def _history(user_id: int) -> list[dict]:
    rows = db.query(
        "SELECT role, body FROM assistant_messages WHERE user_id = ?"
        " ORDER BY id DESC LIMIT ?",
        (user_id, HISTORY_TURNS),
    )
    return [{"role": r["role"], "content": r["body"]} for r in reversed(rows)]


def _urgent_notes(message: str) -> list[str]:
    lowered = message.lower()
    return [note for term, note in URGENT_TERMS.items() if term in lowered]


def _prompt_context(passages: list[dict], context: dict) -> str:
    refs = "\n\n".join(f"[{p['title']}]\n{p['body']}" for p in passages) or "(no matching article)"
    return (
        f"Reference passages from the app's own library:\n{refs}\n\n"
        f"User's aggregate cycle context: {json.dumps(context)}"
    )


# --------------------------------------------------------------------------
# backend 1: Ollama (local, private)


def _ollama(message: str, passages: list[dict], context: dict, history: list[dict]) -> str | None:
    payload = {
        "model": OLLAMA_MODEL,
        "stream": False,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT + "\n\n" + _prompt_context(passages, context)},
            *history,
            {"role": "user", "content": message},
        ],
    }
    request = urllib.request.Request(
        f"{OLLAMA_URL}/api/chat",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_S) as response:
            body = json.loads(response.read())
        text = (body.get("message") or {}).get("content", "").strip()
        return text or None
    except (urllib.error.URLError, TimeoutError, OSError, ValueError, KeyError):
        return None


# --------------------------------------------------------------------------
# backend 2: Anthropic (cloud, opt-in via env, aggregates only)


def _anthropic(message: str, passages: list[dict], context: dict, history: list[dict]) -> str | None:
    if not ANTHROPIC_API_KEY:
        return None
    try:
        import anthropic  # imported lazily: the SDK is an optional dependency
    except ImportError:
        return None
    try:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
        response = client.messages.create(
            model=ANTHROPIC_MODEL,
            max_tokens=700,
            system=SYSTEM_PROMPT + "\n\n" + _prompt_context(passages, context),
            messages=[*history, {"role": "user", "content": message}],
        )
        parts = [block.text for block in response.content if getattr(block, "type", "") == "text"]
        text = "\n".join(parts).strip()
        return text or None
    except Exception:
        return None


# --------------------------------------------------------------------------
# backend 3: deterministic retrieval — always works, no model required


def _rules(message: str, passages: list[dict], context: dict) -> str:
    if not passages:
        return (
            "I don't have an article covering that in the library yet. "
            f"{DISCLAIMER} If the symptom is severe, sudden, or getting worse, "
            "treat that as a reason to be seen rather than to keep reading."
        )

    top = passages[0]
    paragraph = top["body"].split("\n\n")[0]
    lines = [f"Here's what the library says on {top['title'].lower()}:", "", paragraph]

    phase = context.get("phase")
    day = context.get("cycle_day")
    if phase and day:
        lines += ["", f"For context, you're on day {day} of your cycle, in the {phase} phase."]

    if len(passages) > 1:
        others = ", ".join(p["title"] for p in passages[1:])
        lines += ["", f"Related reading: {others}."]

    lines += ["", DISCLAIMER]
    return "\n".join(lines)


# --------------------------------------------------------------------------


def answer(user_id: int, message: str, today: date | None = None) -> dict:
    passages = content.snippets_for(message, limit=3)
    context = cycle_context(user_id, today)
    history = _history(user_id)

    text, backend = None, "rules"
    for name, fn in (("ollama", _ollama), ("anthropic", _anthropic)):
        text = fn(message, passages, context, history)
        if text:
            backend = name
            break
    if not text:
        text = _rules(message, passages, context)

    urgent = _urgent_notes(message)
    if urgent:
        text = "\n\n".join(["**" + urgent[0] + "**", text])

    return {
        "reply": text,
        "backend": backend,
        "sources": [{"id": p["id"], "title": p["title"]} for p in passages],
        "urgent": urgent,
        "disclaimer": DISCLAIMER,
    }


@router.get("/history")
def read_history(user: sqlite3.Row = Depends(require_premium("Health Assistant"))) -> dict:
    rows = db.query(
        "SELECT role, body, backend, created_at FROM assistant_messages"
        " WHERE user_id = ? ORDER BY id",
        (user["id"],),
    )
    return {"messages": [dict(r) for r in rows], "disclaimer": DISCLAIMER}


@router.post("/chat")
def chat(payload: ChatIn, user: sqlite3.Row = Depends(require_premium("Health Assistant"))) -> dict:
    result = answer(user["id"], payload.message)
    db.execute(
        "INSERT INTO assistant_messages (user_id, role, body, backend, created_at)"
        " VALUES (?, 'user', ?, NULL, ?)",
        (user["id"], payload.message, auth.now_iso()),
    )
    db.execute(
        "INSERT INTO assistant_messages (user_id, role, body, backend, created_at)"
        " VALUES (?, 'assistant', ?, ?, ?)",
        (user["id"], result["reply"], result["backend"], auth.now_iso()),
    )
    return result


@router.delete("/history")
def clear_history(user: sqlite3.Row = Depends(require_premium("Health Assistant"))) -> dict:
    db.execute("DELETE FROM assistant_messages WHERE user_id = ?", (user["id"],))
    return {"cleared": True}
