import json
import os

from whmon.evaluate import evaluate, prf
from whmon.reader import load, load_truth, iter_csv
from whmon.schema import TABLES


def test_prf_helper():
    r = prf({"a", "b", "x"}, {"a", "b", "c"})
    assert r["true_positive"] == 2 and r["false_positive"] == 1 and r["false_negative"] == 1
    assert round(r["precision"], 3) == 0.667 and round(r["recall"], 3) == 0.667


def test_edge_case_detectors_find_all_injected_defects(starter):
    res = evaluate(starter["out"])
    for name, m in res["edge_case_detection"].items():
        assert m["recall"] == 1.0 and m["precision"] == 1.0, name
        assert m["truth"] >= 1, f"starter dataset must contain the {name} edge case"


def test_alarm_recall_and_transient_spikes(starter):
    res = evaluate(starter["out"])["alarm_quality"]
    for k, v in res["recall_by_injected_condition"].items():
        assert v["recall"] >= 0.9, k
    assert res["transient_spikes_that_alarmed"] == 0
    assert res["false_alarm_rate"] < 0.15


def test_ground_truth_is_separate_and_not_leaked(starter):
    out = starter["out"]
    truth_ids = {t["truth_id"] for t in load_truth(out)}
    assert truth_ids and os.path.exists(os.path.join(out, "ground_truth", "ground_truth.csv"))
    labels = {"issue_type", "ground_truth", "expected_decision", "truth_id", "expected_alarm_types"}
    for t in TABLES:
        assert not labels & set(t.names), t.name
    for t in TABLES:
        if t.name == "sensor_reading":
            continue
        text = open(os.path.join(out, "csv", f"{t.name}.csv"), encoding="utf-8").read()
        assert "GT-0" not in text and "HGAP-" not in text, t.name


def test_ground_truth_labels_follow_documented_rules(starter):
    out = starter["out"]
    zones = {z["zone_id"]: z for z in load(out, "zone")}
    lots = {l["lot_id"]: l for l in load(out, "inventory_lot")}
    reqs = {r["requirement_id"]: r for r in load(out, "storage_requirement")}
    impacts = {}
    for x in load(out, "alarm_lot_impact"):
        impacts.setdefault(x["alarm_id"], []).append(x)
    for t in load_truth(out):
        d = t["details"]
        if t["issue_type"] == "DOOR_LEFT_OPEN":
            assert d["duration_s"] > d["limit_s"]
        if t["issue_type"] == "ALARM_NOT_LINKED_TO_LOTS":
            assert t["entity_id"] not in impacts and d["expected_lot_count"] >= 1
        if t["issue_type"] == "INCOMPATIBLE_ZONE_ASSIGNMENT":
            z = zones[t["zone_id"]]
            req = reqs[lots[t["entity_id"]]["requirement_id"]]
            assert float(z["temp_min_c"]) < float(req["temp_min_c"]) or float(z["temp_max_c"]) > float(req["temp_max_c"]) \
                or (req["humidity_max_pct"] and float(z["humidity_max_pct"]) > float(req["humidity_max_pct"]))
        if t["issue_type"] == "SENSOR_MULTI_ZONE_NO_RATIONALE":
            assert d["home_zone"] != d["second_zone"]


def test_hidden_gap_has_no_gap_record_and_no_alarm(starter):
    out = starter["out"]
    gaps = load(out, "sensor_gap")
    alarms = load(out, "alarm")
    for t in load_truth(out):
        if t["issue_type"] != "GAP_TREATED_AS_NORMAL":
            continue
        z = t["zone_id"]
        assert not [g for g in gaps if g["zone_id"] == z and g["gap_start"] < t["window_end"] and g["gap_end"] > t["window_start"]]
        assert not [a for a in alarms if a["zone_id"] == z and a["alarm_type"] == "SENSOR_GAP"
                    and a["breach_start"] < t["window_end"] and a["breach_end"] > t["window_start"]]


def test_affected_lots_are_identified_from_time_and_zone_overlap(starter):
    out = starter["out"]
    res = evaluate(out)["edge_case_detection"]["ALARM_NOT_LINKED_TO_LOTS"]
    assert res["partially_linked_alarms"] == 0     # every link-eligible alarm is either fully linked or a labelled defect
    stays = {}
    for a in load(out, "lot_zone_assignment"):
        stays.setdefault(a["zone_id"], []).append(a)
    from whmon.reader import fast_epoch as E
    unlinked = {t["entity_id"] for t in load_truth(out) if t["issue_type"] == "ALARM_NOT_LINKED_TO_LOTS"}
    linked = {}
    for x in load(out, "alarm_lot_impact"):
        linked.setdefault(x["alarm_id"], set()).add(x["lot_id"])
    for al in load(out, "alarm"):
        if al["alarm_type"] not in ("TEMP_HIGH", "TEMP_LOW", "HUMIDITY_HIGH", "SENSOR_GAP", "SENSOR_DRIFT") or al["alarm_id"] in unlinked:
            continue
        b0, b1 = E(al["breach_start"]), E(al["breach_end"])
        exp = {a["lot_id"] for a in stays.get(al["zone_id"], [])
               if min(E(a["stored_to"]) if a["stored_to"] else 1 << 60, b1) - max(E(a["stored_from"]), b0) >= 60}
        assert exp == linked.get(al["alarm_id"], set()), al["alarm_id"]
