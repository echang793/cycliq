"""Every premium surface must return 402 with an upsell body for a free
account, and 200 once the trial starts. A blank page or a 500 is a bug."""

import pytest

import billing

PREMIUM_GET = [
    "/api/patterns",
    "/api/patterns/trends",
    "/api/patterns/forecast",
    "/api/checker/tools",
    "/api/checker/pcos",
    "/api/checker/endometriosis",
    "/api/checker/perimenopause",
    "/api/checker/history/all",
    "/api/assistant/history",
    "/api/report/preview",
    "/api/report.pdf",
    "/api/pregnancy/weeks",
    "/api/pregnancy/contractions",
]

FREE_GET = [
    "/api/prediction",
    "/api/calendar",
    "/api/insights/today",
    "/api/reminders",
    "/api/reminders/due",
    "/api/content/library",
    "/api/content/courses",
    "/api/community/topics",
    "/api/community/posts",
    "/api/partner/links",
    "/api/partner/scopes",
    "/api/ttc/window",
    "/api/ttc/chart",
    "/api/pregnancy/status",
]


@pytest.mark.parametrize("path", PREMIUM_GET)
def test_premium_routes_are_locked_for_free_accounts(signed_in, path):
    res = signed_in.get(path)
    assert res.status_code == 402, path
    detail = res.json()["detail"]
    assert detail["error"] == "premium_required"
    assert detail["feature"]
    assert detail["plans"]


@pytest.mark.parametrize("path", PREMIUM_GET)
def test_premium_routes_open_after_trial(premium, path):
    assert premium.get(path).status_code == 200, path


@pytest.mark.parametrize("path", FREE_GET)
def test_free_routes_stay_open(signed_in, path):
    assert signed_in.get(path).status_code == 200, path


def test_assistant_chat_is_gated(signed_in):
    res = signed_in.post("/api/assistant/chat", json={"message": "why do I get cramps?"})
    assert res.status_code == 402


def test_premium_routes_require_a_session(client):
    for path in PREMIUM_GET + FREE_GET:
        assert client.get(path).status_code == 401, path


def test_trial_can_only_be_used_once(signed_in):
    assert signed_in.post("/api/billing/trial").status_code == 200
    signed_in.post("/api/billing/cancel")
    assert signed_in.post("/api/billing/trial").status_code == 400


def test_cancel_revokes_access_immediately(premium):
    assert premium.get("/api/patterns").status_code == 200
    premium.post("/api/billing/cancel")
    assert premium.get("/api/patterns").status_code == 402


def test_subscribe_sets_expiry(signed_in):
    out = signed_in.post("/api/billing/subscribe", json={"plan": "annual"}).json()
    assert out["active"] and out["plan"] == "annual"
    assert out["days_left"] > 300
    assert signed_in.post("/api/billing/subscribe", json={"plan": "nope"}).status_code == 400


def test_expired_entitlement_reads_as_free(user_id):
    import db

    db.execute(
        "UPDATE entitlements SET tier = 'premium', plan = 'annual', expires_at = '2020-01-01T00:00:00+00:00'"
        " WHERE user_id = ?",
        (user_id,),
    )
    assert billing.is_premium(user_id) is False
    assert billing.status(user_id)["tier"] == "free"


def test_locked_content_returns_upsell_not_blank(signed_in):
    library = signed_in.get("/api/content/library").json()
    locked = next(a for a in library["articles"] if a["locked"])
    # A locked card still carries title and blurb so the UI can preview it.
    assert locked["title"] and locked["blurb"]
    res = signed_in.get(f"/api/content/articles/{locked['id']}")
    assert res.status_code == 402
    assert res.json()["detail"]["premium_features"]
