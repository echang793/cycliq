"""Quizzes: a free daily question and Premium lesson quizzes.

Every correct answer is a fact already stated in `data/library.json`, so a quiz
never teaches something the library does not. Answers are checked on the server
and are never sent to the client before a question is answered — otherwise the
"quiz" would be a lookup table in the page source.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import content
import cycle as cyc
import db
from deps import current_user, require_premium

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "quizzes.json"
PASS_RATIO = 0.7


@lru_cache(maxsize=1)
def load() -> dict:
    with DATA_PATH.open() as handle:
        return json.load(handle)


def daily_question(day: date) -> dict:
    """Same question for everyone on a given day, a different one each day."""
    pool = load()["daily"]
    return pool[day.toordinal() % len(pool)]


def lesson_questions(course_id: str, slug: str) -> list[dict]:
    return load()["lessons"].get(course_id, {}).get(slug, [])


def _public(question: dict) -> dict:
    return {"question": question["q"], "options": question["options"]}


# --------------------------------------------------------------------------
# storage


def record(user_id: int, key: str, score: int, total: int, on: date) -> None:
    """Daily keys are write-once. Lesson keys keep the best score."""
    if key.startswith("lesson:"):
        db.execute(
            "INSERT INTO quiz_results (user_id, quiz_key, score, total, answered_on, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)"
            " ON CONFLICT(user_id, quiz_key) DO UPDATE SET"
            "   score = MAX(score, excluded.score),"
            "   total = CASE WHEN excluded.score > score THEN excluded.total ELSE total END",
            (user_id, key, score, total, cyc.iso(on), auth.now_iso()),
        )
        return
    db.execute(
        "INSERT OR IGNORE INTO quiz_results (user_id, quiz_key, score, total, answered_on, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?)",
        (user_id, key, score, total, cyc.iso(on), auth.now_iso()),
    )


def _stored(user_id: int, key: str) -> sqlite3.Row | None:
    return db.query_one(
        "SELECT * FROM quiz_results WHERE user_id = ? AND quiz_key = ?", (user_id, key)
    )


def streak(user_id: int, today: date | None = None) -> int:
    """Consecutive days with a daily answer. A streak built through yesterday
    still counts until today is over, so opening the app in the morning does
    not show zero."""
    today = today or date.today()
    days = {
        r["answered_on"]
        for r in db.query(
            "SELECT answered_on FROM quiz_results WHERE user_id = ? AND quiz_key LIKE 'daily:%'",
            (user_id,),
        )
    }
    cursor = today if cyc.iso(today) in days else today - timedelta(days=1)
    count = 0
    while cyc.iso(cursor) in days:
        count += 1
        cursor -= timedelta(days=1)
    return count


# --------------------------------------------------------------------------
# daily quiz (free)


class ChoiceIn(BaseModel):
    choice: int


class AnswersIn(BaseModel):
    answers: list[int]


def _daily_key(day: date) -> str:
    return f"daily:{cyc.iso(day)}"


@router.get("/daily")
def read_daily(user: sqlite3.Row = Depends(current_user)) -> dict:
    today = date.today()
    question = daily_question(today)
    stored = _stored(user["id"], _daily_key(today))
    out = {**_public(question), "answered": stored is not None, "streak": streak(user["id"], today)}
    if stored is not None:
        out.update(
            correct=bool(stored["score"]),
            correct_index=question["answer"],
            explanation=question["explain"],
        )
    return out


@router.post("/daily/answer")
def answer_daily(payload: ChoiceIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    today = date.today()
    question = daily_question(today)
    if not 0 <= payload.choice < len(question["options"]):
        raise HTTPException(400, detail={"error": "bad_choice", "message": "Pick one of the options."})

    stored = _stored(user["id"], _daily_key(today))
    already = stored is not None
    correct = bool(stored["score"]) if already else payload.choice == question["answer"]
    if not already:
        record(user["id"], _daily_key(today), int(correct), 1, today)

    return {
        "correct": correct,
        "already_answered": already,
        "correct_index": question["answer"],
        "explanation": question["explain"],
        "streak": streak(user["id"], today),
    }


@router.get("/stats")
def read_stats(user: sqlite3.Row = Depends(current_user)) -> dict:
    rows = db.query(
        "SELECT quiz_key, score, total FROM quiz_results WHERE user_id = ?", (user["id"],)
    )
    daily = [r for r in rows if r["quiz_key"].startswith("daily:")]
    return {
        "streak": streak(user["id"]),
        "answered": len(daily),
        "correct": sum(r["score"] for r in daily),
        "lessons_passed": sum(
            1 for r in rows
            if r["quiz_key"].startswith("lesson:") and r["score"] >= PASS_RATIO * r["total"]
        ),
    }


# --------------------------------------------------------------------------
# lesson quizzes (Premium)


def _lesson_or_404(course_id: str, slug: str) -> list[dict]:
    course = content.course_by_id(course_id)
    questions = lesson_questions(course_id, slug)
    if course is None or not questions or slug not in {l["slug"] for l in course["lessons"]}:
        raise HTTPException(404, detail={"error": "not_found"})
    return questions


@router.get("/lessons/{course_id}/{slug}")
def read_lesson_quiz(
    course_id: str, slug: str,
    user: sqlite3.Row = Depends(require_premium("Lesson quizzes")),
) -> dict:
    questions = _lesson_or_404(course_id, slug)
    best = _stored(user["id"], f"lesson:{course_id}:{slug}")
    return {
        "questions": [_public(q) for q in questions],
        "best": {"score": best["score"], "total": best["total"]} if best else None,
        "pass_ratio": PASS_RATIO,
    }


@router.post("/lessons/{course_id}/{slug}")
def submit_lesson_quiz(
    course_id: str, slug: str, payload: AnswersIn,
    user: sqlite3.Row = Depends(require_premium("Lesson quizzes")),
) -> dict:
    questions = _lesson_or_404(course_id, slug)
    if len(payload.answers) != len(questions):
        raise HTTPException(400, detail={
            "error": "wrong_length",
            "message": f"Answer all {len(questions)} questions.",
        })
    for question, choice in zip(questions, payload.answers):
        if not 0 <= choice < len(question["options"]):
            raise HTTPException(400, detail={"error": "bad_choice", "message": "Pick one of the options."})

    results = [
        {
            "correct": choice == q["answer"],
            "correct_index": q["answer"],
            "explanation": q["explain"],
        }
        for q, choice in zip(questions, payload.answers)
    ]
    score = sum(1 for r in results if r["correct"])
    total = len(questions)
    passed = score >= PASS_RATIO * total

    record(user["id"], f"lesson:{course_id}:{slug}", score, total, date.today())
    if passed:
        db.execute(
            "INSERT OR REPLACE INTO content_progress (user_id, item_id, lesson_slug, completed_at)"
            " VALUES (?, ?, ?, ?)",
            (user["id"], course_id, slug, auth.now_iso()),
        )
    return {"score": score, "total": total, "passed": passed, "results": results}
