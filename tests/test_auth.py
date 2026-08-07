import pytest

import auth
import db


def test_password_round_trip():
    digest, salt = auth.hash_secret("correct horse battery")
    assert auth.verify_secret("correct horse battery", digest, salt)
    assert not auth.verify_secret("wrong", digest, salt)
    assert not auth.verify_secret("correct horse battery", "", salt)


def test_signup_rejects_bad_input():
    with pytest.raises(auth.AuthError):
        auth.create_user("not-an-email", "correct horse battery")
    with pytest.raises(auth.AuthError):
        auth.create_user("a@b.com", "short")


def test_duplicate_email_rejected():
    auth.create_user("a@b.com", "correct horse battery")
    with pytest.raises(auth.AuthError):
        auth.create_user("A@B.com", "correct horse battery")


def test_handle_is_not_derived_from_email():
    user_id = auth.create_user("jane.doe@example.com", "correct horse battery")
    handle = auth.get_user(user_id)["handle"]
    assert "jane" not in handle.lower()
    assert "@" not in handle


def test_anonymous_account_has_no_identifying_fields():
    user_id, code = auth.create_anonymous_user()
    row = auth.get_user(user_id)
    assert row["email"] is None
    assert row["anonymous"] == 1
    assert row["pw_hash"] is None
    assert auth.login_recovery(row["handle"], code)["id"] == user_id
    with pytest.raises(auth.AuthError):
        auth.login_recovery(row["handle"], "nope")


def test_sessions_resolve_and_revoke():
    user_id = auth.create_user("a@b.com", "correct horse battery")
    token = auth.create_session(user_id)
    assert auth.user_from_token(token)["id"] == user_id
    auth.destroy_session(token)
    assert auth.user_from_token(token) is None
    assert auth.user_from_token(None) is None


def test_delete_user_cascades_every_health_table():
    user_id = auth.create_user("a@b.com", "correct horse battery")
    db.execute(
        "INSERT INTO period_events (user_id, start_date) VALUES (?, '2026-01-01')", (user_id,)
    )
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, '2026-01-01', 'mood', 'mood_sad', ?)",
        (user_id, auth.now_iso()),
    )
    db.execute(
        "INSERT INTO assistant_messages (user_id, role, body, created_at)"
        " VALUES (?, 'user', 'hi', ?)",
        (user_id, auth.now_iso()),
    )
    auth.delete_user(user_id)

    for table in ("period_events", "daily_logs", "assistant_messages", "sessions", "entitlements"):
        assert db.query(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)) == []


def test_signup_and_whoami_over_http(client):
    res = client.post("/api/auth/signup", json={"email": "x@y.com", "password": "correct horse battery"})
    assert res.status_code == 200
    me = client.get("/api/me").json()
    assert me["user"]["email"] == "x@y.com"
    assert me["billing"]["tier"] == "free"

    client.post("/api/auth/logout")
    assert client.get("/api/me").status_code == 401


def test_anonymous_signup_returns_recovery_code(client):
    out = client.post("/api/auth/anonymous").json()
    assert out["recovery_code"]
    assert out["user"]["anonymous"] is True
    assert out["user"]["email"] is None
