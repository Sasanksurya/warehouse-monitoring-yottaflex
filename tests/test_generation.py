import csv
import os

from whmon.config import make_config
from whmon.pipeline import build_dataset
from whmon.reader import iter_csv, load


def test_starter_counts(starter):
    c = starter["manifest"]["row_counts"]
    assert c["warehouse"] == 2 and c["zone"] == 10 and c["sensor"] == 50 and c["inventory_lot"] == 400


def test_id_conventions(starter):
    import re
    z = load(starter["out"], "zone")[0]["zone_id"]
    assert re.fullmatch(r"ZONE-WH-\d{3}-\d{3}", z)
    assert re.fullmatch(r"SNS-ZONE-WH-\d{3}-\d{3}-TEMP-01", load(starter["out"], "sensor")[0]["sensor_id"])
    r = next(iter_csv(starter["out"], "sensor_reading"))
    assert r["reading_id"] == "RDG-" + r["sensor_id"] + "-" + r["measured_at"].replace("-", "").replace(":", "")
    assert load(starter["out"], "inventory_lot")[0]["lot_id"] == "LOT-2026-000001"
    assert load(starter["out"], "warehouse")[0]["warehouse_id"] == "WH-001"


def test_cold_and_hot_zones_exist(starter):
    types = {z["zone_type"] for z in load(starter["out"], "zone")}
    assert {"COLD", "FROZEN", "HOT"} <= types


def test_door_events_sensor_drift_and_gaps_present(starter):
    assert len(load(starter["out"], "door_event")) > 500
    truth = {t["issue_type"] for t in starter["world"].truth}
    assert {"SENSOR_DRIFT", "SENSOR_OUTAGE"} <= truth


def test_scale_is_parameterised():
    w = build_dataset(make_config("starter", warehouses=1, zones_per_warehouse=5, days=8, lots=60))
    assert len(w.tables["zone"]) == 5 and len(w.tables["sensor"]) == 25 and len(w.tables["inventory_lot"]) == 60
    assert len(w.readings["SNS-ZONE-WH-001-001-TEMP-01"]) == 8 * 96


def test_derived_values_come_from_source_records(starter):
    d = starter["out"]
    from whmon.reader import fast_epoch as E
    for r in load(d, "door_event"):
        assert int(r["duration_s"]) == E(r["closed_at"]) - E(r["opened_at"])
    lots = {l["lot_id"]: l["current_state"] for l in load(d, "inventory_lot")}
    last = {}
    for e in load(d, "lot_state_history"):
        last[e["lot_id"]] = e["to_state"]
    assert lots == last


def test_alarms_trace_to_lots_and_remediations(starter):
    d = starter["out"]
    impacts = {(x["alarm_id"], x["lot_id"]) for x in load(d, "alarm_lot_impact")}
    for r in load(d, "remediation"):
        if r["lot_id"]:
            assert (r["alarm_id"], r["lot_id"]) in impacts


def test_history_is_append_only_ordered(starter):
    d = starter["out"]
    prev = {}
    for e in load(d, "alarm_state_history"):
        assert e["event_ts"] >= prev.get(e["alarm_id"], "")
        prev[e["alarm_id"]] = e["event_ts"]
