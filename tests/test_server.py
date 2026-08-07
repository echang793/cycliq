from datetime import date, timedelta

import symptoms as sym


def test_health_endpoint_reports_library_size(client):
    out = client.get("/api/health").json()
    assert out["ok"] is True
    assert out["articles"] >= 40
    assert out["courses"] >= 5


def test_catalog_covers_more_than_eighty_trackables(client):
    out = client.get("/api/log/catalog").json()
    assert out["total_trackable"] > 80
    keys = {c["key"] for c in out["categories"]}
    assert {"flow", "mood", "symptoms", "discharge", "sex", "tests", "vitals"} <= keys


def test_onboarding_then_first_prediction(signed_in):
    signed_in.patch("/api/me", json={
        "goal": "track", "birth_year": 1995, "avg_cycle_len": 30,
        "avg_period_len": 5, "onboarded": True,
    })
    assert signed_in.get("/api/me").json()["user"]["onboarded"] is True

    prediction = signed_in.get("/api/prediction").json()
    assert prediction["source"] == "profile"
    assert prediction["next_period"] is None  # nothing to anchor to yet

    start = (date.today() - timedelta(days=3)).isoformat()
    out = signed_in.post("/api/periods", json={"start_date": start}).json()["prediction"]
    assert out["source"] == "profile"
    assert out["cycle_len"] == 30
    assert out["next_period"]


def test_interval_tightens_as_cycles_accumulate(signed_in):
    intervals = []
    start = date(2026, 1, 1)
    for i in range(7):
        signed_in.post("/api/periods", json={"start_date": (start + timedelta(days=28 * i)).isoformat()})
        intervals.append(signed_in.get("/api/prediction").json()["interval"])
    assert intervals[-1] <= intervals[0]
    final = signed_in.get("/api/prediction").json()
    assert final["confidence"] == "high"
    assert final["n_cycles"] == 6


def test_bad_dates_rejected(signed_in):
    assert signed_in.post("/api/periods", json={"start_date": "not-a-date"}).status_code == 400
    assert signed_in.post(
        "/api/periods", json={"start_date": "2026-03-10", "end_date": "2026-03-01"}
    ).status_code == 400


def test_period_delete_updates_prediction(signed_in):
    signed_in.post("/api/periods", json={"start_date": "2026-02-01"})
    period_id = signed_in.get("/api/periods").json()["periods"][0]["id"]
    out = signed_in.delete(f"/api/periods/{period_id}").json()
    assert out["deleted"] is True
    assert signed_in.get("/api/periods").json()["periods"] == []


def test_logging_round_trip(signed_in):
    day = date.today().isoformat()
    out = signed_in.post("/api/log", json={"date": day, "code": "sym_cramps"}).json()
    assert any(e["code"] == "sym_cramps" for e in out["entries"])

    signed_in.post("/api/log", json={"date": day, "code": "bbt", "value": 36.55})
    entries = signed_in.get(f"/api/log/{day}").json()["entries"]
    assert next(e for e in entries if e["code"] == "bbt")["value"] == 36.55

    out = signed_in.request("DELETE", "/api/log", json={"date": day, "code": "sym_cramps"}).json()
    assert all(e["code"] != "sym_cramps" for e in out["entries"])


def test_single_choice_categories_replace_not_stack(signed_in, user_id):
    me = signed_in.get("/api/me").json()["user"]
    day = date.today().isoformat()
    signed_in.post("/api/log", json={"date": day, "code": "flow_heavy"})
    signed_in.post("/api/log", json={"date": day, "code": "flow_light"})
    flows = [e for e in sym.day_log(me["id"], day)["entries"] if e["category"] == "flow"]
    assert len(flows) == 1 and flows[0]["code"] == "flow_light"


def test_unknown_tracking_code_rejected(signed_in):
    res = signed_in.post("/api/log", json={"date": date.today().isoformat(), "code": "vibes"})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "bad_code"


def test_calendar_marks_days(signed_in):
    signed_in.post("/api/periods", json={"start_date": "2026-03-01", "end_date": "2026-03-05"})
    out = signed_in.get("/api/calendar?start=2026-03-01&days=31").json()
    assert out["days"]["2026-03-02"]["logged_period"] is True
    assert out["days"]["2026-03-20"]["logged_period"] is False


def test_export_contains_every_table_and_delete_is_final(signed_in):
    day = date.today().isoformat()
    signed_in.post("/api/periods", json={"start_date": "2026-01-01"})
    signed_in.post("/api/log", json={"date": day, "code": "mood_anxious"})
    signed_in.post("/api/community/posts", json={"topic": "cycle", "body": "Hello."})

    export = signed_in.get("/api/me/export").json()
    for key in ("account", "billing", "periods", "logs", "reminders", "checker_results",
                "assistant_messages", "community_posts", "partner_links", "pregnancies"):
        assert key in export
    assert len(export["periods"]) == 1
    assert len(export["logs"]) == 1

    assert signed_in.delete("/api/me").json()["deleted"] is True
    assert signed_in.get("/api/me").status_code == 401


def test_pwa_assets_are_served(client):
    assert client.get("/").status_code == 200
    assert client.get("/manifest.json").json()["name"] == "cycliq"
    assert "cycliq-shell" in client.get("/sw.js").text
    assert client.get("/static/app.js").status_code == 200


def test_service_worker_never_caches_api_responses(client):
    body = client.get("/sw.js").text
    assert "/api/" in body and "return;" in body


def test_app_shell_assets_force_revalidation(client):
    """A stale-cache regression: browsers heuristically cache assets that ship
    Last-Modified but no Cache-Control, and can skip the network entirely on
    reload. Without this header a JS fix can silently never reach an already-
    open tab. API responses are deliberately exempt — no cycle data belongs
    in any HTTP cache, so they carry no caching guidance either way here."""
    for path in ("/", "/static/app.js", "/static/style.css", "/sw.js", "/manifest.json"):
        assert client.get(path).headers["cache-control"] == "no-cache", path
    assert "cache-control" not in {k.lower() for k in client.get("/api/health").headers}
