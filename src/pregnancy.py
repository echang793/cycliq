"""Pregnancy mode.

Free: due date, current week, trimester. Premium: week-by-week development,
the kick counter and the contraction timer — the "detailed pregnancy tracking"
half of the tier split.

Movement guidance here deliberately avoids a kick-count target. Current
obstetric guidance is that there is no established normal number; what matters
is a change from that baby's own pattern, reported the same day.
"""

from __future__ import annotations

import sqlite3
from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

import auth
import billing
import cycle as cyc
import db
from deps import current_user, require_premium

router = APIRouter(prefix="/api/pregnancy", tags=["pregnancy"])

GESTATION_DAYS = 280

# week: (comparison size, what is developing)
WEEKS: dict[int, tuple[str, str]] = {
    4: ("poppy seed", "The embryo implants and the placenta begins to form. A test can usually detect hCG around now."),
    5: ("sesame seed", "The neural tube — future brain and spinal cord — closes. Folic acid matters most in these weeks."),
    6: ("lentil", "A heartbeat becomes detectable on ultrasound. Nausea often starts."),
    7: ("blueberry", "Arm and leg buds appear; the brain grows fastest of any organ."),
    8: ("raspberry", "All major organ systems have begun. Fingers and toes are webbed but present."),
    9: ("grape", "The embryo becomes a fetus. Basic movement starts, far too small to feel."),
    10: ("kumquat", "Vital organs are formed and now grow. Nails and hair follicles begin."),
    11: ("fig", "Bones harden. The head is still about half the total length."),
    12: ("lime", "Reflexes develop; the fetus can open and close its fists. Nausea often eases from here."),
    13: ("pea pod", "Vocal cords form and fingerprints appear. End of the first trimester."),
    14: ("lemon", "Facial muscles work — squinting and frowning. The body starts growing faster than the head."),
    15: ("apple", "Bones become visible on scan. The fetus senses light through closed eyelids."),
    16: ("avocado", "Coordinated limb movements. Some people feel the first flutters."),
    17: ("pear", "Fat stores begin. The umbilical cord thickens and strengthens."),
    18: ("bell pepper", "Hearing develops; loud sounds may prompt movement. Anatomy scan window opens."),
    19: ("mango", "Vernix, a waxy coating, protects the skin. Sensory areas of the brain specialise."),
    20: ("banana", "Halfway. Swallowing begins, and the digestive system practises."),
    21: ("carrot", "Movements become stronger and more regular. Sleep-wake cycles emerge."),
    22: ("papaya", "Lips, eyelids and eyebrows are distinct. Grip develops."),
    23: ("grapefruit", "Rapid weight gain starts. Lungs begin developing the blood supply for breathing."),
    24: ("corn cob", "Viability threshold in most settings. Inner ear completes, so balance develops."),
    25: ("cauliflower", "Surfactant production begins, which will let the lungs inflate."),
    26: ("lettuce", "Eyes open for the first time. Responses to sound become consistent."),
    27: ("cabbage", "Regular breathing movements practise for air. End of the second trimester."),
    28: ("eggplant", "Dreaming-type brain activity appears. Fat continues to build."),
    29: ("butternut squash", "Bones are fully formed but soft; calcium demand peaks."),
    30: ("cucumber", "Amniotic fluid volume peaks and then declines as the baby grows."),
    31: ("coconut", "All five senses function. Movements feel more like rolls than kicks."),
    32: ("jicama", "Most babies turn head-down around now. Toenails complete."),
    33: ("pineapple", "Skull bones stay separate to allow moulding during birth."),
    34: ("cantaloupe", "Central nervous system and lungs mature steadily."),
    35: ("honeydew", "Most weight gain from here is fat. Space is tight, so movements change character."),
    36: ("romaine lettuce", "The baby often drops lower into the pelvis. Weekly checks usually begin."),
    37: ("chard", "Early term. Practising sucking and breathing."),
    38: ("leek", "Full term approaches. Vernix and lanugo shed into the fluid."),
    39: ("watermelon", "Full term. The brain and lungs continue maturing right up to birth."),
    40: ("small pumpkin", "Estimated due date — a midpoint, not a deadline. Only about 4% arrive today."),
}

MOVEMENT_GUIDANCE = (
    "There is no set number of movements to expect. What matters is your baby's own pattern. "
    "If movements slow, weaken or change, contact your midwife or maternity unit the same day — "
    "do not wait, and do not try cold drinks or sugar first."
)

LABOUR_GUIDANCE = (
    "Braxton Hicks tightenings are irregular, do not intensify and often stop when you change "
    "activity. Labour contractions get longer, stronger and closer together and continue regardless. "
    "Call if your waters break, if there is any bleeding, or if the fluid is green or bloody."
)


class StartIn(BaseModel):
    lmp_date: str | None = None
    due_date: str | None = None


class KickIn(BaseModel):
    session_id: int | None = None


class ContractionIn(BaseModel):
    started_at: str
    duration_s: float


def due_from_lmp(lmp: date) -> date:
    return lmp + timedelta(days=GESTATION_DAYS)


def trimester(week: int) -> int:
    if week <= 13:
        return 1
    if week <= 27:
        return 2
    return 3


def status(user_id: int, today: date | None = None) -> dict:
    today = today or date.today()
    row = db.query_one(
        "SELECT * FROM pregnancies WHERE user_id = ? AND active = 1 ORDER BY id DESC LIMIT 1",
        (user_id,),
    )
    if row is None:
        return {"active": False}

    due = cyc.to_date(row["due_date"])
    days_along = GESTATION_DAYS - (due - today).days
    week = max(0, days_along // 7)
    day_of_week = max(0, days_along % 7)
    premium = billing.is_premium(user_id)

    out = {
        "active": True,
        "id": row["id"],
        "due_date": row["due_date"],
        "lmp_date": row["lmp_date"],
        "week": week,
        "day_of_week": day_of_week,
        "days_to_due": (due - today).days,
        "trimester": trimester(week),
        "premium": premium,
    }
    detail = WEEKS.get(min(max(week, 4), 40))
    if premium and detail:
        out["size"] = detail[0]
        out["development"] = detail[1]
        out["movement_guidance"] = MOVEMENT_GUIDANCE if week >= 24 else None
        out["labour_guidance"] = LABOUR_GUIDANCE if week >= 34 else None
    elif detail:
        out["locked"] = {
            "feature": "Detailed pregnancy tracking",
            "preview": "Week-by-week development, the kick counter and the contraction timer.",
        }
    return out


@router.get("/status")
def read_status(user: sqlite3.Row = Depends(current_user)) -> dict:
    return status(user["id"])


@router.post("/start")
def start(payload: StartIn, user: sqlite3.Row = Depends(current_user)) -> dict:
    if not payload.lmp_date and not payload.due_date:
        raise HTTPException(400, detail={"error": "need_lmp_or_due_date"})
    lmp = cyc.to_date(payload.lmp_date) if payload.lmp_date else None
    due = cyc.to_date(payload.due_date) if payload.due_date else due_from_lmp(lmp)
    db.execute("UPDATE pregnancies SET active = 0 WHERE user_id = ?", (user["id"],))
    db.execute(
        "INSERT INTO pregnancies (user_id, lmp_date, due_date, active, created_at)"
        " VALUES (?, ?, ?, 1, ?)",
        (user["id"], cyc.iso(lmp) if lmp else None, cyc.iso(due), auth.now_iso()),
    )
    db.execute("UPDATE users SET mode = 'pregnancy' WHERE id = ?", (user["id"],))
    return status(user["id"])


@router.post("/end")
def end(user: sqlite3.Row = Depends(current_user)) -> dict:
    db.execute("UPDATE pregnancies SET active = 0 WHERE user_id = ?", (user["id"],))
    db.execute("UPDATE users SET mode = 'cycle' WHERE id = ?", (user["id"],))
    return {"active": False}


@router.get("/weeks")
def week_guide(user: sqlite3.Row = Depends(require_premium("Detailed pregnancy tracking"))) -> dict:
    return {
        "weeks": [
            {"week": w, "size": size, "development": text, "trimester": trimester(w)}
            for w, (size, text) in sorted(WEEKS.items())
        ],
        "movement_guidance": MOVEMENT_GUIDANCE,
        "labour_guidance": LABOUR_GUIDANCE,
    }


@router.post("/kicks")
def log_kick(payload: KickIn,
             user: sqlite3.Row = Depends(require_premium("Detailed pregnancy tracking"))) -> dict:
    if payload.session_id is None:
        session_id = db.execute(
            "INSERT INTO kick_sessions (user_id, started_at, kicks) VALUES (?, ?, 1)",
            (user["id"], auth.now_iso()),
        )
    else:
        session_id = payload.session_id
        db.execute(
            "UPDATE kick_sessions SET kicks = kicks + 1 WHERE id = ? AND user_id = ?",
            (session_id, user["id"]),
        )
    row = db.query_one("SELECT * FROM kick_sessions WHERE id = ?", (session_id,))
    if row is None:
        raise HTTPException(404, detail={"error": "not_found"})
    return {
        "session_id": row["id"],
        "kicks": row["kicks"],
        "started_at": row["started_at"],
        "guidance": MOVEMENT_GUIDANCE,
    }


@router.post("/kicks/{session_id}/end")
def end_kicks(session_id: int,
              user: sqlite3.Row = Depends(require_premium("Detailed pregnancy tracking"))) -> dict:
    db.execute(
        "UPDATE kick_sessions SET ended_at = ? WHERE id = ? AND user_id = ?",
        (auth.now_iso(), session_id, user["id"]),
    )
    return {"ended": True}


@router.post("/contractions")
def log_contraction(payload: ContractionIn,
                    user: sqlite3.Row = Depends(require_premium("Detailed pregnancy tracking"))) -> dict:
    db.execute(
        "INSERT INTO contractions (user_id, started_at, duration_s) VALUES (?, ?, ?)",
        (user["id"], payload.started_at, payload.duration_s),
    )
    return contraction_summary(user["id"])


@router.get("/contractions")
def read_contractions(
    user: sqlite3.Row = Depends(require_premium("Detailed pregnancy tracking")),
) -> dict:
    return contraction_summary(user["id"])


def contraction_summary(user_id: int, limit: int = 20) -> dict:
    rows = db.query(
        "SELECT started_at, duration_s FROM contractions WHERE user_id = ?"
        " ORDER BY started_at DESC LIMIT ?",
        (user_id, limit),
    )
    entries = [dict(r) for r in rows]
    gaps = []
    for newer, older in zip(entries, entries[1:]):
        delta = _seconds_between(older["started_at"], newer["started_at"])
        if delta > 0:
            gaps.append(delta)
    avg_gap = sum(gaps) / len(gaps) if gaps else None
    avg_len = sum(e["duration_s"] for e in entries) / len(entries) if entries else None
    return {
        "contractions": entries,
        "average_gap_s": round(avg_gap) if avg_gap else None,
        "average_duration_s": round(avg_len) if avg_len else None,
        "guidance": LABOUR_GUIDANCE,
    }


def _seconds_between(earlier: str, later: str) -> float:
    from datetime import datetime

    try:
        return (datetime.fromisoformat(later) - datetime.fromisoformat(earlier)).total_seconds()
    except ValueError:
        return 0.0
