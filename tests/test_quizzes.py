"""Daily quiz (free) and lesson quizzes (Premium)."""

from datetime import date, timedelta


import content
import db
import quizzes

LESSON = "/api/quiz/lessons/course-cycle-literacy/hormones"


# ── content integrity ────────────────────────────────────────────

def test_every_lesson_has_a_quiz_with_valid_answers():
    for course in content.courses():
        for lesson in course["lessons"]:
            questions = quizzes.lesson_questions(course["id"], lesson["slug"])
            assert len(questions) >= 2, (course["id"], lesson["slug"])
            for q in questions:
                assert len(q["options"]) >= 2
                assert 0 <= q["answer"] < len(q["options"])
                assert q["q"].strip() and q["explain"].strip()


def test_no_quiz_for_a_lesson_that_does_not_exist():
    data = quizzes.load()["lessons"]
    real = {(c["id"], l["slug"]) for c in content.courses() for l in c["lessons"]}
    listed = {(cid, slug) for cid, lessons in data.items() for slug in lessons}
    assert listed <= real


def test_daily_pool_is_large_and_ids_unique():
    pool = quizzes.load()["daily"]
    assert len(pool) >= 14
    ids = [q["id"] for q in pool]
    assert len(ids) == len(set(ids))
    for q in pool:
        assert 0 <= q["answer"] < len(q["options"]) and q["explain"].strip()


def test_daily_question_changes_each_day_and_is_stable_within_a_day():
    today = date(2026, 10, 12)
    assert quizzes.daily_question(today)["id"] == quizzes.daily_question(today)["id"]
    ids = {quizzes.daily_question(today + timedelta(days=i))["id"] for i in range(7)}
    assert len(ids) == 7


# ── daily quiz over HTTP ─────────────────────────────────────────

def test_daily_is_free_and_never_leaks_the_answer(signed_in):
    res = signed_in.get("/api/quiz/daily")
    assert res.status_code == 200
    body = res.json()
    assert body["question"] and len(body["options"]) >= 2
    assert body["answered"] is False
    assert not {"answer", "correct", "correct_index", "explanation"} & set(body)


def test_answering_reveals_the_result_and_is_final(signed_in):
    first = signed_in.get("/api/quiz/daily").json()
    right = quizzes.daily_question(date.today())["answer"]
    wrong = (right + 1) % len(first["options"])

    out = signed_in.post("/api/quiz/daily/answer", json={"choice": wrong}).json()
    assert out["correct"] is False
    assert out["correct_index"] == right and out["explanation"]

    # A second attempt cannot change the stored result.
    again = signed_in.post("/api/quiz/daily/answer", json={"choice": right}).json()
    assert again["correct"] is False and again["already_answered"] is True
    assert signed_in.get("/api/quiz/daily").json()["answered"] is True


def test_out_of_range_choice_rejected(signed_in):
    assert signed_in.post("/api/quiz/daily/answer", json={"choice": 99}).status_code == 400
    assert signed_in.post("/api/quiz/daily/answer", json={"choice": -1}).status_code == 400


def test_streak_counts_consecutive_days_and_resets_on_a_gap(user_id):
    today = date(2026, 10, 12)
    for offset in (0, 1, 2, 4):  # a gap at day 3
        quizzes.record(user_id, f"daily:{(today - timedelta(days=offset)).isoformat()}", 1, 1,
                       today - timedelta(days=offset))
    assert quizzes.streak(user_id, today) == 3


def test_streak_survives_until_the_end_of_today(user_id):
    """Not having answered yet today must not zero a streak built through yesterday."""
    today = date(2026, 10, 12)
    for offset in (1, 2):
        quizzes.record(user_id, f"daily:{(today - timedelta(days=offset)).isoformat()}", 1, 1,
                       today - timedelta(days=offset))
    assert quizzes.streak(user_id, today) == 2
    assert quizzes.streak(user_id, today + timedelta(days=2)) == 0


# ── lesson quizzes ───────────────────────────────────────────────

def test_lesson_quiz_is_premium(signed_in):
    res = signed_in.get(LESSON)
    assert res.status_code == 402
    assert res.json()["detail"]["error"] == "premium_required"
    assert signed_in.post(LESSON, json={"answers": [0, 0]}).status_code == 402


def test_lesson_quiz_never_leaks_answers(premium):
    res = premium.get(LESSON)
    assert res.status_code == 200
    questions = res.json()["questions"]
    assert len(questions) == 2
    for q in questions:
        assert set(q) == {"question", "options"}


def test_scoring_and_pass_mark(premium):
    right = [q["answer"] for q in quizzes.lesson_questions("course-cycle-literacy", "hormones")]
    out = premium.post(LESSON, json={"answers": right}).json()
    assert out["score"] == out["total"] == 2 and out["passed"] is True
    assert all(r["correct"] and r["explanation"] for r in out["results"])

    wrong = [(a + 1) % 3 for a in right]
    out = premium.post(LESSON, json={"answers": wrong}).json()
    assert out["score"] == 0 and out["passed"] is False


def test_best_score_is_kept(premium):
    right = [q["answer"] for q in quizzes.lesson_questions("course-cycle-literacy", "hormones")]
    premium.post(LESSON, json={"answers": right})
    premium.post(LESSON, json={"answers": [(a + 1) % 3 for a in right]})
    assert premium.get(LESSON).json()["best"] == {"score": 2, "total": 2}


def test_malformed_submissions_rejected(premium):
    assert premium.post(LESSON, json={"answers": [0]}).status_code == 400          # wrong length
    assert premium.post(LESSON, json={"answers": [0, 99]}).status_code == 400      # out of range
    assert premium.get("/api/quiz/lessons/course-cycle-literacy/nope").status_code == 404
    assert premium.get("/api/quiz/lessons/no-course/hormones").status_code == 404


def test_passing_a_lesson_quiz_marks_the_lesson_complete(premium):
    right = [q["answer"] for q in quizzes.lesson_questions("course-cycle-literacy", "hormones")]
    premium.post(LESSON, json={"answers": right})
    course = next(c for c in premium.get("/api/content/courses").json()["courses"]
                  if c["id"] == "course-cycle-literacy")
    assert course["completed"] == 1


def test_stats_reports_streak_and_totals(signed_in):
    signed_in.post("/api/quiz/daily/answer", json={"choice": 0})
    stats = signed_in.get("/api/quiz/stats").json()
    assert stats["streak"] == 1 and stats["answered"] == 1


def test_quiz_results_cascade_on_account_delete(signed_in):
    signed_in.post("/api/quiz/daily/answer", json={"choice": 0})
    me = signed_in.get("/api/me").json()["user"]["id"]
    assert db.query("SELECT 1 FROM quiz_results WHERE user_id = ?", (me,))
    signed_in.delete("/api/me")
    assert db.query("SELECT 1 FROM quiz_results WHERE user_id = ?", (me,)) == []


def test_export_includes_quiz_results(signed_in):
    signed_in.post("/api/quiz/daily/answer", json={"choice": 0})
    assert len(signed_in.get("/api/me/export").json()["quiz_results"]) == 1


def test_course_paywall_no_longer_promises_video(signed_in):
    course = content.courses()[0]["id"]
    detail = signed_in.get(f"/api/content/courses/{course}").json()["detail"]
    assert "video" not in detail["feature"].lower()
