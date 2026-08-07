"""Daily insight cards for the Today screen.

Free accounts get phase-based cards. Premium adds cards derived from the user's
own logged history — the personalised half of the tier.
"""

from __future__ import annotations

import sqlite3
from datetime import date

from fastapi import APIRouter, Depends

import billing
import content
import cycle as cyc
import patterns
import predict as pr
import symptoms as sym
from deps import current_user

router = APIRouter(prefix="/api/insights", tags=["insights"])

PHASE_CARDS: dict[str, list[dict]] = {
    "menstrual": [
        {"title": "Why the first two days hit hardest",
         "body": "Prostaglandins peak early in the bleed, which is what drives cramping. "
                 "Anti-inflammatories work better than paracetamol here, and better still "
                 "taken at the first twinge rather than at peak pain.",
         "article": "cramps"},
        {"title": "Iron leaves with the blood",
         "body": "Heavy or long periods deplete iron faster than diet replaces it. Persistent "
                 "fatigue and breathlessness on stairs are worth a ferritin test, not just a nap.",
         "article": "iron-and-periods"},
    ],
    "follicular": [
        {"title": "Oestrogen is climbing",
         "body": "The lining is rebuilding and energy typically returns over the next week. "
                 "If you train, this is often where progressive load feels easiest — though "
                 "the research on cycle-phase training is weaker than the internet suggests.",
         "article": "exercise-and-cycle"},
        {"title": "Discharge changes on purpose",
         "body": "As oestrogen rises, cervical mucus moves from sticky to creamy to watery. "
                 "It is one of the few fertility signals you can read without a device.",
         "article": "discharge-guide"},
    ],
    "ovulatory": [
        {"title": "This is the fertile window",
         "body": "Sperm survive up to five days; an egg survives under one. The highest-"
                 "probability days are the two before release, not the day itself.",
         "article": "fertile-window"},
        {"title": "One-sided twinges are common",
         "body": "Mittelschmerz — brief one-sided pelvic pain around ovulation — affects "
                 "roughly one in five people and is harmless. Pain that is severe or lasts "
                 "days is a different thing.",
         "article": "cycle-phases"},
    ],
    "luteal": [
        {"title": "Progesterone is running the show",
         "body": "It raises your resting temperature, slows digestion (hence the bloating) "
                 "and can fragment sleep. All of it reverses within a day or two of bleeding.",
         "article": "sleep-and-hormones"},
        {"title": "Mood shifts here have a mechanism",
         "body": "Both hormones act on serotonin and GABA systems. If low mood or irritability "
                 "reliably clusters in this phase and lifts when bleeding starts, that timing "
                 "is exactly what makes it diagnosable.",
         "article": "pms-vs-pmdd"},
    ],
}

NO_DATA_CARD = {
    "title": "Log your last period to start",
    "body": "Predictions are anchored to period start dates. One logged period gives a rough "
            "window; two gives real numbers; six makes it tight.",
    "article": "tracking-well",
}


def _card(payload: dict, kind: str, locked: bool = False) -> dict:
    article = content.article_by_id(payload.get("article", "")) if payload.get("article") else None
    return {
        "title": payload["title"],
        "body": payload["body"],
        "kind": kind,
        "locked": locked,
        "article_id": article["id"] if article else None,
        "article_title": article["title"] if article else None,
    }


def _prediction_card(prediction: pr.Prediction) -> dict:
    if prediction.next_period is None:
        return _card(NO_DATA_CARD, "prediction")
    days = prediction.days_to_period
    if days is None:
        window = "soon"
    elif days < 0:
        window = f"{abs(days)} day{'s' if abs(days) != 1 else ''} later than expected"
    elif days == 0:
        window = "expected today"
    else:
        window = f"in about {days} day{'s' if days != 1 else ''}"
    return _card(
        {
            "title": f"Next period {window}",
            "body": (
                f"Window: {prediction.next_period_low} to {prediction.next_period_high}. "
                f"{prediction.note}"
            ),
            "article": "cycle-length-normal",
        },
        "prediction",
    )


def _premium_cards(user_id: int, today: date) -> list[dict]:
    out: list[dict] = []
    found = patterns.compute(user_id, today)
    if found.get("ready") and found["patterns"]:
        top = found["patterns"][0]
        out.append(_card(
            {"title": "A pattern in your own logs", "body": top["sentence"]},
            "pattern",
        ))
    trend = patterns.trends(user_id)
    if trend.get("ready"):
        out.append(_card(
            {"title": f"Your cycles are {trend['direction']}", "body": trend["message"]},
            "trend",
        ))
    forecast = patterns.forecast(user_id, today, days=7)
    if forecast.get("ready"):
        upcoming = [d for d in forecast["days"] if d["likely"]]
        if upcoming:
            first = upcoming[0]
            labels = ", ".join(item["label"].lower() for item in first["likely"])
            out.append(_card(
                {
                    "title": "What you often log around now",
                    "body": f"On {first['date']} you'll be in your {first['phase']} phase, "
                            f"where you have most often logged {labels}.",
                },
                "forecast",
            ))
    return out


def _locked_previews() -> list[dict]:
    return [
        _card({"title": "A pattern in your own logs",
               "body": "Premium finds which symptoms cluster in which phase of your cycle, "
                       "measured against your own baseline."}, "pattern", locked=True),
        _card({"title": "Cycle trends",
               "body": "See whether your cycles are lengthening, shortening or holding steady "
                       "across the last year."}, "trend", locked=True),
    ]


def build(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    prediction = pr.predict(user_id, today)
    premium = billing.is_premium(user_id)

    cards = [_prediction_card(prediction)]
    for payload in PHASE_CARDS.get(prediction.phase or "", []):
        cards.append(_card(payload, "phase"))

    logged_today = sym.day_log(user_id, today)["entries"]
    if not logged_today:
        cards.append(_card(
            {"title": "Nothing logged today",
             "body": "A small consistent set logged daily is worth more than everything "
                     "logged occasionally — a symptom only entered on bad days makes every "
                     "day look bad.",
             "article": "tracking-well"},
            "nudge",
        ))

    cards.extend(_premium_cards(user_id, today) if premium else _locked_previews())

    return {
        "date": cyc.iso(today),
        "premium": premium,
        "prediction": prediction.as_dict(),
        "logged_today": len(logged_today),
        "cards": cards,
    }


@router.get("/today")
def read_today(user: sqlite3.Row = Depends(current_user)) -> dict:
    return build(user["id"])
