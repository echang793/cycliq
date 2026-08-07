from datetime import date, timedelta

from conftest import regular_starts, seed_periods

import auth
import cycle as cyc
import db
import patterns


def log(user_id, day, code, category="symptoms"):
    db.execute(
        "INSERT OR REPLACE INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (user_id, cyc.iso(day), category, code, auth.now_iso()),
    )


def test_patterns_refuse_to_speak_before_two_cycles(user_id):
    seed_periods(user_id, regular_starts(2, 28, date(2026, 1, 1)))
    out = patterns.compute(user_id, date(2026, 2, 1))
    assert out["ready"] is False
    assert out["cycles_logged"] == 1
    assert out["patterns"] == []


def test_luteal_clustering_is_detected(user_id):
    starts = regular_starts(5, 28, date(2026, 1, 1))
    seed_periods(user_id, starts)
    # Log something every day of each cycle so the baseline is well defined,
    # and headaches only in the luteal phase (days 17-27).
    for start in starts[:-1]:
        for offset in range(28):
            day = start + timedelta(days=offset)
            log(user_id, day, "mood_calm", "mood")
            if 16 <= offset <= 26:
                log(user_id, day, "sym_headache")

    out = patterns.compute(user_id, starts[-1])
    assert out["ready"] is True
    headache = next(p for p in out["patterns"] if p["code"] == "sym_headache")
    assert headache["phase"] == "luteal"
    assert headache["lift"] > patterns.LIFT_THRESHOLD
    assert "luteal" in headache["sentence"]


def test_min_sample_gate_suppresses_thin_claims(user_id):
    starts = regular_starts(5, 28, date(2026, 1, 1))
    seed_periods(user_id, starts)
    for start in starts[:-1]:
        for offset in range(28):
            log(user_id, start + timedelta(days=offset), "mood_calm", "mood")
    # A symptom logged only twice, ever, must not become a "pattern".
    log(user_id, starts[0] + timedelta(days=20), "sym_migraine")
    log(user_id, starts[1] + timedelta(days=20), "sym_migraine")

    out = patterns.compute(user_id, starts[-1])
    assert all(p["code"] != "sym_migraine" for p in out["patterns"])


def test_trends_report_direction_and_spread(user_id):
    starts, cursor = [], date(2026, 1, 1)
    for length in (26, 26, 27, 31, 32, 33):
        starts.append(cursor)
        cursor += timedelta(days=length)
    starts.append(cursor)
    seed_periods(user_id, starts)

    out = patterns.trends(user_id)
    assert out["ready"] is True
    assert out["direction"] == "lengthening"
    assert out["shortest"] == 26 and out["longest"] == 33
    assert len(out["cycles"]) == 6


def test_trends_flag_irregular(user_id):
    starts, cursor = [], date(2026, 1, 1)
    for length in (21, 47, 22, 49, 24, 45):
        starts.append(cursor)
        cursor += timedelta(days=length)
    starts.append(cursor)
    seed_periods(user_id, starts)

    out = patterns.trends(user_id)
    assert out["irregular"] is True
    assert "clinician" in out["message"]


def test_forecast_maps_future_days_to_phases(user_id):
    starts = regular_starts(5, 28, date(2026, 1, 1))
    seed_periods(user_id, starts)
    for start in starts[:-1]:
        for offset in range(28):
            day = start + timedelta(days=offset)
            log(user_id, day, "mood_calm", "mood")
            if 16 <= offset <= 26:
                log(user_id, day, "sym_bloating")

    out = patterns.forecast(user_id, starts[-1] + timedelta(days=16), days=7)
    assert out["ready"] is True
    assert len(out["days"]) == 7
    assert {d["phase"] for d in out["days"]} <= set(cyc.PHASES)
    assert any(d["likely"] for d in out["days"])


def test_forecast_declines_without_data(user_id):
    out = patterns.forecast(user_id, date(2026, 1, 1))
    assert out["ready"] is False
    assert out["days"] == []
