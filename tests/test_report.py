from datetime import date, timedelta

from conftest import seed_periods

import auth
import cycle as cyc
import db
import report


def seed_six_months(user_id, today):
    starts = [today - timedelta(days=28 * i) for i in range(1, 7)]
    seed_periods(user_id, starts)
    for start in starts:
        for offset in (18, 20, 22):
            db.execute(
                "INSERT OR REPLACE INTO daily_logs (user_id, log_date, category, code, created_at)"
                " VALUES (?, ?, 'symptoms', 'sym_headache', ?)",
                (user_id, cyc.iso(start + timedelta(days=offset)), auth.now_iso()),
            )
    return starts


def test_gather_summarises_the_window(user_id):
    today = date(2026, 8, 1)
    seed_six_months(user_id, today)
    data = report.gather(user_id, today)

    assert data["months"] == 6
    assert len(data["cycles"]) == 5
    assert data["median_cycle"] == 28
    assert data["shortest"] == data["longest"] == 28
    assert data["logged_days"] == 18
    headache = next(s for s in data["top_symptoms"] if s["label"] == "Headache")
    assert headache["count"] == 18
    assert "luteal" in headache["phases"]


def test_gather_excludes_older_data(user_id):
    today = date(2026, 8, 1)
    seed_six_months(user_id, today)
    seed_periods(user_id, [date(2024, 1, 1)])
    data = report.gather(user_id, today)
    assert all(p["start"] >= data["from"] for p in data["periods"])


def test_pdf_renders(user_id):
    today = date(2026, 8, 1)
    seed_six_months(user_id, today)
    pdf = report.build_pdf(user_id, "quiet-fern-402", today)
    assert pdf.startswith(b"%PDF")
    assert len(pdf) > 2000


def test_pdf_renders_for_an_empty_account(user_id):
    pdf = report.build_pdf(user_id, "quiet-fern-402", date(2026, 8, 1))
    assert pdf.startswith(b"%PDF")


def test_report_download_over_http(premium):
    me = premium.get("/api/me").json()["user"]
    seed_six_months(me["id"], date.today())
    res = premium.get("/api/report.pdf")
    assert res.status_code == 200
    assert res.headers["content-type"] == "application/pdf"
    assert res.headers["content-disposition"].endswith('filename="cycle-report.pdf"')
    assert res.content.startswith(b"%PDF")


def test_report_carries_a_disclaimer(user_id):
    data = report.gather(user_id, date(2026, 8, 1))
    assert "not a medical record" in data["disclaimer"]


def test_saved_screener_results_appear(premium):
    me = premium.get("/api/me").json()["user"]
    db.execute(
        "INSERT INTO checker_results (user_id, tool, band, score, answers, created_at)"
        " VALUES (?, 'pcos', 'moderate', 9, '{}', ?)",
        (me["id"], auth.now_iso()),
    )
    data = report.gather(me["id"], date.today())
    assert data["checkers"][0]["tool"] == "pcos"
    assert report.build_pdf(me["id"], me["handle"], date.today()).startswith(b"%PDF")
