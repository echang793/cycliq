"""The trackable taxonomy (90+ symptoms and events) plus daily-log storage.

`CATALOG` is the single source of truth: the logging sheet in the UI, the
pattern engine, the doctor's report and the export all read from it, so adding
a symptom in one place adds it everywhere.
"""

from __future__ import annotations

from datetime import date

import auth
import db
import cycle as cyc

# kind: "choice" = pick one per day, "multi" = pick many, "number" = numeric value
CATALOG: dict[str, dict] = {
    "flow": {
        "label": "Menstrual flow",
        "kind": "choice",
        "codes": {
            "flow_none": "No flow",
            "flow_spotting": "Spotting",
            "flow_light": "Light",
            "flow_medium": "Medium",
            "flow_heavy": "Heavy",
            "flow_clots": "Blood clots",
        },
    },
    "mood": {
        "label": "Mood",
        "kind": "multi",
        "codes": {
            "mood_calm": "Calm",
            "mood_happy": "Happy",
            "mood_energetic": "Energetic",
            "mood_swings": "Mood swings",
            "mood_irritable": "Irritable",
            "mood_sad": "Sad",
            "mood_anxious": "Anxious",
            "mood_low": "Very low",
            "mood_apathetic": "Apathetic",
            "mood_confused": "Confused",
            "mood_self_critical": "Self-critical",
            "mood_obsessive": "Obsessive thoughts",
            "mood_guilty": "Guilt",
            "mood_restless": "Restless",
        },
    },
    "symptoms": {
        "label": "Symptoms",
        "kind": "multi",
        "codes": {
            "sym_none": "Everything is fine",
            "sym_cramps": "Cramps",
            "sym_pelvic_pain": "Pelvic pain",
            "sym_ovulation_pain": "Ovulation pain",
            "sym_tender_breasts": "Tender breasts",
            "sym_breast_lump": "Breast lump",
            "sym_headache": "Headache",
            "sym_migraine": "Migraine",
            "sym_backache": "Backache",
            "sym_joint_pain": "Joint pain",
            "sym_leg_cramps": "Leg cramps",
            "sym_acne": "Acne",
            "sym_fatigue": "Fatigue",
            "sym_insomnia": "Insomnia",
            "sym_brain_fog": "Brain fog",
            "sym_dizziness": "Dizziness",
            "sym_palpitations": "Palpitations",
            "sym_bloating": "Bloating",
            "sym_nausea": "Nausea",
            "sym_vomiting": "Vomiting",
            "sym_heartburn": "Heartburn",
            "sym_diarrhea": "Diarrhea",
            "sym_constipation": "Constipation",
            "sym_gas": "Gas",
            "sym_painful_bowel": "Pain when passing stool",
            "sym_painful_urination": "Pain when urinating",
            "sym_cravings": "Food cravings",
            "sym_food_aversion": "Food aversion",
            "sym_smell_sensitivity": "Sensitivity to smell",
            "sym_hot_flashes": "Hot flashes",
            "sym_night_sweats": "Night sweats",
            "sym_chills": "Chills",
            "sym_fever": "Fever",
            "sym_swelling": "Swelling",
            "sym_hair_loss": "Hair loss",
            "sym_excess_hair": "Excess hair growth",
            "sym_vaginal_itching": "Vaginal itching",
            "sym_vaginal_dryness": "Vaginal dryness",
            "sym_painful_sex": "Pain during sex",
            "sym_sore_throat": "Sore throat",
        },
    },
    "discharge": {
        "label": "Vaginal discharge",
        "kind": "choice",
        "codes": {
            "dis_none": "No discharge",
            "dis_creamy": "Creamy",
            "dis_watery": "Watery",
            "dis_sticky": "Sticky",
            "dis_egg_white": "Egg white",
            "dis_spotting": "Spotting",
            "dis_gray": "Gray",
            "dis_clumpy": "Clumpy white",
            "dis_unusual": "Unusual",
        },
    },
    "sex": {
        "label": "Sex and drive",
        "kind": "multi",
        "codes": {
            "sex_none": "No sex",
            "sex_protected": "Protected sex",
            "sex_unprotected": "Unprotected sex",
            "sex_masturbation": "Masturbation",
            "sex_orgasm": "Orgasm",
            "sex_drive_high": "High sex drive",
            "sex_drive_neutral": "Neutral sex drive",
            "sex_drive_low": "Low sex drive",
        },
    },
    "tests": {
        "label": "Tests",
        "kind": "multi",
        "codes": {
            "ovulation_test_pos": "Ovulation test: positive",
            "ovulation_test_neg": "Ovulation test: negative",
            "pregnancy_test_pos": "Pregnancy test: positive",
            "pregnancy_test_neg": "Pregnancy test: negative",
        },
    },
    "lifestyle": {
        "label": "Lifestyle",
        "kind": "multi",
        "codes": {
            "life_travel": "Travel",
            "life_stress": "Stress",
            "life_illness": "Illness or injury",
            "life_alcohol": "Alcohol",
            "life_smoking": "Smoking",
            "life_meditation": "Meditation",
            "life_yoga": "Yoga",
            "life_gym": "Gym",
            "life_running": "Running",
            "life_cycling": "Cycling",
            "life_swimming": "Swimming",
            "life_team_sport": "Team sport",
            "life_no_exercise": "No exercise",
        },
    },
    "medication": {
        "label": "Medication",
        "kind": "multi",
        "codes": {
            "med_pill_taken": "Birth control taken",
            "med_pill_missed": "Birth control missed",
            "med_other": "Other medication",
            "med_supplement": "Supplement",
        },
    },
    "vitals": {
        "label": "Measurements",
        "kind": "number",
        "codes": {
            "bbt": "Basal body temperature (°C)",
            "weight": "Weight (kg)",
            "water": "Water (glasses)",
            "sleep": "Sleep (hours)",
            "steps": "Steps",
        },
    },
    "notes": {
        "label": "Notes",
        "kind": "text",
        "codes": {"note": "Note"},
    },
}

CODE_TO_CATEGORY: dict[str, str] = {
    code: category for category, spec in CATALOG.items() for code in spec["codes"]
}
CODE_LABELS: dict[str, str] = {
    code: label for spec in CATALOG.values() for code, label in spec["codes"].items()
}
# Codes that are meaningful to correlate with cycle phase (a "no symptoms"
# marker or a numeric reading is not a symptom occurrence).
PATTERN_CODES: list[str] = [
    code
    for code in CODE_LABELS
    if CODE_TO_CATEGORY[code] in {"mood", "symptoms", "discharge", "flow"}
    and code not in {"sym_none", "flow_none", "dis_none"}
]


def catalog_payload() -> dict:
    return {
        "categories": [
            {
                "key": key,
                "label": spec["label"],
                "kind": spec["kind"],
                "options": [{"code": c, "label": lbl} for c, lbl in spec["codes"].items()],
            }
            for key, spec in CATALOG.items()
        ],
        "total_trackable": len(CODE_LABELS),
    }


class LogError(Exception):
    pass


def log_entry(
    user_id: int,
    log_date: date | str,
    code: str,
    value: float | None = None,
    text: str | None = None,
) -> None:
    category = CODE_TO_CATEGORY.get(code)
    if category is None:
        raise LogError(f"Unknown tracking code: {code}")
    day = cyc.iso(cyc.to_date(log_date))

    if CATALOG[category]["kind"] == "choice":
        # One value per day for single-choice categories.
        db.execute(
            "DELETE FROM daily_logs WHERE user_id = ? AND log_date = ? AND category = ?",
            (user_id, day, category),
        )
    db.execute(
        "INSERT INTO daily_logs (user_id, log_date, category, code, value, text, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)"
        " ON CONFLICT(user_id, log_date, category, code)"
        " DO UPDATE SET value = excluded.value, text = excluded.text",
        (user_id, day, category, code, value, text, auth.now_iso()),
    )


def unlog_entry(user_id: int, log_date: date | str, code: str) -> None:
    db.execute(
        "DELETE FROM daily_logs WHERE user_id = ? AND log_date = ? AND code = ?",
        (user_id, cyc.iso(cyc.to_date(log_date)), code),
    )


def day_log(user_id: int, log_date: date | str) -> dict:
    day = cyc.iso(cyc.to_date(log_date))
    rows = db.query(
        "SELECT category, code, value, text FROM daily_logs"
        " WHERE user_id = ? AND log_date = ?",
        (user_id, day),
    )
    return {
        "date": day,
        "entries": [
            {
                "category": r["category"],
                "code": r["code"],
                "label": CODE_LABELS.get(r["code"], r["code"]),
                "value": r["value"],
                "text": r["text"],
            }
            for r in rows
        ],
    }


def range_log(user_id: int, start: date | str, end: date | str) -> list[dict]:
    rows = db.query(
        "SELECT log_date, category, code, value, text FROM daily_logs"
        " WHERE user_id = ? AND log_date >= ? AND log_date <= ? ORDER BY log_date",
        (user_id, cyc.iso(cyc.to_date(start)), cyc.iso(cyc.to_date(end))),
    )
    return [dict(r) for r in rows]
