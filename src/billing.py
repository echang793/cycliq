"""Subscription entitlements and the paywall.

Checkout is deliberately a stub: no card details are collected, handled or
stored anywhere in this app. `subscribe()` records an entitlement and nothing
else. Wiring a real processor would replace that one function.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import auth
import db

TRIAL_DAYS = 7

PLANS = {
    "monthly": {"label": "Monthly", "price_usd": 11.49, "days": 31},
    "annual": {"label": "Annual", "price_usd": 39.99, "days": 365, "note": "Best value"},
}

# Mirrors the free/premium split of the app being cloned.
FREE_FEATURES = [
    "Period and ovulation predictions",
    "90+ symptoms and events to track",
    "Custom reminders",
    "Secret Chats community",
    "Anonymous Mode",
    "Basic Partner Mode",
]

PREMIUM_FEATURES = [
    "Cycle patterns: which symptoms cluster in which phase",
    "Cycle trends and symptom predictions",
    "Symptom Checker for PCOS, endometriosis and perimenopause",
    "Unlimited Health Assistant chat",
    "Full article and course library",
    "Six-month report to share with a clinician",
    "Detailed pregnancy tracking",
    "Full Partner Mode sharing",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _row(user_id: int):
    row = db.query_one("SELECT * FROM entitlements WHERE user_id = ?", (user_id,))
    if row is None:
        db.execute("INSERT INTO entitlements (user_id, tier) VALUES (?, 'free')", (user_id,))
        row = db.query_one("SELECT * FROM entitlements WHERE user_id = ?", (user_id,))
    return row


def _active(row) -> bool:
    if row["tier"] == "free":
        return False
    if not row["expires_at"]:
        return False
    return datetime.fromisoformat(row["expires_at"]) > _now()


def is_premium(user_id: int) -> bool:
    return _active(_row(user_id))


def status(user_id: int) -> dict:
    row = _row(user_id)
    active = _active(row)
    return {
        "tier": row["tier"] if active else "free",
        "plan": row["plan"],
        "active": active,
        "trial_used": bool(row["trial_used"]),
        "expires_at": row["expires_at"] if active else None,
        "days_left": (
            (datetime.fromisoformat(row["expires_at"]) - _now()).days if active else 0
        ),
        "plans": PLANS,
        "free_features": FREE_FEATURES,
        "premium_features": PREMIUM_FEATURES,
    }


class BillingError(Exception):
    pass


def start_trial(user_id: int) -> dict:
    row = _row(user_id)
    if row["trial_used"]:
        raise BillingError("The free trial has already been used on this account.")
    if _active(row):
        raise BillingError("Premium is already active.")
    expires = _now() + timedelta(days=TRIAL_DAYS)
    db.execute(
        "UPDATE entitlements SET tier = 'premium', plan = 'trial', trial_used = 1,"
        " started_at = ?, expires_at = ? WHERE user_id = ?",
        (auth.now_iso(), expires.isoformat(timespec="seconds"), user_id),
    )
    return status(user_id)


def subscribe(user_id: int, plan: str) -> dict:
    if plan not in PLANS:
        raise BillingError(f"Unknown plan: {plan}")
    expires = _now() + timedelta(days=PLANS[plan]["days"])
    db.execute(
        "UPDATE entitlements SET tier = 'premium', plan = ?, started_at = ?,"
        " expires_at = ? WHERE user_id = ?",
        (plan, auth.now_iso(), expires.isoformat(timespec="seconds"), user_id),
    )
    return status(user_id)


def cancel(user_id: int) -> dict:
    db.execute(
        "UPDATE entitlements SET tier = 'free', plan = NULL, expires_at = NULL"
        " WHERE user_id = ?",
        (user_id,),
    )
    return status(user_id)


def upsell(feature: str) -> dict:
    """Body returned with a 402 so the UI can render a locked preview."""
    return {
        "error": "premium_required",
        "feature": feature,
        "message": f"{feature} is part of Premium.",
        "trial_days": TRIAL_DAYS,
        "plans": PLANS,
        "premium_features": PREMIUM_FEATURES,
    }
