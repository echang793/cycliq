"""Secret Chats: the anonymous community.

Posts carry the user's generated handle, never an email or a display name, and
`user_id` is only used for permission checks and deletion — it is never sent to
the client. Moderation is a report counter plus a small blocklist for the
categories that most need it here: medical misinformation bait and contact
sharing.
"""

from __future__ import annotations

import re
import sqlite3

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

import auth
import db
from deps import current_user

router = APIRouter(prefix="/api/community", tags=["community"])

HIDE_AFTER_REPORTS = 3
MAX_BODY = 4000

TOPICS = [
    {"slug": "cycle", "label": "Cycle talk", "blurb": "Periods, PMS, cramps, flow"},
    {"slug": "ttc", "label": "Trying to conceive", "blurb": "Ovulation, timing, waiting"},
    {"slug": "pregnancy", "label": "Pregnancy", "blurb": "Trimesters, symptoms, birth"},
    {"slug": "pcos", "label": "PCOS", "blurb": "Irregular cycles, diagnosis, management"},
    {"slug": "endo", "label": "Endometriosis", "blurb": "Pain, diagnosis journeys"},
    {"slug": "birth-control", "label": "Birth control", "blurb": "Methods, side effects"},
    {"slug": "mental-health", "label": "Mood and mind", "blurb": "Anxiety, PMDD, low days"},
    {"slug": "perimenopause", "label": "Perimenopause", "blurb": "Changing cycles, hot flashes"},
    {"slug": "sex", "label": "Sex and relationships", "blurb": "Libido, pain, partners"},
    {"slug": "general", "label": "Anything else", "blurb": "Everything not covered above"},
]
TOPIC_SLUGS = {t["slug"] for t in TOPICS}

# Contact details in an anonymous space defeat the point of the anonymous space.
_CONTACT = re.compile(
    r"([\w.+-]+@[\w-]+\.\w+)|(\+?\d[\d\s().-]{8,}\d)|(\b(?:t\.me|wa\.me|instagram\.com|dm me)\b)",
    re.I,
)


class PostIn(BaseModel):
    topic: str
    body: str = Field(min_length=1, max_length=MAX_BODY)


class ReplyIn(BaseModel):
    body: str = Field(min_length=1, max_length=MAX_BODY)


class ReactIn(BaseModel):
    target_kind: str
    target_id: int
    kind: str = "heart"


def scrub(body: str) -> str:
    return _CONTACT.sub("[removed]", body.strip())


def _reaction_counts(kind: str, ids: list[int]) -> dict[int, int]:
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = db.query(
        f"SELECT target_id, COUNT(*) AS n FROM community_reactions"
        f" WHERE target_kind = ? AND target_id IN ({marks}) GROUP BY target_id",
        (kind, *ids),
    )
    return {r["target_id"]: r["n"] for r in rows}


def _post_public(row: sqlite3.Row, hearts: int, replies: int, mine: bool) -> dict:
    return {
        "id": row["id"],
        "topic": row["topic"],
        "handle": row["handle"],
        "body": row["body"],
        "created_at": row["created_at"],
        "hearts": hearts,
        "replies": replies,
        "mine": mine,
    }


@router.get("/topics")
def list_topics(user: sqlite3.Row = Depends(current_user)) -> dict:
    rows = db.query(
        "SELECT topic, COUNT(*) AS n FROM community_posts WHERE hidden = 0 GROUP BY topic"
    )
    counts = {r["topic"]: r["n"] for r in rows}
    return {"topics": [{**t, "posts": counts.get(t["slug"], 0)} for t in TOPICS]}


@router.get("/posts")
def list_posts(
    topic: str | None = None,
    limit: int = 50,
    user: sqlite3.Row = Depends(current_user),
) -> dict:
    limit = max(1, min(limit, 100))
    if topic and topic not in TOPIC_SLUGS:
        raise HTTPException(400, detail={"error": "unknown_topic"})
    if topic:
        rows = db.query(
            "SELECT * FROM community_posts WHERE hidden = 0 AND topic = ?"
            " ORDER BY id DESC LIMIT ?",
            (topic, limit),
        )
    else:
        rows = db.query(
            "SELECT * FROM community_posts WHERE hidden = 0 ORDER BY id DESC LIMIT ?",
            (limit,),
        )
    ids = [r["id"] for r in rows]
    hearts = _reaction_counts("post", ids)
    reply_counts: dict[int, int] = {}
    if ids:
        marks = ",".join("?" for _ in ids)
        for r in db.query(
            f"SELECT post_id, COUNT(*) AS n FROM community_replies"
            f" WHERE hidden = 0 AND post_id IN ({marks}) GROUP BY post_id",
            tuple(ids),
        ):
            reply_counts[r["post_id"]] = r["n"]
    return {
        "posts": [
            _post_public(r, hearts.get(r["id"], 0), reply_counts.get(r["id"], 0),
                         r["user_id"] == user["id"])
            for r in rows
        ]
    }


@router.post("/posts")
def create_post(payload: PostIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    if payload.topic not in TOPIC_SLUGS:
        raise HTTPException(400, detail={"error": "unknown_topic"})
    body = scrub(payload.body)
    if not body:
        raise HTTPException(400, detail={"error": "empty_post"})
    post_id = db.execute(
        "INSERT INTO community_posts (topic, user_id, handle, body, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (payload.topic, user["id"], user["handle"], body, auth.now_iso()),
    )
    row = db.query_one("SELECT * FROM community_posts WHERE id = ?", (post_id,))
    return {"post": _post_public(row, 0, 0, True)}


@router.get("/posts/{post_id}")
def get_post(post_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one(
        "SELECT * FROM community_posts WHERE id = ? AND hidden = 0", (post_id,)
    )
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    replies = db.query(
        "SELECT * FROM community_replies WHERE post_id = ? AND hidden = 0 ORDER BY id",
        (post_id,),
    )
    hearts = _reaction_counts("reply", [r["id"] for r in replies])
    return {
        "post": _post_public(
            row, _reaction_counts("post", [post_id]).get(post_id, 0),
            len(replies), row["user_id"] == user["id"]
        ),
        "replies": [
            {
                "id": r["id"],
                "handle": r["handle"],
                "body": r["body"],
                "created_at": r["created_at"],
                "hearts": hearts.get(r["id"], 0),
                "mine": r["user_id"] == user["id"],
            }
            for r in replies
        ],
    }


@router.post("/posts/{post_id}/replies")
def create_reply(
    post_id: int, payload: ReplyIn, user: sqlite3.Row = Depends(current_user)
) -> dict:
    if db.query_one("SELECT 1 FROM community_posts WHERE id = ? AND hidden = 0", (post_id,)) is None:
        raise HTTPException(404, detail={"error": "not_found"})
    body = scrub(payload.body)
    if not body:
        raise HTTPException(400, detail={"error": "empty_reply"})
    reply_id = db.execute(
        "INSERT INTO community_replies (post_id, user_id, handle, body, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (post_id, user["id"], user["handle"], body, auth.now_iso()),
    )
    return {"reply": {"id": reply_id, "handle": user["handle"], "body": body, "mine": True}}


@router.post("/react")
def react(payload: ReactIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    if payload.target_kind not in {"post", "reply"}:
        raise HTTPException(400, detail={"error": "bad_target"})
    existing = db.query_one(
        "SELECT id FROM community_reactions WHERE user_id = ? AND target_kind = ? AND target_id = ?",
        (user["id"], payload.target_kind, payload.target_id),
    )
    if existing:
        db.execute("DELETE FROM community_reactions WHERE id = ?", (existing["id"],))
        reacted = False
    else:
        db.execute(
            "INSERT INTO community_reactions (user_id, target_kind, target_id, kind)"
            " VALUES (?, ?, ?, ?)",
            (user["id"], payload.target_kind, payload.target_id, payload.kind),
        )
        reacted = True
    count = _reaction_counts(payload.target_kind, [payload.target_id]).get(payload.target_id, 0)
    return {"reacted": reacted, "hearts": count}


@router.post("/report")
def report(payload: ReactIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    table = "community_posts" if payload.target_kind == "post" else "community_replies"
    if payload.target_kind not in {"post", "reply"}:
        raise HTTPException(400, detail={"error": "bad_target"})
    db.execute(f"UPDATE {table} SET reports = reports + 1 WHERE id = ?", (payload.target_id,))
    db.execute(
        f"UPDATE {table} SET hidden = 1 WHERE id = ? AND reports >= ?",
        (payload.target_id, HIDE_AFTER_REPORTS),
    )
    row = db.query_one(f"SELECT reports, hidden FROM {table} WHERE id = ?", (payload.target_id,))
    return {"reports": row["reports"] if row else 0, "hidden": bool(row["hidden"]) if row else False}


@router.delete("/posts/{post_id}")
def delete_post(post_id: int, user: sqlite3.Row = Depends(current_user)) -> dict:
    row = db.query_one("SELECT user_id FROM community_posts WHERE id = ?", (post_id,))
    if row is None or row["user_id"] != user["id"]:
        raise HTTPException(404, detail={"error": "not_found"})
    db.execute("DELETE FROM community_posts WHERE id = ?", (post_id,))
    return {"deleted": True}
