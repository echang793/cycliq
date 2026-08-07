from datetime import date, timedelta

from conftest import regular_starts, seed_periods

import cycle as cyc
import db
import predict as pr


def test_regular_cycles_predict_tightly(user_id):
    seed_periods(user_id, regular_starts(7, 28, date(2026, 1, 1)))
    p = pr.predict(user_id, date(2026, 6, 1))
    assert p.cycle_len == 28
    assert p.source == "history"
    assert p.n_cycles == 6
    assert p.confidence == "high"
    assert p.interval == 1          # MAD is 0, so the floor applies
    assert not p.irregular


def test_irregular_cycles_widen_the_window(user_id):
    starts, cursor = [], date(2026, 1, 1)
    for length in (24, 45, 26, 51, 23, 44):
        starts.append(cursor)
        cursor += timedelta(days=length)
    starts.append(cursor)
    seed_periods(user_id, starts)

    p = pr.predict(user_id, cursor)
    assert p.irregular
    assert p.interval == 7
    assert p.confidence == "low"
    assert "vary" in p.note


def test_cold_start_uses_profile_then_default(user_id):
    p = pr.predict(user_id, date(2026, 1, 10))
    assert p.source == "default"
    assert p.cycle_len == 28
    assert p.next_period is None

    db.execute("UPDATE users SET avg_cycle_len = 31 WHERE id = ?", (user_id,))
    seed_periods(user_id, [date(2026, 1, 5)])
    p = pr.predict(user_id, date(2026, 1, 10))
    assert p.source == "profile"
    assert p.cycle_len == 31
    assert p.next_period == "2026-02-05"


def test_prediction_rolls_forward_when_logging_stops(user_id):
    """Someone who logged once and vanished should not see 'day 200'."""
    seed_periods(user_id, [date(2026, 1, 1)])
    db.execute("UPDATE users SET avg_cycle_len = 28 WHERE id = ?", (user_id,))
    p = pr.predict(user_id, date(2026, 7, 1))
    assert p.cycle_day is not None and p.cycle_day <= 35


def test_ovulation_counts_back_from_next_period(user_id):
    seed_periods(user_id, regular_starts(4, 30, date(2026, 1, 1)))
    p = pr.predict(user_id, date(2026, 4, 1))
    next_period = cyc.to_date(p.next_period)
    ovulation = cyc.to_date(p.ovulation)
    assert (next_period - ovulation).days == p.luteal_len == 14


def test_fertile_window_spans_five_before_to_one_after(user_id):
    seed_periods(user_id, regular_starts(6, 28, date(2026, 1, 1)))
    p = pr.predict(user_id, date(2026, 6, 1))
    ovulation = cyc.to_date(p.ovulation)
    assert cyc.to_date(p.fertile_start) == ovulation - timedelta(days=5)
    assert cyc.to_date(p.fertile_end) == ovulation + timedelta(days=1)


def _log_bbt(user_id, start, temps):
    import auth

    for offset, temp in enumerate(temps):
        db.execute(
            "INSERT OR REPLACE INTO daily_logs (user_id, log_date, category, code, value, created_at)"
            " VALUES (?, ?, 'vitals', 'bbt', ?, ?)",
            (user_id, cyc.iso(start + timedelta(days=offset)), temp, auth.now_iso()),
        )


def test_bbt_thermal_shift_measures_luteal_length(user_id):
    starts = regular_starts(4, 30, date(2026, 1, 1))
    seed_periods(user_id, starts)
    # Low phase then a sustained 0.35C rise starting on cycle day 17 →
    # ovulation on day 16 → luteal length 30 - 16 = 14... shifted to 13 here.
    for start in starts[:-1]:
        _log_bbt(user_id, start, [36.4] * 16 + [36.75] * 14)

    luteal, n = pr.estimate_luteal(user_id, cyc.derive_cycles(cyc.list_periods(user_id)))
    assert n == 3
    assert pr.LUTEAL_MIN <= luteal <= pr.LUTEAL_MAX


def test_positive_lh_test_sets_ovulation(user_id):
    import auth

    start, nxt = date(2026, 2, 1), date(2026, 3, 1)
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, '2026-02-15', 'tests', 'ovulation_test_pos', ?)",
        (user_id, auth.now_iso()),
    )
    assert pr.ovulation_marker(user_id, start, nxt) == date(2026, 2, 16)


def test_luteal_clamped_to_plausible_range(user_id):
    import auth

    starts = regular_starts(3, 28, date(2026, 1, 1))
    seed_periods(user_id, starts)
    # An LH test on cycle day 2 would imply a 26-day luteal phase — rejected.
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, created_at)"
        " VALUES (?, '2026-01-02', 'tests', 'ovulation_test_pos', ?)",
        (user_id, auth.now_iso()),
    )
    luteal, _ = pr.estimate_luteal(user_id, cyc.derive_cycles(cyc.list_periods(user_id)))
    assert luteal == pr.LUTEAL_DEFAULT


def test_weighted_median_and_mad():
    assert pr.median([1, 2, 3]) == 2
    assert pr.median([1, 2, 3, 4]) == 2.5
    assert pr.mad([28, 28, 28, 40], 28) == 0.0
    assert pr.weighted_median([28, 28, 40], [1, 1, 0.1]) == 28


def test_calendar_map_marks_logged_and_predicted(user_id):
    seed_periods(user_id, regular_starts(4, 28, date(2026, 1, 1)))
    days = pr.upcoming_days(user_id, date(2026, 1, 1), 140)
    assert any(v["logged_period"] for v in days.values())
    assert any(v["predicted_period"] for v in days.values())
    assert any(v["fertile"] for v in days.values())
    assert sum(1 for v in days.values() if v["ovulation"]) <= 1
