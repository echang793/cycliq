"""Pregnancy mode, TTC mode, insights and the content library."""

from datetime import date, timedelta

from conftest import regular_starts, seed_periods

import auth
import content
import cycle as cyc
import db
import pregnancy
import ttc


# ── pregnancy ────────────────────────────────────────────────────

def test_due_date_is_lmp_plus_280_days():
    assert pregnancy.due_from_lmp(date(2026, 1, 1)) == date(2026, 10, 8)


def test_trimester_boundaries():
    assert pregnancy.trimester(13) == 1
    assert pregnancy.trimester(14) == 2
    assert pregnancy.trimester(27) == 2
    assert pregnancy.trimester(28) == 3


def test_week_maths(signed_in):
    me = signed_in.get("/api/me").json()["user"]
    lmp = date.today() - timedelta(days=140)  # exactly 20 weeks
    signed_in.post("/api/pregnancy/start", json={"lmp_date": lmp.isoformat()})
    status = pregnancy.status(me["id"], date.today())
    assert status["active"] is True
    assert status["week"] == 20
    assert status["trimester"] == 2
    assert status["days_to_due"] == 140


def test_starting_pregnancy_switches_mode(signed_in):
    signed_in.post("/api/pregnancy/start", json={"due_date": (date.today() + timedelta(days=100)).isoformat()})
    assert signed_in.get("/api/me").json()["user"]["mode"] == "pregnancy"
    signed_in.post("/api/pregnancy/end")
    assert signed_in.get("/api/me").json()["user"]["mode"] == "cycle"


def test_pregnancy_needs_one_of_the_two_dates(signed_in):
    assert signed_in.post("/api/pregnancy/start", json={}).status_code == 400


def test_weekly_detail_is_premium(signed_in):
    lmp = (date.today() - timedelta(days=140)).isoformat()
    signed_in.post("/api/pregnancy/start", json={"lmp_date": lmp})
    free = signed_in.get("/api/pregnancy/status").json()
    assert "development" not in free
    assert free["locked"]["feature"] == "Detailed pregnancy tracking"
    # Week and due date stay free — those are the basics.
    assert free["week"] == 20 and free["due_date"]

    signed_in.post("/api/billing/trial")
    paid = signed_in.get("/api/pregnancy/status").json()
    assert paid["development"] and paid["size"]


def test_movement_guidance_avoids_a_kick_target(premium):
    lmp = (date.today() - timedelta(days=200)).isoformat()
    premium.post("/api/pregnancy/start", json={"lmp_date": lmp})
    guide = premium.get("/api/pregnancy/weeks").json()
    text = guide["movement_guidance"].lower()
    assert "no set number" in text
    assert "same day" in text
    assert "10 kicks" not in text


def test_kick_counter_accumulates(premium):
    first = premium.post("/api/pregnancy/kicks", json={}).json()
    assert first["kicks"] == 1
    session = first["session_id"]
    for _ in range(4):
        out = premium.post("/api/pregnancy/kicks", json={"session_id": session}).json()
    assert out["kicks"] == 5
    assert premium.post(f"/api/pregnancy/kicks/{session}/end").json()["ended"] is True


def test_contraction_timer_averages(premium):
    base = date.today()
    for minutes, length in ((0, 45), (6, 50), (12, 55)):
        premium.post("/api/pregnancy/contractions", json={
            "started_at": f"{base}T10:{minutes:02d}:00",
            "duration_s": length,
        })
    out = premium.get("/api/pregnancy/contractions").json()
    assert len(out["contractions"]) == 3
    assert out["average_duration_s"] == 50
    assert out["average_gap_s"] == 360


# ── TTC ──────────────────────────────────────────────────────────

def test_fertile_window_probabilities_peak_before_ovulation(user_id):
    seed_periods(user_id, regular_starts(4, 28, date(2026, 1, 1)))
    out = ttc.window(user_id, date(2026, 4, 1))
    assert out["ready"] is True
    peak = max(out["days"], key=lambda d: d["probability"])
    assert peak["offset"] in (0, -1)
    assert out["days"][0]["offset"] == -5
    assert out["days"][-1]["offset"] == 1
    assert "every one to two days" in out["note"]


def test_window_declines_without_a_logged_period(user_id):
    assert ttc.window(user_id, date(2026, 4, 1))["ready"] is False


def test_chart_collects_bbt_mucus_and_lh(user_id):
    start = date(2026, 3, 1)
    seed_periods(user_id, [date(2026, 2, 1), start])
    for offset, temp in enumerate([36.4] * 14 + [36.75] * 10):
        db.execute(
            "INSERT INTO daily_logs (user_id, log_date, category, code, value, created_at)"
            " VALUES (?, ?, 'vitals', 'bbt', ?, ?)",
            (user_id, cyc.iso(start + timedelta(days=offset)), temp, auth.now_iso()),
        )
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, ?, 'discharge', 'dis_egg_white', ?)",
        (user_id, cyc.iso(start + timedelta(days=12)), auth.now_iso()),
    )
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, ?, 'tests', 'ovulation_test_pos', ?)",
        (user_id, cyc.iso(start + timedelta(days=13)), auth.now_iso()),
    )

    out = ttc.chart(user_id, start + timedelta(days=23))
    assert out["readings"] == 24
    assert out["luteal_measured"] is True
    day13 = next(d for d in out["days"] if d["cycle_day"] == 13)
    assert day13["mucus"] == "dis_egg_white"
    assert day13["mucus_score"] == 4
    day14 = next(d for d in out["days"] if d["cycle_day"] == 14)
    assert day14["lh"] == "ovulation_test_pos"


# ── insights ─────────────────────────────────────────────────────

def test_free_insights_show_locked_previews_not_blanks(signed_in):
    signed_in.post("/api/periods", json={"start_date": (date.today() - timedelta(days=5)).isoformat()})
    out = signed_in.get("/api/insights/today").json()
    assert out["premium"] is False
    locked = [c for c in out["cards"] if c["locked"]]
    assert locked
    for card in locked:
        assert card["title"] and card["body"]


def test_premium_insights_use_the_users_own_data(premium):
    me = premium.get("/api/me").json()["user"]
    starts = regular_starts(5, 28, date.today() - timedelta(days=112))
    seed_periods(me["id"], starts)
    for start in starts[:-1]:
        for offset in range(28):
            day = start + timedelta(days=offset)
            db.execute(
                "INSERT OR REPLACE INTO daily_logs (user_id, log_date, category, code, created_at)"
                " VALUES (?, ?, 'mood', 'mood_calm', ?)",
                (me["id"], cyc.iso(day), auth.now_iso()),
            )
            if 16 <= offset <= 26:
                db.execute(
                    "INSERT OR REPLACE INTO daily_logs (user_id, log_date, category, code, created_at)"
                    " VALUES (?, ?, 'symptoms', 'sym_bloating', ?)",
                    (me["id"], cyc.iso(day), auth.now_iso()),
                )
    out = premium.get("/api/insights/today").json()
    assert out["premium"] is True
    assert not any(c["locked"] for c in out["cards"])
    assert any(c["kind"] == "pattern" for c in out["cards"])


def test_no_data_card_appears_before_any_period(signed_in):
    out = signed_in.get("/api/insights/today").json()
    assert any("Log your last period" in c["title"] for c in out["cards"])


# ── content ──────────────────────────────────────────────────────

def test_every_article_names_a_source():
    for item in content.articles():
        assert item["source"].strip()
        assert item["body"].strip()
        assert item["blurb"].strip()


def test_courses_have_lessons_with_bodies():
    for course in content.courses():
        assert len(course["lessons"]) >= 4
        slugs = [lesson["slug"] for lesson in course["lessons"]]
        assert len(slugs) == len(set(slugs))
        for lesson in course["lessons"]:
            assert lesson["title"] and lesson["body"]


def test_article_ids_are_unique():
    ids = [a["id"] for a in content.articles()]
    assert len(ids) == len(set(ids))


def test_free_articles_exist_and_open_without_premium(signed_in):
    library = signed_in.get("/api/content/library").json()
    assert library["free_count"] >= 5
    free = next(a for a in library["articles"] if not a["locked"])
    assert signed_in.get(f"/api/content/articles/{free['id']}").status_code == 200


def test_course_progress_records_lessons(premium):
    course = content.courses()[0]
    premium.post("/api/content/progress",
                 json={"item_id": course["id"], "lesson_slug": course["lessons"][0]["slug"]})
    listed = premium.get("/api/content/courses").json()["courses"]
    assert next(c for c in listed if c["id"] == course["id"])["completed"] == 1


def test_reminders_fire_relative_to_predictions(signed_in):
    import reminders

    me = signed_in.get("/api/me").json()["user"]
    seed_periods(me["id"], regular_starts(4, 28, date.today() - timedelta(days=84)))
    prediction = signed_in.get("/api/prediction").json()
    fires_on = cyc.to_date(prediction["next_period"]) - timedelta(days=2)

    signed_in.post("/api/reminders", json={"kind": "period_soon", "offset_days": -2})
    signed_in.post("/api/reminders", json={"kind": "log"})

    due_today = reminders.due(me["id"], date.today())
    assert any(r["kind"] == "log" for r in due_today)          # daily always fires
    assert all(r["kind"] != "period_soon" for r in due_today)  # not yet

    due_then = reminders.due(me["id"], fires_on)
    assert any(r["kind"] == "period_soon" for r in due_then)
