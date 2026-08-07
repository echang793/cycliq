import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))


@pytest.fixture(autouse=True)
def temp_db(tmp_path, monkeypatch):
    """Every test gets its own database file. Nothing touches ~/.cycliq."""
    monkeypatch.setenv("CYCLIQ_DB", str(tmp_path / "test.db"))
    import db

    db.close()
    db.init_db()
    yield
    db.close()


@pytest.fixture
def user_id():
    import auth

    return auth.create_user("someone@example.com", "correct horse battery")


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    import server

    return TestClient(server.app)


@pytest.fixture
def signed_in(client):
    client.post(
        "/api/auth/signup",
        json={"email": "member@example.com", "password": "correct horse battery"},
    )
    return client


@pytest.fixture
def premium(signed_in):
    signed_in.post("/api/billing/trial")
    return signed_in


def seed_periods(user_id, starts, period_len=5):
    """Insert period events from a list of date objects or ISO strings."""
    import cycle as cyc
    import db

    for start in starts:
        start = cyc.to_date(start)
        db.execute(
            "INSERT OR REPLACE INTO period_events (user_id, start_date, end_date)"
            " VALUES (?, ?, ?)",
            (user_id, cyc.iso(start), cyc.iso(start + timedelta(days=period_len - 1))),
        )


def regular_starts(n=6, length=28, first=date(2026, 1, 1)):
    return [first + timedelta(days=length * i) for i in range(n)]


os.environ.setdefault("ANTHROPIC_API_KEY", "")
