"""Partner Mode is the one place where one account reads another's health data.
These tests exist to make sure the scope list is the only thing that decides."""

from datetime import date

from conftest import regular_starts, seed_periods

import auth
import db
import partner


def make_partner(client):
    from fastapi.testclient import TestClient

    import server

    other = TestClient(server.app)
    other.post("/api/auth/signup", json={"email": "partner@example.com", "password": "correct horse battery"})
    return other


def owner_with_data(client):
    me = client.get("/api/me").json()["user"]
    seed_periods(me["id"], regular_starts(5, 28, date(2026, 1, 1)))
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, ?, 'symptoms', 'sym_cramps', ?)",
        (me["id"], date.today().isoformat(), auth.now_iso()),
    )
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, ?, 'mood', 'mood_irritable', ?)",
        (me["id"], date.today().isoformat(), auth.now_iso()),
    )
    return me


def link_up(owner, other, scopes):
    code = owner.post("/api/partner/invite", json={"scopes": scopes}).json()["invite_code"]
    joined = other.post("/api/partner/join", json={"code": code}).json()
    return joined["link"]["id"]


def test_free_owner_cannot_share_symptoms(signed_in):
    owner_with_data(signed_in)
    other = make_partner(signed_in)
    link_id = link_up(signed_in, other, ["cycle_phase", "period_dates", "symptoms", "mood", "fertile_window"])

    view = other.get(f"/api/partner/view/{link_id}").json()
    assert set(view["scopes"]) == partner.BASIC_SCOPES
    assert "today_logged" not in view
    assert "fertile_start" not in view
    assert view["phase"] and view["next_period"]


def test_premium_owner_shares_the_full_scope_set(premium):
    owner_with_data(premium)
    other = make_partner(premium)
    link_id = link_up(premium, other, ["cycle_phase", "period_dates", "symptoms", "mood", "fertile_window"])

    view = other.get(f"/api/partner/view/{link_id}").json()
    assert "fertile_start" in view
    labels = {e["label"] for e in view["today_logged"]}
    assert "Cramps" in labels and "Irritable" in labels


def test_scope_removal_takes_effect_immediately(premium):
    owner_with_data(premium)
    other = make_partner(premium)
    link_id = link_up(premium, other, ["cycle_phase", "period_dates", "symptoms"])
    assert "today_logged" in other.get(f"/api/partner/view/{link_id}").json()

    premium.post(f"/api/partner/links/{link_id}/scopes", json={"scopes": ["cycle_phase"]})
    view = other.get(f"/api/partner/view/{link_id}").json()
    assert "today_logged" not in view
    assert "next_period" not in view


def test_downgrading_to_free_narrows_an_existing_link(premium):
    owner_with_data(premium)
    other = make_partner(premium)
    link_id = link_up(premium, other, ["cycle_phase", "symptoms"])
    assert "today_logged" in other.get(f"/api/partner/view/{link_id}").json()

    premium.post("/api/billing/cancel")
    assert "today_logged" not in other.get(f"/api/partner/view/{link_id}").json()


def test_a_stranger_cannot_read_the_link(signed_in):
    owner_with_data(signed_in)
    other = make_partner(signed_in)
    link_id = link_up(signed_in, other, ["cycle_phase"])

    from fastapi.testclient import TestClient

    import server

    stranger = TestClient(server.app)
    stranger.post("/api/auth/signup", json={"email": "nosy@example.com", "password": "correct horse battery"})
    assert stranger.get(f"/api/partner/view/{link_id}").status_code == 404
    # Nor can the owner read it through the partner endpoint.
    assert signed_in.get(f"/api/partner/view/{link_id}").status_code == 404


def test_invite_code_is_single_use(signed_in):
    owner_with_data(signed_in)
    other = make_partner(signed_in)
    code = signed_in.post("/api/partner/invite", json={"scopes": ["cycle_phase"]}).json()["invite_code"]
    assert other.post("/api/partner/join", json={"code": code}).status_code == 200

    from fastapi.testclient import TestClient

    import server

    third = TestClient(server.app)
    third.post("/api/auth/signup", json={"email": "third@example.com", "password": "correct horse battery"})
    assert third.post("/api/partner/join", json={"code": code}).status_code == 404


def test_cannot_partner_yourself(signed_in):
    code = signed_in.post("/api/partner/invite", json={"scopes": ["cycle_phase"]}).json()["invite_code"]
    assert signed_in.post("/api/partner/join", json={"code": code}).status_code == 400


def test_unknown_scopes_are_dropped(signed_in):
    out = signed_in.post(
        "/api/partner/invite", json={"scopes": ["cycle_phase", "read_my_diary"]}
    ).json()
    assert out["link"]["scopes"] == ["cycle_phase"]


def test_revoking_removes_access(signed_in):
    owner_with_data(signed_in)
    other = make_partner(signed_in)
    link_id = link_up(signed_in, other, ["cycle_phase"])
    signed_in.delete(f"/api/partner/links/{link_id}")
    assert other.get(f"/api/partner/view/{link_id}").status_code == 404


def test_partner_view_never_leaks_notes(premium):
    me = owner_with_data(premium)
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, text, created_at)"
        " VALUES (?, ?, 'notes', 'note', 'private thought', ?)",
        (me["id"], date.today().isoformat(), auth.now_iso()),
    )
    other = make_partner(premium)
    link_id = link_up(premium, other, list(partner.SCOPES))
    assert "private thought" not in other.get(f"/api/partner/view/{link_id}").text
