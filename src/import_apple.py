"""Apple Health export parser.

The best-supported import route. Flo and most other trackers write cycle data
to HealthKit continuously, the category identifiers are documented and stable,
and the user can produce the export themselves in two minutes instead of
waiting on a support request.

Exports are large — hundreds of MB is normal — so records are streamed with
iterparse rather than loaded into a tree.
"""

from __future__ import annotations

import io
import zipfile
from xml.etree import ElementTree

from import_staging import ImportError_, Staged, derive_starts, parse_day

APPLE_FLOW = {
    "HKCategoryValueMenstrualFlowNone": "flow_none",
    "HKCategoryValueMenstrualFlowUnspecified": "flow_medium",
    "HKCategoryValueMenstrualFlowLight": "flow_light",
    "HKCategoryValueMenstrualFlowMedium": "flow_medium",
    "HKCategoryValueMenstrualFlowHeavy": "flow_heavy",
}

APPLE_MUCUS = {
    "HKCategoryValueCervicalMucusQualityDry": "dis_none",
    "HKCategoryValueCervicalMucusQualitySticky": "dis_sticky",
    "HKCategoryValueCervicalMucusQualityCreamy": "dis_creamy",
    "HKCategoryValueCervicalMucusQualityWatery": "dis_watery",
    "HKCategoryValueCervicalMucusQualityEggWhite": "dis_egg_white",
}

APPLE_OVULATION = {
    "HKCategoryValueOvulationTestResultLuteinizingHormoneSurge": "ovulation_test_pos",
    "HKCategoryValueOvulationTestResultPositive": "ovulation_test_pos",
    "HKCategoryValueOvulationTestResultNegative": "ovulation_test_neg",
}

APPLE_PREGNANCY = {
    "HKCategoryValuePregnancyTestResultPositive": "pregnancy_test_pos",
    "HKCategoryValuePregnancyTestResultNegative": "pregnancy_test_neg",
}

# Category identifier suffix (after the Apple prefix) -> our code.
APPLE_SYMPTOMS = {
    "AbdominalCramps": "sym_cramps",
    "Acne": "sym_acne",
    "AppetiteChanges": "sym_cravings",
    "Bloating": "sym_bloating",
    "BreastPain": "sym_tender_breasts",
    "Chills": "sym_chills",
    "Constipation": "sym_constipation",
    "Diarrhea": "sym_diarrhea",
    "Dizziness": "sym_dizziness",
    "Fainting": "sym_dizziness",
    "Fatigue": "sym_fatigue",
    "Fever": "sym_fever",
    "GeneralizedBodyAche": "sym_joint_pain",
    "HairLoss": "sym_hair_loss",
    "Headache": "sym_headache",
    "Heartburn": "sym_heartburn",
    "HotFlashes": "sym_hot_flashes",
    "LowerBackPain": "sym_backache",
    "MemoryLapse": "sym_brain_fog",
    "MoodChanges": "mood_swings",
    "Nausea": "sym_nausea",
    "NightSweats": "sym_night_sweats",
    "PelvicPain": "sym_pelvic_pain",
    "RapidPoundingHeartbeat": "sym_palpitations",
    "SleepChanges": "sym_insomnia",
    "SoreThroat": "sym_sore_throat",
    "VaginalDryness": "sym_vaginal_dryness",
    "Vomiting": "sym_vomiting",
}

APPLE_ABSENT = {
    "HKCategoryValueSeverityNotPresent",
    "HKCategoryValuePresenceNotPresent",
    "HKCategoryValueNotApplicable",
}

TRUE_VALUES = ("1", "true", "True")
FALSE_VALUES = ("0", "false", "False")


def unwrap(raw: bytes) -> bytes:
    """Health hands you a zip containing apple_health_export/export.xml."""
    if raw[:2] != b"PK":
        return raw
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        names = [n for n in archive.namelist() if n.endswith("export.xml")]
        if not names:
            raise ImportError_("That zip has no export.xml in it.")
        names.sort(key=len)  # prefer export.xml over export_cda.xml
        return archive.read(names[0])


def to_celsius(value: str, unit: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if "F" in unit:
        return round((number - 32) * 5 / 9, 2)
    return round(number, 2)


def to_kilos(value: str, unit: str) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if unit.startswith("lb"):
        return round(number * 0.45359237, 2)
    return round(number, 2)


def parse(raw: bytes) -> Staged:
    staged = Staged(source="apple_health")
    cycle_start_days: set[str] = set()

    for _, element in ElementTree.iterparse(io.BytesIO(unwrap(raw)), events=("end",)):
        if element.tag != "Record":
            # Deliberately not cleared. MetadataEntry children fire their own end
            # event before the parent Record does, and clearing one wipes the
            # attributes the Record handler is about to read — which silently
            # loses HKMenstrualCycleStart and the sexual-activity protection flag.
            continue

        day = parse_day(element.get("startDate"))
        if day is None:
            staged.skipped["record with no usable date"] += 1
            element.clear()
            continue

        value = element.get("value", "")
        metadata = {
            child.get("key"): child.get("value") for child in element.findall("MetadataEntry")
        }
        short = (
            element.get("type", "")
            .replace("HKCategoryTypeIdentifier", "")
            .replace("HKQuantityTypeIdentifier", "")
        )

        _absorb(short, day, value, metadata, element.get("unit", ""), staged, cycle_start_days)
        element.clear()

    staged.period_starts = cycle_start_days or derive_starts(staged.period_days)
    if not cycle_start_days and staged.period_days:
        staged.warnings.append(
            "No HKMenstrualCycleStart flags in this export, so period starts were "
            "inferred from breaks in the flow records."
        )
    return staged


def _absorb(
    short: str,
    day: str,
    value: str,
    metadata: dict,
    unit: str,
    staged: Staged,
    cycle_start_days: set[str],
) -> None:
    if short == "MenstrualFlow":
        code = APPLE_FLOW.get(value)
        if code:
            if code != "flow_none":
                staged.period_days.add(day)
            staged.log(day, code)
        if metadata.get("HKMenstrualCycleStart") in TRUE_VALUES:
            cycle_start_days.add(day)

    elif short == "IntermenstrualBleeding":
        if value not in APPLE_ABSENT:
            staged.log(day, "dis_spotting")

    elif short == "CervicalMucusQuality":
        code = APPLE_MUCUS.get(value)
        if code:
            staged.log(day, code)

    elif short == "OvulationTestResult":
        code = APPLE_OVULATION.get(value)
        if code:
            staged.log(day, code)
        else:
            staged.skipped["ovulation test: indeterminate or estrogen surge"] += 1

    elif short == "PregnancyTestResult":
        code = APPLE_PREGNANCY.get(value)
        if code:
            staged.log(day, code)

    elif short == "SexualActivity":
        protection = metadata.get("HKSexualActivityProtectionUsed")
        if protection in TRUE_VALUES:
            staged.log(day, "sex_protected")
        elif protection in FALSE_VALUES:
            staged.log(day, "sex_unprotected")
        else:
            staged.skipped["sexual activity with no protection metadata"] += 1

    elif short == "BasalBodyTemperature":
        celsius = to_celsius(value, unit)
        if celsius is not None:
            staged.log(day, "bbt", celsius)

    elif short == "BodyMass":
        kilos = to_kilos(value, unit)
        if kilos is not None:
            staged.log(day, "weight", kilos)

    elif short in APPLE_SYMPTOMS:
        if value in APPLE_ABSENT:
            staged.skipped["symptom recorded as not present"] += 1
        else:
            staged.log(day, APPLE_SYMPTOMS[short])

    else:
        staged.skipped[f"unsupported record type: {short}"] += 1
