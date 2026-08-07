from datetime import date, timedelta

from conftest import regular_starts, seed_periods

import cycle as cyc


def test_derive_cycles_from_consecutive_starts(user_id):
    seed_periods(user_id, regular_starts(4, 28))
    cycles = cyc.derive_cycles(cyc.list_periods(user_id))
    assert [c.length for c in cycles] == [28, 28, 28]


def test_implausible_gap_is_dropped(user_id):
    # A 120-day gap is missing data, not a 120-day cycle.
    seed_periods(user_id, [date(2026, 1, 1), date(2026, 1, 29), date(2026, 5, 29)])
    cycles = cyc.derive_cycles(cyc.list_periods(user_id))
    assert [c.length for c in cycles] == [28]


def test_too_short_gap_is_dropped(user_id):
    # Two starts three days apart is a double-logged period.
    seed_periods(user_id, [date(2026, 1, 1), date(2026, 1, 4), date(2026, 2, 1)])
    lengths = [c.length for c in cyc.derive_cycles(cyc.list_periods(user_id))]
    assert 3 not in lengths
    assert 28 in lengths


def test_period_length_and_typical(user_id):
    seed_periods(user_id, regular_starts(3, 28), period_len=6)
    assert cyc.typical_period_len(user_id) == 6


def test_cycle_day_is_one_indexed(user_id):
    start = date(2026, 3, 1)
    assert cyc.cycle_day(start, start) == 1
    assert cyc.cycle_day(start + timedelta(days=5), start) == 6
    assert cyc.cycle_day(start - timedelta(days=1), start) is None


def test_phase_boundaries():
    # 28-day cycle, ovulation day 14, 5-day period
    assert cyc.phase_for_day(1, 28, 14, 5) == "menstrual"
    assert cyc.phase_for_day(5, 28, 14, 5) == "menstrual"
    assert cyc.phase_for_day(6, 28, 14, 5) == "follicular"
    assert cyc.phase_for_day(13, 28, 14, 5) == "ovulatory"
    assert cyc.phase_for_day(14, 28, 14, 5) == "ovulatory"
    assert cyc.phase_for_day(15, 28, 14, 5) == "ovulatory"
    assert cyc.phase_for_day(16, 28, 14, 5) == "luteal"
    assert cyc.phase_for_day(28, 28, 14, 5) == "luteal"


def test_phase_on_uses_enclosing_cycle(user_id):
    seed_periods(user_id, regular_starts(3, 28, date(2026, 1, 1)))
    assert cyc.phase_on(user_id, date(2026, 1, 2)) == "menstrual"
    assert cyc.phase_on(user_id, date(2026, 1, 14)) == "ovulatory"
    assert cyc.phase_on(user_id, date(2026, 1, 25)) == "luteal"
    assert cyc.phase_on(user_id, date(2025, 12, 1)) is None


def test_history_is_newest_first(user_id):
    seed_periods(user_id, regular_starts(4, 28))
    hist = cyc.history(user_id)
    assert hist[0]["start"] > hist[-1]["start"]
