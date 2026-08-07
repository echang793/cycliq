"""Accounts, sessions, anonymous mode.

Handles are always machine-generated pseudonyms, never derived from the email,
so the community feed cannot be linked back to an identity by reading a name.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

import db

SESSION_DAYS = 90
_SCRYPT = dict(n=2**14, r=8, p=1, dklen=32)

_ADJECTIVES = [
    "quiet", "amber", "wild", "soft", "bright", "calm", "brave", "cedar",
    "lunar", "misty", "olive", "rapid", "sable", "tidal", "velvet", "warm",
]
_NOUNS = [
    "fern", "harbor", "willow", "otter", "meadow", "comet", "sparrow", "birch",
    "river", "ember", "orchid", "heron", "pebble", "aurora", "juniper", "wren",
]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def random_handle() -> str:
    return (
        f"{secrets.choice(_ADJECTIVES)}-{secrets.choice(_NOUNS)}-"
        f"{secrets.randbelow(900) + 100}"
    )


def _unique_handle() -> str:
    for _ in range(50):
        handle = random_handle()
        if db.query_one("SELECT 1 FROM users WHERE handle = ?", (handle,)) is None:
            return handle
    return f"member-{secrets.token_hex(4)}"


def hash_secret(secret: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.scrypt(secret.encode(), salt=salt.encode(), **_SCRYPT)
    return digest.hex(), salt


def verify_secret(secret: str, expected_hash: str, salt: str) -> bool:
    if not expected_hash or not salt:
        return False
    candidate, _ = hash_secret(secret, salt)
    return hmac.compare_digest(candidate, expected_hash)


# --------------------------------------------------------------------------
# users


class AuthError(Exception):
    """Raised for any credential problem; message is safe to show a user."""


def create_user(email: str, password: str) -> int:
    email = email.strip().lower()
    if not email or "@" not in email:
        raise AuthError("Enter a valid email address.")
    if len(password) < 8:
        raise AuthError("Password must be at least 8 characters.")
    if db.query_one("SELECT 1 FROM users WHERE email = ?", (email,)):
        raise AuthError("An account with that email already exists.")

    pw_hash, salt = hash_secret(password)
    user_id = db.execute(
        "INSERT INTO users (handle, email, pw_hash, pw_salt, anonymous, created_at)"
        " VALUES (?, ?, ?, ?, 0, ?)",
        (_unique_handle(), email, pw_hash, salt, now_iso()),
    )
    db.execute(
        "INSERT INTO entitlements (user_id, tier) VALUES (?, 'free')", (user_id,)
    )
    return user_id


def create_anonymous_user() -> tuple[int, str]:
    """No email, no name. A one-time recovery code is the only way back in."""
    code = "-".join(secrets.token_hex(2) for _ in range(3))
    code_hash, salt = hash_secret(code)
    user_id = db.execute(
        "INSERT INTO users (handle, pw_salt, recovery_hash, anonymous, created_at)"
        " VALUES (?, ?, ?, 1, ?)",
        (_unique_handle(), salt, code_hash, now_iso()),
    )
    db.execute(
        "INSERT INTO entitlements (user_id, tier) VALUES (?, 'free')", (user_id,)
    )
    return user_id, code


def login(email: str, password: str) -> sqlite3.Row:
    row = db.query_one("SELECT * FROM users WHERE email = ?", (email.strip().lower(),))
    if row is None or not verify_secret(password, row["pw_hash"] or "", row["pw_salt"] or ""):
        raise AuthError("Email or password is incorrect.")
    return row


def login_recovery(handle: str, code: str) -> sqlite3.Row:
    row = db.query_one("SELECT * FROM users WHERE handle = ?", (handle.strip(),))
    if row is None or not verify_secret(code, row["recovery_hash"] or "", row["pw_salt"] or ""):
        raise AuthError("Handle or recovery code is incorrect.")
    return row


def get_user(user_id: int) -> sqlite3.Row | None:
    return db.query_one("SELECT * FROM users WHERE id = ?", (user_id,))


def delete_user(user_id: int) -> None:
    """Hard delete. Foreign keys cascade every health table."""
    db.execute("DELETE FROM users WHERE id = ?", (user_id,))


# --------------------------------------------------------------------------
# sessions


def create_session(user_id: int) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(timezone.utc) + timedelta(days=SESSION_DAYS)
    db.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, now_iso(), expires.isoformat(timespec="seconds")),
    )
    return token


def user_from_token(token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    row = db.query_one(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id"
        " WHERE s.token = ? AND s.expires_at > ?",
        (token, now_iso()),
    )
    return row


def destroy_session(token: str | None) -> None:
    if token:
        db.execute("DELETE FROM sessions WHERE token = ?", (token,))


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "handle": row["handle"],
        "email": row["email"],
        "anonymous": bool(row["anonymous"]),
        "onboarded": bool(row["onboarded"]),
        "mode": row["mode"],
        "goal": row["goal"],
        "birth_year": row["birth_year"],
        "avg_cycle_len": row["avg_cycle_len"],
        "avg_period_len": row["avg_period_len"],
    }
