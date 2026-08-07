"""Shared FastAPI dependencies: the signed-in user and the premium gate."""

from __future__ import annotations

import sqlite3

from fastapi import Depends, HTTPException, Request

import auth
import billing

COOKIE = "cycliq_session"


def current_user(request: Request) -> sqlite3.Row:
    user = auth.user_from_token(request.cookies.get(COOKIE))
    if user is None:
        raise HTTPException(status_code=401, detail={"error": "auth_required"})
    return user


def optional_user(request: Request) -> sqlite3.Row | None:
    return auth.user_from_token(request.cookies.get(COOKIE))


def require_premium(feature: str):
    """Dependency factory. Returns 402 with an upsell body, never a bare 403,
    so the client can render a locked preview instead of an error page."""

    def _gate(user: sqlite3.Row = Depends(current_user)) -> sqlite3.Row:
        if not billing.is_premium(user["id"]):
            raise HTTPException(status_code=402, detail=billing.upsell(feature))
        return user

    return _gate
