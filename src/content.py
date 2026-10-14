"""The article and course library.

Content lives in `data/library.json` so it can be edited without touching code.
Everything in it is original writing with a named public source (ACOG, NHS,
NICHD, Mayo Clinic, WHO) for each piece — nothing is lifted from another app.

Free accounts get the articles flagged `free`; the rest of the library and all
courses are Premium, matching the tier split of the app being cloned.
"""

from __future__ import annotations

import json
import math
import sqlite3
from functools import lru_cache
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import billing
import db
from deps import current_user

router = APIRouter(prefix="/api/content", tags=["content"])

LIBRARY_PATH = Path(__file__).resolve().parent.parent / "data" / "library.json"

DISCLAIMER = (
    "Educational information, reviewed against public clinical guidance. "
    "It is not medical advice and cannot replace a clinician who knows your history."
)


@lru_cache(maxsize=1)
def library() -> dict:
    with LIBRARY_PATH.open() as handle:
        return json.load(handle)


def articles() -> list[dict]:
    return library()["articles"]


def courses() -> list[dict]:
    return library()["courses"]


def article_by_id(article_id: str) -> dict | None:
    return next((a for a in articles() if a["id"] == article_id), None)


def course_by_id(course_id: str) -> dict | None:
    return next((c for c in courses() if c["id"] == course_id), None)


def _card(item: dict, unlocked: bool) -> dict:
    """A locked card still shows title, blurb and read time — a blank wall sells
    nothing and tells the user nothing."""
    return {
        "id": item["id"],
        "title": item["title"],
        "blurb": item["blurb"],
        "category": item.get("category"),
        "minutes": item.get("minutes", 3),
        "tags": item.get("tags", []),
        "locked": not unlocked,
    }


def is_unlocked(item: dict, premium: bool) -> bool:
    return premium or bool(item.get("free"))


# Words that would match half the library and tell us nothing about intent.
# Found 2026-08-06: "before" was missing, so "why do I get bloating before my
# period" scored the sleep article (title-hits "period" *and* "before") over
# the PMS article that actually discusses bloating (a body-tier hit only,
# since "bloating" isn't in its title) — the connector outranked the symptom.
STOPWORDS = {
    "the", "and", "for", "with", "what", "why", "how", "does", "did", "get", "got",
    "can", "you", "your", "my", "me", "i", "is", "are", "was", "were", "a", "an",
    "of", "to", "in", "on", "it", "this", "that", "do", "have", "has", "about",
    "when", "should", "would", "there", "they", "them", "but", "not", "any", "so",
    "before", "after", "during", "while", "then", "than", "again",
}


def _tokens(text: str) -> list[str]:
    cleaned = "".join(c if c.isalnum() else " " for c in text.lower())
    return [t for t in cleaned.split() if len(t) > 2 and t not in STOPWORDS]


@lru_cache(maxsize=1)
def _token_document_frequency() -> dict[str, int]:
    """How many articles each token appears in anywhere. Backs the IDF
    weighting in `search` — found 2026-08-06: a flat per-tier score let
    "period" (in nearly every title, being a menstrual-cycle library) always
    outrank a specific symptom like "bloating" that only appears in one
    article's body, so "why do I get bloating before my period" surfaced an
    unrelated sleep article. A raw match count can't fix that; the fix is
    weighting a match by how much it actually narrows things down."""
    freq: dict[str, int] = {}
    for item in articles():
        haystack = " ".join(
            [item["title"], " ".join(item.get("tags", [])), item["blurb"], item["body"]]
        )
        for token in set(_tokens(haystack)):
            freq[token] = freq.get(token, 0) + 1
    return freq


def _idf(token: str) -> float:
    """Smoothed IDF: log((N+1)/(df+1)), floored just above zero. The +1s live
    inside the log only to dodge log(0) for a term in every single article —
    putting a +1 *outside* instead (an earlier version of this) put a high
    floor under common terms and defeated the point of weighting by rarity."""
    df = _token_document_frequency()
    n_docs = max(len(articles()), 1)
    count = df.get(token, 1)
    return max(math.log((n_docs + 1) / (count + 1)), 0.05)


def search(query: str, limit: int = 20) -> list[dict]:
    """Token search, not substring. A question like 'why do I get cramps on my
    period?' has to find the cramps article — the assistant is grounded on this.
    Matches are weighted by tier (title > tags > blurb > body) and by IDF, so a
    word that pins down one specific article outweighs one that is in every
    title in the library."""
    needles = _tokens(query)
    if not needles:
        return []
    weights = {token: _idf(token) for token in needles}

    scored: list[tuple[float, dict]] = []
    for item in articles():
        title = item["title"].lower()
        tags = " ".join(item.get("tags", [])).lower()
        blurb = item["blurb"].lower()
        body = item["body"].lower()
        score = 0.0
        for token in needles:
            tier = (
                5 if token in title else
                3 if token in tags else
                2 if token in blurb else
                1 if token in body else
                0
            )
            score += tier * weights[token]
        if score:
            scored.append((score, item))

    scored.sort(key=lambda pair: (-pair[0], pair[1]["id"]))
    return [item for _, item in scored[:limit]]


def snippets_for(query: str, limit: int = 3) -> list[dict]:
    """Grounding passages for the Health Assistant."""
    return [
        {"id": a["id"], "title": a["title"], "body": a["body"], "source": a.get("source", "")}
        for a in search(query, limit)
    ]


# --------------------------------------------------------------------------
# routes


class ProgressIn(BaseModel):
    item_id: str
    lesson_slug: str = ""


@router.get("/library")
def read_library(category: str | None = None, user: sqlite3.Row = Depends(current_user)) -> dict:
    premium = billing.is_premium(user["id"])
    items = articles()
    if category:
        items = [a for a in items if a.get("category") == category]
    cats = sorted({a.get("category", "General") for a in articles()})
    return {
        "categories": cats,
        "articles": [_card(a, is_unlocked(a, premium)) for a in items],
        "free_count": sum(1 for a in articles() if a.get("free")),
        "total": len(articles()),
        "premium": premium,
        "disclaimer": DISCLAIMER,
    }


@router.get("/search")
def read_search(q: str, user: sqlite3.Row = Depends(current_user)) -> dict:
    premium = billing.is_premium(user["id"])
    return {"results": [_card(a, is_unlocked(a, premium)) for a in search(q)]}


@router.get("/courses")
def read_courses(user: sqlite3.Row = Depends(current_user)) -> dict:
    premium = billing.is_premium(user["id"])
    done = {
        (r["item_id"], r["lesson_slug"])
        for r in db.query(
            "SELECT item_id, lesson_slug FROM content_progress WHERE user_id = ?", (user["id"],)
        )
    }
    out = []
    for course in courses():
        lessons = course["lessons"]
        completed = sum(1 for lesson in lessons if (course["id"], lesson["slug"]) in done)
        out.append({
            **_card(course, premium),
            "lessons": len(lessons),
            "completed": completed,
            "expert": course.get("expert"),
        })
    return {"courses": out, "premium": premium, "disclaimer": DISCLAIMER}


@router.get("/courses/{course_id}")
def read_course(course_id: str, user: sqlite3.Row = Depends(current_user)) -> dict:
    course = course_by_id(course_id)
    if course is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if not billing.is_premium(user["id"]):
        raise HTTPException(402, detail=billing.upsell("Courses and lesson quizzes"))
    done = {
        r["lesson_slug"]
        for r in db.query(
            "SELECT lesson_slug FROM content_progress WHERE user_id = ? AND item_id = ?",
            (user["id"], course_id),
        )
    }
    return {
        "course": {
            **course,
            "lessons": [{**lesson, "completed": lesson["slug"] in done} for lesson in course["lessons"]],
        },
        "disclaimer": DISCLAIMER,
    }


@router.get("/articles/{article_id}")
def read_article(article_id: str, user: sqlite3.Row = Depends(current_user)) -> dict:
    item = article_by_id(article_id)
    if item is None:
        raise HTTPException(404, detail={"error": "not_found"})
    if not is_unlocked(item, billing.is_premium(user["id"])):
        raise HTTPException(402, detail=billing.upsell("The full article library"))
    return {"article": item, "disclaimer": DISCLAIMER}


@router.post("/progress")
def mark_progress(payload: ProgressIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    if not billing.is_premium(user["id"]):
        raise HTTPException(402, detail=billing.upsell("Course progress"))
    db.execute(
        "INSERT OR REPLACE INTO content_progress (user_id, item_id, lesson_slug, completed_at)"
        " VALUES (?, ?, ?, ?)",
        (user["id"], payload.item_id, payload.lesson_slug, auth.now_iso()),
    )
    return {"saved": True}
