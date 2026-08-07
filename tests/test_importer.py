"""Import from Apple Health, an unknown-schema JSON export, and CSV.

The Flo-shaped fixtures below are invented, because Flo's export schema is not
published. That is the point of the tests: the parser has to work on a document
whose exact key names it has never seen.
"""

import io
import json
import zipfile
from datetime import date, timedelta

import pytest

import cycle as cyc
import db
import importer
import symptoms as sym


# ── fixtures ─────────────────────────────────────────────────────

def health_xml(records: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<HealthData locale=\"en_GB\">\n" + records + "\n</HealthData>"
    ).encode()


def record(type_, start, value, unit=None, metadata=None) -> str:
    attrs = f'type="{type_}" startDate="{start} 08:00:00 +0000" endDate="{start} 08:00:00 +0000" value="{value}"'
    if unit:
        attrs += f' unit="{unit}"'
    if metadata:
        inner = "".join(f'<MetadataEntry key="{k}" value="{v}"/>' for k, v in metadata.items())
        return f"<Record {attrs}>{inner}</Record>"
    return f"<Record {attrs}/>"


def apple_export(cycles=3, start=date(2026, 1, 5), length=28) -> bytes:
    rows = []
    for i in range(cycles):
        first = start + timedelta(days=length * i)
        for offset, flow in enumerate(["Heavy", "Heavy", "Medium", "Light", "Light"]):
            day = (first + timedelta(days=offset)).isoformat()
            meta = {"HKMenstrualCycleStart": "1"} if offset == 0 else None
            rows.append(record(
                "HKCategoryTypeIdentifierMenstrualFlow", day,
                f"HKCategoryValueMenstrualFlow{flow}", metadata=meta,
            ))
        rows.append(record("HKCategoryTypeIdentifierAbdominalCramps",
                           (first + timedelta(days=1)).isoformat(),
                           "HKCategoryValueSeveritySevere"))
        rows.append(record("HKCategoryTypeIdentifierHeadache",
                           (first + timedelta(days=20)).isoformat(),
                           "HKCategoryValueSeverityMild"))
        rows.append(record("HKCategoryTypeIdentifierCervicalMucusQuality",
                           (first + timedelta(days=13)).isoformat(),
                           "HKCategoryValueCervicalMucusQualityEggWhite"))
        rows.append(record("HKCategoryTypeIdentifierOvulationTestResult",
                           (first + timedelta(days=13)).isoformat(),
                           "HKCategoryValueOvulationTestResultLuteinizingHormoneSurge"))
        rows.append(record("HKQuantityTypeIdentifierBasalBodyTemperature",
                           (first + timedelta(days=16)).isoformat(), "36.72", unit="degC"))
    return health_xml("\n".join(rows))


FLO_SHAPED = {
    "user": {"id": "abc-123", "birthday": "1993-04-11"},
    "cycles": [
        {"period_start_date": "2026-01-05", "period_end_date": "2026-01-09"},
        {"period_start_date": "2026-02-02", "period_end_date": "2026-02-06"},
        {"period_start_date": "2026-03-02", "period_end_date": "2026-03-06"},
    ],
    "point_events": [
        {"date": "2026-01-06", "category": "symptom", "subtype": "Cramps"},
        {"date": "2026-01-06", "category": "menstrual_flow", "subtype": "Heavy flow"},
        {"date": "2026-01-25", "category": "mood", "subtype": "Mood swings"},
        {"date": "2026-01-25", "category": "symptom", "subtype": "Bloating"},
        {"date": "2026-02-18", "category": "fluid", "subtype": "Egg white"},
        {"date": "2026-02-18", "category": "ovulation_test", "subtype": "Positive"},
        {"date": "2026-02-19", "basal_temperature": 36.7},
        {"date": "2026-02-20", "category": "unknowable", "subtype": "Sputnik"},
    ],
}

CSV_TEXT = """date,flow,symptom,mood,bbt
2026-01-05,Heavy,Cramps,Irritable,36.4
2026-01-06,Medium,Cramps,,36.35
2026-01-07,Light,,Calm,36.4
2026-02-02,Heavy,Cramps,,36.42
2026-02-03,Medium,,,36.38
"""


# ── date parsing ─────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("2026-03-04", "2026-03-04"),
    ("2026-03-04 08:12:00 +0000", "2026-03-04"),
    ("2026-03-04T08:12:00Z", "2026-03-04"),
    (1772582400, "2026-03-04"),          # epoch seconds
    (1772582400000, "2026-03-04"),       # epoch millis
    ("04/03/2026", "2026-03-04"),
])
def test_parse_day_accepts_the_formats_exports_use(raw, expected):
    assert importer.parse_day(raw) == expected


@pytest.mark.parametrize("raw", ["", None, True, "hello", 42, "0000-01-01", "1780-01-01"])
def test_parse_day_rejects_non_dates(raw):
    assert importer.parse_day(raw) is None


# ── detection ────────────────────────────────────────────────────

def test_detection():
    assert importer.detect(apple_export(1)) == "apple_health"
    assert importer.detect(json.dumps(FLO_SHAPED).encode()) == "json"
    assert importer.detect(CSV_TEXT.encode(), "flo.csv") == "csv"
    with pytest.raises(importer.ImportError_):
        importer.detect(b"\x00\x01\x02binary garbage")


def test_zipped_health_export_is_unwrapped():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("apple_health_export/export.xml", apple_export(2))
        archive.writestr("apple_health_export/export_cda.xml", "<ignored/>")
    raw = buffer.getvalue()
    assert importer.detect(raw) == "apple_health"
    staged = importer.parse(raw)
    assert len(staged.period_starts) == 2


def test_zip_without_an_export_is_rejected():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("photos/cat.jpg", "not health data")
    with pytest.raises(importer.ImportError_, match="no export.xml"):
        importer.parse(buffer.getvalue())


# ── Apple Health ─────────────────────────────────────────────────

def test_apple_health_maps_the_documented_identifiers():
    staged = importer.parse(apple_export(3))
    assert staged.source == "apple_health"
    assert staged.period_starts == {"2026-01-05", "2026-02-02", "2026-03-02"}
    assert len(staged.period_days) == 15

    codes = {code for _, code in staged.logs}
    assert {"flow_heavy", "flow_medium", "flow_light", "sym_cramps", "sym_headache",
            "dis_egg_white", "ovulation_test_pos", "bbt"} <= codes
    assert staged.logs[("2026-01-21", "bbt")][0] == 36.72


def test_fahrenheit_and_pounds_are_converted():
    xml = health_xml("\n".join([
        record("HKQuantityTypeIdentifierBasalBodyTemperature", "2026-01-10", "98.24", unit="degF"),
        record("HKQuantityTypeIdentifierBodyMass", "2026-01-10", "150", unit="lb"),
    ]))
    staged = importer.parse(xml)
    assert staged.logs[("2026-01-10", "bbt")][0] == 36.8
    assert staged.logs[("2026-01-10", "weight")][0] == 68.04


def test_absent_symptoms_are_not_imported():
    xml = health_xml(record("HKCategoryTypeIdentifierHeadache", "2026-01-10",
                            "HKCategoryValueSeverityNotPresent"))
    staged = importer.parse(xml)
    assert staged.logs == {}
    assert any("not present" in reason for reason, _ in staged.skipped.items())


def test_sexual_activity_needs_protection_metadata():
    xml = health_xml("\n".join([
        record("HKCategoryTypeIdentifierSexualActivity", "2026-01-10", "0",
               metadata={"HKSexualActivityProtectionUsed": "0"}),
        record("HKCategoryTypeIdentifierSexualActivity", "2026-01-11", "0",
               metadata={"HKSexualActivityProtectionUsed": "1"}),
        record("HKCategoryTypeIdentifierSexualActivity", "2026-01-12", "0"),
    ]))
    staged = importer.parse(xml)
    assert ("2026-01-10", "sex_unprotected") in staged.logs
    assert ("2026-01-11", "sex_protected") in staged.logs
    assert not any(day == "2026-01-12" for day, _ in staged.logs)


def test_period_starts_inferred_when_the_flag_is_missing():
    rows = []
    for first in (date(2026, 1, 5), date(2026, 2, 2)):
        for offset in range(4):
            rows.append(record("HKCategoryTypeIdentifierMenstrualFlow",
                               (first + timedelta(days=offset)).isoformat(),
                               "HKCategoryValueMenstrualFlowMedium"))
    staged = importer.parse(health_xml("\n".join(rows)))
    assert staged.period_starts == {"2026-01-05", "2026-02-02"}
    assert any("inferred" in w for w in staged.warnings)


def test_unsupported_record_types_are_counted_not_dropped_silently():
    xml = health_xml(record("HKQuantityTypeIdentifierStepCount", "2026-01-10", "8000",
                            unit="count"))
    staged = importer.parse(xml)
    assert any("StepCount" in reason for reason, _ in staged.skipped.items())


# ── unknown-schema JSON ──────────────────────────────────────────

def test_flo_shaped_json_is_sniffed():
    staged = importer.parse(json.dumps(FLO_SHAPED).encode())
    assert staged.period_starts == {"2026-01-05", "2026-02-02", "2026-03-02"}
    codes = {code for _, code in staged.logs}
    assert {"sym_cramps", "flow_heavy", "mood_swings", "sym_bloating",
            "dis_egg_white", "ovulation_test_pos", "bbt"} <= codes
    assert staged.logs[("2026-02-19", "bbt")][0] == 36.7


def test_unknown_values_are_reported_rather_than_guessed():
    staged = importer.parse(json.dumps(FLO_SHAPED).encode())
    reasons = " ".join(reason for reason, _ in staged.skipped.items())
    assert "Sputnik" in reasons


def test_unknown_schema_carries_a_health_warning():
    staged = importer.parse(json.dumps(FLO_SHAPED).encode())
    assert any("best guess" in w for w in staged.warnings)


def test_epoch_timestamps_are_handled():
    document = {"events": [
        {"timestamp": 1767571200000, "type": "period_start"},
        {"timestamp": 1767657600000, "symptom": "Headache"},
    ]}
    staged = importer.parse(json.dumps(document).encode())
    assert staged.period_starts == {"2026-01-05"}
    assert ("2026-01-06", "sym_headache") in staged.logs


def test_json_with_nothing_recognisable_is_rejected_with_a_hint():
    with pytest.raises(importer.ImportError_, match="Top-level paths"):
        importer.parse(json.dumps({"settings": {"theme": "dark", "units": "metric"}}).encode())


def test_broken_json_names_the_line():
    with pytest.raises(importer.ImportError_, match="not valid JSON"):
        importer.parse(b'{"cycles": [')


def test_our_own_export_round_trips(signed_in):
    signed_in.post("/api/periods", json={"start_date": "2026-01-05", "end_date": "2026-01-09"})
    signed_in.post("/api/log", json={"date": "2026-01-06", "code": "sym_cramps"})
    signed_in.post("/api/log", json={"date": "2026-01-06", "code": "bbt", "value": 36.5})
    export = signed_in.get("/api/me/export").json()

    staged = importer.parse(json.dumps(export).encode())
    assert staged.source == "cycliq_export"
    assert staged.period_starts == {"2026-01-05"}
    assert staged.period_days == {f"2026-01-0{d}" for d in range(5, 10)}
    assert staged.logs[("2026-01-06", "bbt")][0] == 36.5


# ── CSV ──────────────────────────────────────────────────────────

def test_csv_columns_are_matched_by_value():
    staged = importer.parse(CSV_TEXT.encode(), "export.csv")
    assert staged.period_starts == {"2026-01-05", "2026-02-02"}
    assert ("2026-01-05", "flow_heavy") in staged.logs
    assert ("2026-01-05", "mood_irritable") in staged.logs
    assert staged.logs[("2026-01-06", "bbt")][0] == 36.35


def test_semicolon_csv_is_handled():
    staged = importer.parse(CSV_TEXT.replace(",", ";").encode(), "export.csv")
    assert staged.period_starts == {"2026-01-05", "2026-02-02"}


def test_csv_without_a_date_column_is_rejected():
    with pytest.raises(importer.ImportError_, match="No date column"):
        importer.parse(b"flow,mood\nHeavy,Calm\n", "x.csv")


# ── applying ─────────────────────────────────────────────────────

def test_apply_writes_periods_and_logs(user_id):
    staged = importer.parse(apple_export(3))
    result = importer.apply(user_id, staged)
    assert result["periods_added"] == 3
    assert result["logs_added"] == len(staged.logs)

    periods = cyc.list_periods(user_id)
    assert [cyc.iso(p.start) for p in periods] == ["2026-01-05", "2026-02-02", "2026-03-02"]
    assert periods[0].length == 5  # end date derived from the run of flow days


def test_applying_twice_changes_nothing(user_id):
    staged = importer.parse(apple_export(3))
    importer.apply(user_id, staged)
    before = importer.existing_counts(user_id)
    second = importer.apply(user_id, importer.parse(apple_export(3)))
    assert second["periods_added"] == 0
    assert second["logs_added"] == 0
    assert importer.existing_counts(user_id) == before


def test_imported_data_drives_predictions(user_id):
    import predict as pr

    importer.apply(user_id, importer.parse(apple_export(6, date(2026, 1, 5), 29)))
    prediction = pr.predict(user_id, date(2026, 6, 1))
    assert prediction.source == "history"
    assert prediction.cycle_len == 29
    assert prediction.n_cycles == 5
    # The export's LH tests fall on cycle day 14, so ovulation lands on day 15
    # and the luteal phase comes out measured (29 - 14) rather than assumed.
    assert prediction.luteal_len == 15
    assert "measured from 5 of your own cycles" in prediction.note


def test_unmapped_codes_never_reach_the_database(user_id):
    staged = importer.Staged()
    staged.period_starts.add("2026-01-05")
    staged.log("2026-01-06", "sym_not_a_real_code")
    assert staged.logs == {}
    importer.apply(user_id, staged)
    assert db.query("SELECT * FROM daily_logs WHERE user_id = ?", (user_id,)) == []


def test_every_mapped_code_exists_in_the_catalog():
    mapped = (
        set(importer.APPLE_FLOW.values()) | set(importer.APPLE_MUCUS.values())
        | set(importer.APPLE_OVULATION.values()) | set(importer.APPLE_PREGNANCY.values())
        | set(importer.APPLE_SYMPTOMS.values())
        | {code for _, code in importer.VALUE_HINTS}
        | {code for _, code in importer.NUMERIC_HINTS}
    )
    unknown = mapped - set(sym.CODE_TO_CATEGORY)
    assert unknown == set()


# ── routes ───────────────────────────────────────────────────────

def test_preview_then_apply_over_http(signed_in):
    files = {"file": ("export.xml", apple_export(3), "text/xml")}
    preview = signed_in.post("/api/import/preview", files=files).json()
    assert preview["preview"]["period_start_count"] == 3
    assert preview["preview"]["date_range"][0] == "2026-01-05"
    assert preview["existing"] == {"periods": 0, "logs": 0}
    # Preview alone must not write.
    assert signed_in.get("/api/periods").json()["periods"] == []

    applied = signed_in.post("/api/import/apply").json()
    assert applied["periods_added"] == 3
    assert len(signed_in.get("/api/periods").json()["periods"]) == 3


def test_apply_without_a_preview_is_rejected(signed_in):
    res = signed_in.post("/api/import/apply")
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "nothing_staged"


def test_unparseable_upload_returns_the_reason(signed_in):
    files = {"file": ("junk.json", b'{"nope": 1}', "application/json")}
    res = signed_in.post("/api/import/preview", files=files)
    assert res.status_code == 400
    assert res.json()["detail"]["error"] == "parse_failed"
    assert res.json()["detail"]["message"]


def test_empty_upload_rejected(signed_in):
    res = signed_in.post("/api/import/preview", files={"file": ("empty.csv", b"", "text/csv")})
    assert res.status_code == 400


def test_one_shot_upload_needs_confirm(signed_in):
    files = {"file": ("export.xml", apple_export(2), "text/xml")}
    out = signed_in.post("/api/import/upload", files=files, data={"confirm": "false"}).json()
    assert out["applied"] is False
    assert signed_in.get("/api/periods").json()["periods"] == []

    files = {"file": ("export.xml", apple_export(2), "text/xml")}
    out = signed_in.post("/api/import/upload", files=files, data={"confirm": "true"}).json()
    assert out["applied"] is True and out["periods_added"] == 2


def test_import_requires_a_session(client):
    assert client.get("/api/import/guide").status_code == 200
    assert client.post("/api/import/apply").status_code == 401
    res = client.post("/api/import/preview", files={"file": ("x.csv", CSV_TEXT.encode(), "text/csv")})
    assert res.status_code == 401


def test_guide_names_the_real_flo_route():
    guide = importer.guide()
    flo = next(s for s in guide["sources"] if s["key"] == "flo_json")
    assert "Contact us" in " ".join(flo["steps"])
    assert "undocumented" in flo["caveat"]
    assert any("never uploaded anywhere" in n for n in guide["notes"])
