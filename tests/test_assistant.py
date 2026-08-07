"""The assistant must degrade, never fail. These tests run with both model
backends disabled, which is the deployment most users will actually hit."""

from datetime import date

import pytest
from conftest import regular_starts, seed_periods

import assistant
import content


@pytest.fixture(autouse=True)
def no_models(monkeypatch):
    monkeypatch.setattr(assistant, "_ollama", lambda *a, **k: None)
    monkeypatch.setattr(assistant, "ANTHROPIC_API_KEY", "")


def test_rules_tier_answers_from_the_library(user_id):
    out = assistant.answer(user_id, "why do I get cramps on my period?")
    assert out["backend"] == "rules"
    assert out["reply"]
    assert any(s["id"] == "cramps" for s in out["sources"])
    assert "clinician" in out["disclaimer"]


def test_answer_includes_cycle_context_when_known(user_id):
    seed_periods(user_id, regular_starts(4, 28, date(2026, 1, 1)))
    out = assistant.answer(user_id, "what happens in the luteal phase?", date(2026, 3, 20))
    assert "day" in out["reply"].lower()


def test_unknown_topic_does_not_invent(user_id):
    out = assistant.answer(user_id, "zzzqqq unrelated nonsense token")
    assert out["sources"] == []
    assert "don't have an article" in out["reply"]


def test_self_harm_language_surfaces_a_crisis_line_first(user_id):
    out = assistant.answer(user_id, "I keep thinking about suicide before my period")
    assert out["urgent"]
    assert "988" in out["reply"]
    assert out["reply"].startswith("**")


def test_heavy_bleeding_language_flags_urgency(user_id):
    out = assistant.answer(user_id, "I'm soaking a pad every hour, is that normal?")
    assert out["urgent"]
    assert "urgent" in out["reply"].lower()


def test_context_sent_to_a_model_is_aggregate_only(user_id):
    seed_periods(user_id, regular_starts(4, 28, date(2026, 1, 1)))
    context = assistant.cycle_context(user_id, date(2026, 3, 20))
    assert set(context) == {
        "cycle_day", "phase", "typical_cycle_length", "days_to_next_period",
        "cycles_logged", "cycles_irregular",
    }
    blob = str(context)
    assert "@" not in blob and "example.com" not in blob


def test_retrieval_prefers_title_matches():
    hits = content.snippets_for("endometriosis", limit=3)
    assert hits and "endometriosis" in hits[0]["title"].lower()


def test_connector_words_do_not_win_over_the_actual_symptom():
    """Found 2026-08-06: 'before' wasn't a stopword, so 'why do I get bloating
    before my period' scored the sleep article's title (a hit on both 'period'
    and 'before') over any article discussing bloating, and the assistant
    grounded its answer in the wrong topic entirely."""
    hits = content.search("why do I get bloating before my period?", limit=5)
    ids = [h["id"] for h in hits]
    assert "sleep-and-hormones" not in ids[:1], (
        "an unrelated sleep article should not outrank every bloating-adjacent result"
    )


def test_rare_terms_outweigh_a_word_in_every_title():
    """'period' is in most titles in this library by the nature of the app;
    it should contribute little next to a term specific to one or two
    articles, or search degrades to 'which title says period'."""
    assert content._idf("period") < content._idf("bloating") < content._idf("cramps")


def test_chat_persists_both_turns(premium):
    premium.post("/api/assistant/chat", json={"message": "how long is a normal cycle?"})
    messages = premium.get("/api/assistant/history").json()["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert messages[1]["backend"] == "rules"

    premium.delete("/api/assistant/history")
    assert premium.get("/api/assistant/history").json()["messages"] == []


def test_system_prompt_forbids_diagnosis():
    prompt = assistant.SYSTEM_PROMPT.lower()
    assert "never diagnose" in prompt or "educate, never diagnose" in prompt
    assert "probability" in prompt
