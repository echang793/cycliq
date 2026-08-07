from datetime import date, timedelta

import pytest
from conftest import seed_periods

import checker
import db


def answer_all(tool, choice_index=0):
    """Pick the option at `choice_index` (clamped) for every question."""
    out = {}
    for question in checker.TOOLS[tool]["questions"]:
        options = question["options"]
        out[question["key"]] = options[min(choice_index, len(options) - 1)]["value"]
    return out


def worst(tool):
    return {
        q["key"]: max(q["options"], key=lambda o: o["score"])["value"]
        for q in checker.TOOLS[tool]["questions"]
    }


@pytest.mark.parametrize("tool", list(checker.TOOLS))
def test_lowest_answers_give_a_low_band(tool):
    result = checker.score(tool, answer_all(tool, 0))
    assert result["band"] == "low"
    assert result["score"] == 0
    assert "not a diagnosis" in result["disclaimer"].lower() or "diagnosis" in result["disclaimer"]


@pytest.mark.parametrize("tool", list(checker.TOOLS))
def test_worst_answers_give_a_strong_band(tool):
    result = checker.score(tool, worst(tool))
    assert result["band"] == "strong"
    assert result["ratio"] >= checker.STRONG


@pytest.mark.parametrize("tool", list(checker.TOOLS))
def test_no_probability_of_disease_is_ever_stated(tool):
    for answers in (answer_all(tool, 0), worst(tool)):
        blob = " ".join(str(v) for v in checker.score(tool, answers).values()).lower()
        assert "% chance" not in blob
        assert "you have" not in blob
        assert "diagnos" in blob  # the disclaimer always says it is not one


def test_band_boundaries():
    total = checker.max_score("pcos")
    questions = checker.TOOLS["pcos"]["questions"]

    def build(target):
        """Answers summing to roughly `target`, greedily."""
        remaining, answers = target, {}
        for q in questions:
            options = sorted(q["options"], key=lambda o: -o["score"])
            pick = next((o for o in options if o["score"] <= remaining), options[-1])
            answers[q["key"]] = pick["value"]
            remaining -= pick["score"]
        return answers

    assert checker.score("pcos", build(int(total * 0.10)))["band"] == "low"
    assert checker.score("pcos", build(int(total * 0.45)))["band"] == "moderate"


def test_incomplete_submission_is_rejected():
    answers = answer_all("pcos", 0)
    answers.pop("family")
    with pytest.raises(ValueError):
        checker.score("pcos", answers)


def test_unknown_option_is_rejected():
    answers = answer_all("pcos", 0)
    answers["family"] = "Maybe?"
    with pytest.raises(ValueError):
        checker.score("pcos", answers)


def test_pcos_gate_caps_strong_when_cycles_are_regular():
    """Rotterdam needs two of three features; regular ovulatory cycles make a
    'strong' PCOS match unsupportable however many skin signs are present."""
    answers = worst("pcos")
    answers["cycle_length"] = "21-35 days"
    answers["missed"] = "No"
    result = checker.score("pcos", answers)
    assert result["band"] == "moderate"
    assert "regular" in result["explanation"]


def test_perimenopause_gate_caps_strong_without_cycle_change():
    answers = worst("perimenopause")
    answers["cycle_change"] = "No"
    answers["skipped"] = "No"
    assert checker.score("perimenopause", answers)["band"] == "moderate"


def test_red_flags_surface_regardless_of_band():
    answers = answer_all("endometriosis", 0)
    answers["pain_severity"] = "I miss work, school or plans"
    result = checker.score("endometriosis", answers)
    assert result["band"] == "low"
    assert result["red_flags"]


def test_prefill_reads_logged_cycles(user_id):
    starts, cursor = [], date(2026, 1, 1)
    for length in (23, 48, 25, 52, 22):
        starts.append(cursor)
        cursor += timedelta(days=length)
    starts.append(cursor)
    seed_periods(user_id, starts)
    db.execute("UPDATE users SET birth_year = 1980 WHERE id = ?", (user_id,))

    assert checker.prefill(user_id, "pcos", cursor)["cycle_length"] == "It varies a lot"
    assert checker.prefill(user_id, "perimenopause", cursor)["age"] == "45-55"


def test_prefill_flags_skipped_cycles(user_id):
    seed_periods(user_id, [date(2026, 1, 1), date(2026, 3, 20), date(2026, 4, 18)])
    assert checker.prefill(user_id, "perimenopause", date(2026, 5, 1))["skipped"] == "Yes"


def test_saving_is_opt_in(premium):
    answers = answer_all("pcos", 0)
    premium.post("/api/checker/pcos", json={"answers": answers, "save": False})
    assert premium.get("/api/checker/history/all").json()["results"] == []

    premium.post("/api/checker/pcos", json={"answers": answers, "save": True})
    saved = premium.get("/api/checker/history/all").json()["results"]
    assert len(saved) == 1 and saved[0]["tool"] == "pcos"


def test_incomplete_submission_over_http(premium):
    answers = answer_all("pcos", 0)
    answers.pop("family")
    res = premium.post("/api/checker/pcos", json={"answers": answers})
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "incomplete"


def test_unknown_tool_404(premium):
    assert premium.get("/api/checker/lupus").status_code == 404
