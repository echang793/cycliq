"""SQLite storage. Local file only, mode 0600, no cloud sync, no telemetry.

Every table that holds health data cascades on user delete so `DELETE /api/me`
is a real deletion and not a soft flag.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from pathlib import Path

_LOCAL = threading.local()


def db_path() -> Path:
    """Resolved at call time so tests can point CYCLIQ_DB at a temp file."""
    env = os.getenv("CYCLIQ_DB", "").strip()
    if env:
        return Path(env)
    return Path.home() / ".cycliq" / "cycliq.db"


def connect() -> sqlite3.Connection:
    """One connection per thread, per database path."""
    path = db_path()
    cached = getattr(_LOCAL, "conn", None)
    if cached is not None and getattr(_LOCAL, "path", None) == str(path):
        return cached
    if cached is not None:
        cached.close()

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    if path.exists():
        os.chmod(path, 0o600)

    _LOCAL.conn = conn
    _LOCAL.path = str(path)
    return conn


def close() -> None:
    conn = getattr(_LOCAL, "conn", None)
    if conn is not None:
        conn.close()
    _LOCAL.conn = None
    _LOCAL.path = None


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    handle          TEXT    NOT NULL UNIQUE,
    email           TEXT    UNIQUE,
    pw_hash         TEXT,
    pw_salt         TEXT,
    recovery_hash   TEXT,
    anonymous       INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT    NOT NULL,
    onboarded       INTEGER NOT NULL DEFAULT 0,
    mode            TEXT    NOT NULL DEFAULT 'cycle',
    goal            TEXT,
    birth_year      INTEGER,
    avg_cycle_len   INTEGER,
    avg_period_len  INTEGER
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);

CREATE TABLE IF NOT EXISTS entitlements (
    user_id       INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
    tier          TEXT NOT NULL DEFAULT 'free',
    plan          TEXT,
    trial_used    INTEGER NOT NULL DEFAULT 0,
    started_at    TEXT,
    expires_at    TEXT
);

-- One row per logged menstrual period. end_date NULL while still bleeding.
CREATE TABLE IF NOT EXISTS period_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    start_date  TEXT NOT NULL,
    end_date    TEXT,
    excluded    INTEGER NOT NULL DEFAULT 0,
    note        TEXT,
    UNIQUE(user_id, start_date)
);
CREATE INDEX IF NOT EXISTS idx_period_user ON period_events(user_id, start_date);

-- Everything else logged against a day: symptoms, mood, flow, BBT, LH, mucus,
-- weight, water, activity, sex, medication, free-text notes.
CREATE TABLE IF NOT EXISTS daily_logs (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    log_date    TEXT NOT NULL,
    category    TEXT NOT NULL,
    code        TEXT NOT NULL,
    value       REAL,
    text        TEXT,
    created_at  TEXT NOT NULL,
    UNIQUE(user_id, log_date, category, code)
);
CREATE INDEX IF NOT EXISTS idx_logs_user_date ON daily_logs(user_id, log_date);
CREATE INDEX IF NOT EXISTS idx_logs_user_code ON daily_logs(user_id, code);

CREATE TABLE IF NOT EXISTS reminders (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    kind         TEXT NOT NULL,
    label        TEXT,
    enabled      INTEGER NOT NULL DEFAULT 1,
    offset_days  INTEGER NOT NULL DEFAULT 0,
    time_of_day  TEXT NOT NULL DEFAULT '09:00',
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_reminders_user ON reminders(user_id);

-- Secret Chats: anonymous community. display_handle is per-post so a user's
-- posting identity is never their account handle.
CREATE TABLE IF NOT EXISTS community_posts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT NOT NULL,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    handle      TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    hidden      INTEGER NOT NULL DEFAULT 0,
    reports     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_posts_topic ON community_posts(topic, created_at);

CREATE TABLE IF NOT EXISTS community_replies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    post_id     INTEGER NOT NULL REFERENCES community_posts(id) ON DELETE CASCADE,
    user_id     INTEGER REFERENCES users(id) ON DELETE SET NULL,
    handle      TEXT NOT NULL,
    body        TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    hidden      INTEGER NOT NULL DEFAULT 0,
    reports     INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_replies_post ON community_replies(post_id, created_at);

CREATE TABLE IF NOT EXISTS community_reactions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    target_kind TEXT NOT NULL,
    target_id   INTEGER NOT NULL,
    kind        TEXT NOT NULL,
    UNIQUE(user_id, target_kind, target_id)
);

-- Partner Mode. scopes is a JSON array of share keys; basic tier is capped by
-- partner.BASIC_SCOPES regardless of what is stored here.
CREATE TABLE IF NOT EXISTS partner_links (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    owner_id    INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    partner_id  INTEGER REFERENCES users(id) ON DELETE CASCADE,
    invite_code TEXT NOT NULL UNIQUE,
    scopes      TEXT NOT NULL DEFAULT '[]',
    status      TEXT NOT NULL DEFAULT 'pending',
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_partner_owner ON partner_links(owner_id);
CREATE INDEX IF NOT EXISTS idx_partner_partner ON partner_links(partner_id);

CREATE TABLE IF NOT EXISTS checker_results (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    tool        TEXT NOT NULL,
    band        TEXT NOT NULL,
    score       REAL NOT NULL,
    answers     TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_checker_user ON checker_results(user_id, created_at);

CREATE TABLE IF NOT EXISTS content_progress (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    item_id      TEXT NOT NULL,
    lesson_slug  TEXT NOT NULL DEFAULT '',
    completed_at TEXT NOT NULL,
    PRIMARY KEY (user_id, item_id, lesson_slug)
);

CREATE TABLE IF NOT EXISTS assistant_messages (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role        TEXT NOT NULL,
    body        TEXT NOT NULL,
    backend     TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_assistant_user ON assistant_messages(user_id, id);

CREATE TABLE IF NOT EXISTS pregnancies (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    lmp_date    TEXT,
    due_date    TEXT NOT NULL,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_pregnancy_user ON pregnancies(user_id, active);

CREATE TABLE IF NOT EXISTS kick_sessions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    kicks       INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS contractions (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    started_at  TEXT NOT NULL,
    duration_s  REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_contractions_user ON contractions(user_id, started_at);

-- One row per quiz a user has answered: 'daily:YYYY-MM-DD' (answered once, final)
-- or 'lesson:<course>:<slug>' (best score kept).
CREATE TABLE IF NOT EXISTS quiz_results (
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    quiz_key     TEXT NOT NULL,
    score        INTEGER NOT NULL,
    total        INTEGER NOT NULL,
    answered_on  TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    PRIMARY KEY (user_id, quiz_key)
);
"""


def init_db() -> sqlite3.Connection:
    conn = connect()
    conn.executescript(SCHEMA)
    conn.commit()
    try:
        os.chmod(db_path(), 0o600)
    except OSError:
        pass
    return conn


def query(sql: str, params: tuple = ()) -> list[sqlite3.Row]:
    return connect().execute(sql, params).fetchall()


def query_one(sql: str, params: tuple = ()) -> sqlite3.Row | None:
    return connect().execute(sql, params).fetchone()


def execute(sql: str, params: tuple = ()) -> int:
    conn = connect()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid or 0
