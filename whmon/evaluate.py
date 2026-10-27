"""Evaluation of a dataset against its separate ground truth.

Part A  independent detectors for the four injected edge cases (they only read INPUT tables), scored vs ground truth
Part B  alarm quality: recall per injected condition, time-to-detect, explained vs unexplained alarms
Part C  workflow KPIs and reconciliation
Part D  distribution / realism summary
Ground truth is read only here, after the detectors have produced their findings."""
from __future__ import annotations

import json
import math
import os
from collections import Counter, defaultdict

from .config import INTERVAL_S, STEPS_PER_DAY, RULES
from .reader import iter_csv, load, load_truth, load_manifest, fast_epoch, date_epoch


def pct(vals, p):
    if not vals:
        return None
    v = sorted(vals)
    k = (len(v) - 1) * p
    lo, hi = math.floor(k), math.ceil(k)
    return round(v[lo] + (v[hi] - v[lo]) * (k - lo), 2)


def prf(found: set, truth: set):
    tp = len(found & truth)
    p = tp / len(found) if found else (1.0 if not truth else 0.0)
    r = tp / len(truth) if truth else 1.0
    return {"truth": len(truth), "flagged": len(found), "true_positive": tp, "false_positive": len(found - truth),
            "false_negative": len(truth - found), "precision": round(p, 4), "recall": round(r, 4)}


def zone_compatible(z, req):
    if float(z["temp_min_c"]) < float(req["temp_min_c"]) or float(z["temp_max_c"]) > float(req["temp_max_c"]):
        return False
    return req["humidity_max_pct"] == "" or float(z["humidity_max_pct"]) <= float(req["humidity_max_pct"])


def evaluate(out_dir: str) -> dict:
    E = fast_epoch
    man = load_manifest(out_dir)
    start = E(man["period_utc"][0])
    n_steps = man["scale"]["days"] * STEPS_PER_DAY
    T = {n: load(out_dir, n) for n in ("zone", "sensor", "sensor_zone_assignment", "storage_requirement", "inventory_lot",
                                         "lot_zone_assignment", "door_event", "sensor_gap", "alarm", "alarm_state_history",
                                         "inspection", "remediation", "alarm_lot_impact", "lot_state_history")}
    zones = {z["zone_id"]: z for z in T["zone"]}
    sensors = {s["sensor_id"]: s for s in T["sensor"]}
    reqs = {r["requirement_id"]: r for r in T["storage_requirement"]}
    lots = {l["lot_id"]: l for l in T["inventory_lot"]}
    alarms = T["alarm"]

    # ================= Part A: detectors (input tables only) =================
    flagged = {}
    flagged["INCOMPATIBLE_ZONE_ASSIGNMENT"] = {a["lot_id"] for a in T["lot_zone_assignment"]
                                               if not zone_compatible(zones[a["zone_id"]], reqs[lots[a["lot_id"]]["requirement_id"]])}
    per_sensor = defaultdict(list)
    for a in T["sensor_zone_assignment"]:
        per_sensor[a["sensor_id"]].append(a)
    flagged["SENSOR_MULTI_ZONE_NO_RATIONALE"] = {
        sid for sid, lst in per_sensor.items()
        if len({a["zone_id"] for a in lst if not a["effective_to"]}) > 1 and any(a["rationale"] == "" for a in lst)}

    # one pass over readings: missing intervals per sensor, and distribution statistics
    declared = {(g["sensor_id"], E(g["gap_start"]), E(g["gap_end"])) for g in T["sensor_gap"]}
    undeclared = []        # (sensor, zone, start_epoch, end_epoch)
    stats = defaultdict(lambda: [0, 0.0, 0.0, 0, 0])   # key -> n, mean, M2, out_of_band, min-max placeholder
    steps, cur, n_readings = [], None, 0
    per_type_counts = Counter()

    def close(sid):
        if sid is None:
            return
        prev = -1
        for s in steps + [n_steps]:
            if s - prev > 1:
                a, b = start + (prev + 1) * INTERVAL_S, start + s * INTERVAL_S
                if (sid, a, b) not in declared:
                    undeclared.append((sid, sensors[sid]["home_zone_id"], a, b))
            prev = s

    for r in iter_csv(out_dir, "sensor_reading"):
        sid = r["sensor_id"]
        if sid != cur:
            close(cur)
            cur, steps = sid, []
        t = E(r["measured_at"])
        steps.append((t - start) // INTERVAL_S)
        n_readings += 1
        v = float(r["value"])
        z = zones[r["zone_id"]]
        st = sensors[sid]["sensor_type"]
        key = (z["zone_type"], st)
        s = stats[key]
        s[0] += 1
        d = v - s[1]
        s[1] += d / s[0]
        s[2] += d * (v - s[1])
        if st == "TEMP" and not (float(z["temp_min_c"]) <= v <= float(z["temp_max_c"])):
            s[3] += 1
        elif st == "HUM" and v > float(z["humidity_max_pct"]):
            s[3] += 1
        elif st == "OCC" and v > int(z["max_occupancy"]):
            s[3] += 1
        per_type_counts[st] += 1
    close(cur)

    # group undeclared runs into zone-level events
    by_zone = defaultdict(list)
    for sid, zid, a, b in undeclared:
        by_zone[zid].append((a, b, sid))
    undeclared_events = []
    for zid, runs in by_zone.items():
        runs.sort()
        ev = None
        for a, b, sid in runs:
            if ev and a <= ev["end"]:
                ev["end"] = max(ev["end"], b)
                ev["sensors"].add(sid)
            else:
                if ev:
                    undeclared_events.append(ev)
                ev = {"zone": zid, "start": a, "end": b, "sensors": {sid}}
        undeclared_events.append(ev)

    # alarm -> lot link detector: overlap of breach window with stays in the alarm's zone
    stays = defaultdict(list)
    for a in T["lot_zone_assignment"]:
        stays[a["zone_id"]].append((a["lot_id"], E(a["stored_from"]), E(a["stored_to"]) if a["stored_to"] else 1 << 60))
    linked = defaultdict(set)
    for x in T["alarm_lot_impact"]:
        linked[x["alarm_id"]].add(x["lot_id"])
    elig = set(RULES["lot_link_alarm_types"])
    unlinked_alarms, partial_alarms, expected_pairs, missing_pairs = set(), set(), 0, 0
    for a in alarms:
        if a["alarm_type"] not in elig:
            continue
        b0, b1 = E(a["breach_start"]), E(a["breach_end"])
        expected = {lid for lid, f, t in stays[a["zone_id"]] if min(t, b1) - max(f, b0) >= 60}
        expected_pairs += len(expected)
        miss = expected - linked[a["alarm_id"]]
        missing_pairs += len(miss)
        if expected and not linked[a["alarm_id"]]:
            unlinked_alarms.add(a["alarm_id"])
        elif miss:
            partial_alarms.add(a["alarm_id"])
    flagged["ALARM_NOT_LINKED_TO_LOTS"] = unlinked_alarms

    # ----- truth is loaded only now
    truth = load_truth(out_dir)
    tt = defaultdict(list)
    for t in truth:
        tt[t["issue_type"]].append(t)
    edge = {}
    for itype in ("INCOMPATIBLE_ZONE_ASSIGNMENT", "SENSOR_MULTI_ZONE_NO_RATIONALE", "ALARM_NOT_LINKED_TO_LOTS"):
        edge[itype] = prf(flagged[itype], {t["entity_id"] for t in tt[itype]})
    hidden_truth = tt["GAP_TREATED_AS_NORMAL"]
    matched = set()
    for ev in undeclared_events:
        for t in hidden_truth:
            if t["zone_id"] == ev["zone"] and fast_epoch(t["window_start"]) < ev["end"] and fast_epoch(t["window_end"]) > ev["start"]:
                matched.add(t["entity_id"])
    edge["GAP_TREATED_AS_NORMAL"] = {"truth": len(hidden_truth), "flagged_zone_events": len(undeclared_events),
                                     "true_positive": len(matched), "false_positive": len(undeclared_events) - len(matched),
                                     "false_negative": len(hidden_truth) - len(matched),
                                     "recall": round(len(matched) / len(hidden_truth), 4) if hidden_truth else 1.0,
                                     "precision": round(len(matched) / len(undeclared_events), 4) if undeclared_events else 1.0,
                                     "undeclared_missing_intervals": sum((b - a) // INTERVAL_S for _s, _z, a, b in undeclared)}
    edge["ALARM_NOT_LINKED_TO_LOTS"]["partially_linked_alarms"] = len(partial_alarms)
    edge["ALARM_NOT_LINKED_TO_LOTS"]["expected_alarm_lot_pairs"] = expected_pairs
    edge["ALARM_NOT_LINKED_TO_LOTS"]["missing_pairs"] = missing_pairs

    # ================= Part B: alarm quality vs truth =================
    az = defaultdict(list)
    for a in alarms:
        az[a["zone_id"]].append({**a, "_s": E(a["breach_start"]), "_e": E(a["breach_end"]), "_o": E(a["opened_at"])})
    EVENT_TYPES = {"TEMP_HIGH_EXCURSION", "TEMP_LOW_EXCURSION", "HUMIDITY_EXCURSION", "TEMP_BOUNDARY_MIN_PERSISTENCE", "TRANSIENT_SPIKE",
                   "OCCUPANCY_EXCEEDED", "DOOR_LEFT_OPEN", "SENSOR_DRIFT", "SENSOR_OUTAGE"}
    truth_events = [t for t in truth if t["issue_type"] in EVENT_TYPES]
    explained = {}
    recall = defaultdict(lambda: {"expected": 0, "detected": 0, "ttd_min": []})
    false_alarm_on_transient = 0
    drift_attr = [0, 0]
    for t in truth_events:
        ws, we = E(t["window_start"]), E(t["window_end"])
        types = set(filter(None, t["expected_alarm_types"].split("|")))
        hits = [a for a in az[t["zone_id"]] if a["alarm_type"] in types and a["_s"] < we + 3600 and a["_e"] > ws - 1800]
        if t["issue_type"] == "SENSOR_OUTAGE":
            hits = [a for a in hits if a["sensor_id"] == t["sensor_id"]]
        if t["expected_decision"] == "NO_ALARM":
            near = [a for a in az[t["zone_id"]] if a["alarm_type"] in ("TEMP_HIGH", "TEMP_LOW") and a["_s"] < we + 1800 and a["_e"] > ws - 1800]
            false_alarm_on_transient += bool(near)
            for a in near:
                explained[a["alarm_id"]] = "false_alarm_on_transient_spike"
            continue
        if not types:
            continue
        r = recall[t["issue_type"]]
        r["expected"] += 1
        if hits:
            r["detected"] += 1
            r["ttd_min"].append((min(a["_o"] for a in hits) - ws) / 60)
            for a in hits:
                explained.setdefault(a["alarm_id"], "matched_injected_condition")
            if t["issue_type"] == "SENSOR_DRIFT":
                drift_attr[1] += 1
                drift_attr[0] += any(a["sensor_id"] == t["sensor_id"] for a in hits)
    drift_windows = {t["sensor_id"]: (E(t["window_start"]), E(t["window_end"])) for t in tt["SENSOR_DRIFT"]}
    door_left = defaultdict(list)
    for t in tt["DOOR_LEFT_OPEN"]:
        door_left[t["zone_id"]].append((E(t["window_start"]), E(t["window_end"])))
    natural_door = {(d["zone_id"], E(d["opened_at"])) for d in T["door_event"] if d["exceeded_limit"] == "true"}
    cats = Counter()
    unexplained_samples = []
    for a in alarms:
        cat = explained.get(a["alarm_id"])
        if not cat:
            s, e = E(a["breach_start"]), E(a["breach_end"])
            if a["alarm_type"] in ("TEMP_HIGH", "TEMP_LOW", "HUMIDITY_HIGH") and any(s < b + 4 * 3600 and e > o - 1800 for o, b in door_left[a["zone_id"]]):
                cat = "secondary_to_door_left_open"
            elif a["alarm_type"] in ("TEMP_HIGH", "TEMP_LOW") and a["sensor_id"] in drift_windows and s < drift_windows[a["sensor_id"]][1] + 3600 and e > drift_windows[a["sensor_id"]][0]:
                cat = "drift_induced_false_alarm"
            elif a["alarm_type"] == "DOOR_OPEN_TOO_LONG" and (a["zone_id"], s) in natural_door:
                cat = "natural_door_overrun_by_rule"
            else:
                cat = "unexplained"
                if len(unexplained_samples) < 5:
                    unexplained_samples.append(a["alarm_id"])
        cats[cat] += 1
    n_alarm = len(alarms)
    bad = cats["unexplained"] + cats["drift_induced_false_alarm"] + cats["false_alarm_on_transient_spike"]
    alarm_quality = {
        "alarms_total": n_alarm, "alarm_categories": dict(sorted(cats.items())),
        "false_alarm_rate": round(bad / n_alarm, 4) if n_alarm else 0.0,
        "transient_spikes_that_alarmed": false_alarm_on_transient, "unexplained_samples": unexplained_samples,
        "recall_by_injected_condition": {k: {"expected": v["expected"], "detected": v["detected"],
                                             "recall": round(v["detected"] / v["expected"], 4) if v["expected"] else None,
                                             "time_to_detect_min_median": pct(v["ttd_min"], 0.5), "time_to_detect_min_p90": pct(v["ttd_min"], 0.9)}
                                         for k, v in sorted(recall.items())},
        "drift_sensor_attribution_accuracy": round(drift_attr[0] / drift_attr[1], 4) if drift_attr[1] else None,
        "alarms_by_type_severity": {f"{k[0]}/{k[1]}": v for k, v in sorted(Counter((a["alarm_type"], a["severity"]) for a in alarms).items())},
    }

    # ================= Part C: workflow KPIs =================
    ack, closed_after, status = [], [], Counter(a["status"] for a in alarms)
    first_ack = {}
    for e in T["alarm_state_history"]:
        if e["event_type"] == "ACKNOWLEDGED":
            first_ack[e["alarm_id"]] = E(e["event_ts"])
    for a in alarms:
        if a["alarm_id"] in first_ack:
            ack.append((first_ack[a["alarm_id"]] - E(a["opened_at"])) / 60)
        if a["closed_at"]:
            closed_after.append((E(a["closed_at"]) - E(a["opened_at"])) / 3600)
    crit = [a for a in alarms if a["severity"] == "CRITICAL"]
    insp_alarms = {i["alarm_id"] for i in T["inspection"]}
    lot_actions = [r for r in T["remediation"] if r["lot_id"]]
    workflow = {
        "alarm_status_counts": dict(status),
        "time_to_acknowledge_min": {"median": pct(ack, 0.5), "p90": pct(ack, 0.9)},
        "time_to_close_h": {"median": pct(closed_after, 0.5), "p90": pct(closed_after, 0.9)},
        "critical_alarms_inspected_share": round(sum(a["alarm_id"] in insp_alarms for a in crit) / len(crit), 4) if crit else None,
        "inspections": len(T["inspection"]), "inspection_outcomes": dict(Counter(i["outcome"] or "PENDING" for i in T["inspection"])),
        "remediation_actions": dict(Counter(r["action_type"] for r in T["remediation"])),
        "lots_with_alarm_impact": len({x["lot_id"] for x in T["alarm_lot_impact"]}),
        "impact_levels": dict(Counter(x["impact_level"] for x in T["alarm_lot_impact"])),
        "impact_dispositions": dict(Counter(x["disposition"] for x in T["alarm_lot_impact"])),
        "units_quarantined": sum(int(r["units_affected"]) for r in T["remediation"] if r["action_type"] == "QUARANTINE_LOT"),
        "units_disposed": sum(int(r["units_affected"]) for r in T["remediation"] if r["action_type"] == "DISPOSE_LOT"),
        "lot_final_states": dict(Counter(l["current_state"] for l in T["inventory_lot"])),
        "lot_actions_linked_to_impact_share": 1.0 if not lot_actions else round(
            sum((r["alarm_id"], r["lot_id"]) in {(x["alarm_id"], x["lot_id"]) for x in T["alarm_lot_impact"]} for r in lot_actions) / len(lot_actions), 4),
    }

    # ================= Part D: distributions =================
    dist = {"readings_total": n_readings, "readings_by_sensor_type": dict(per_type_counts),
            "reading_completeness": round(n_readings / (sum(1 for s in sensors.values() if s["sensor_type"] != "DOOR") * n_steps), 4),
            "per_zone_type_stats": {f"{k[0]}/{k[1]}": {"n": v[0], "mean": round(v[1], 2), "std": round(math.sqrt(v[2] / v[0]), 2) if v[0] else 0,
                                                       "share_outside_threshold": round(v[3] / v[0], 5)} for k, v in sorted(stats.items())}}
    per_zone_day = Counter(d["zone_id"] for d in T["door_event"])
    days = man["scale"]["days"]
    dist["door_events"] = {"total": len(T["door_event"]), "per_zone_per_day_mean": round(len(T["door_event"]) / len(zones) / days, 2),
                           "duration_s_p50": pct([int(d["duration_s"]) for d in T["door_event"]], 0.5),
                           "duration_s_p95": pct([int(d["duration_s"]) for d in T["door_event"]], 0.95),
                           "share_over_limit": round(sum(d["exceeded_limit"] == "true" for d in T["door_event"]) / len(T["door_event"]), 4)}
    dwell = [int(a["dwell_minutes"]) / 1440 for a in T["lot_zone_assignment"] if a["dwell_minutes"]]
    dist["lots"] = {"total": len(lots), "by_category": dict(Counter(l["product_category"] for l in T["inventory_lot"])),
                    "dwell_days_p50": pct(dwell, 0.5), "dwell_days_p90": pct(dwell, 0.9),
                    "zone_types_used": dict(Counter(zones[a["zone_id"]]["zone_type"] for a in T["lot_zone_assignment"]))}
    dist["sensor_gaps"] = {"declared": len(T["sensor_gap"]), "missed_readings_p50": pct([int(g["missed_readings"]) for g in T["sensor_gap"]], 0.5),
                           "missed_readings_p90": pct([int(g["missed_readings"]) for g in T["sensor_gap"]], 0.9)}
    dist["ground_truth_issue_counts"] = dict(sorted(Counter(t["issue_type"] for t in truth).items()))

    return {"edge_case_detection": edge, "alarm_quality": alarm_quality, "workflow": workflow, "distributions": dist}


def markdown(res: dict) -> str:
    L = ["# Evaluation report", "", "Detectors in part A read only the input tables; `ground_truth/` is used only to score them.", "",
         "## A. Injected edge cases: detector vs ground truth", "",
         "| Edge case | Truth | Flagged | TP | FP | FN | Precision | Recall |", "|---|---:|---:|---:|---:|---:|---:|---:|"]
    for k, v in res["edge_case_detection"].items():
        L.append(f"| {k} | {v['truth']} | {v.get('flagged', v.get('flagged_zone_events'))} | {v['true_positive']} | {v['false_positive']} | {v['false_negative']} | {v['precision']} | {v['recall']} |")
    e = res["edge_case_detection"]
    L += ["", f"Undeclared missing reading intervals: {e['GAP_TREATED_AS_NORMAL']['undeclared_missing_intervals']}. "
          f"Alarms with partially missing lot links: {e['ALARM_NOT_LINKED_TO_LOTS']['partially_linked_alarms']} "
          f"({e['ALARM_NOT_LINKED_TO_LOTS']['missing_pairs']} of {e['ALARM_NOT_LINKED_TO_LOTS']['expected_alarm_lot_pairs']} expected alarm-lot pairs absent).", ""]
    a = res["alarm_quality"]
    L += ["## B. Alarm quality", "", f"Alarms: {a['alarms_total']}; false-alarm rate (unexplained + drift-induced + spike-induced): {a['false_alarm_rate']}", "",
          "| Alarm category | Count |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in a["alarm_categories"].items()]
    L += ["", "| Injected condition | Expected | Detected | Recall | TTD median (min) | TTD p90 (min) |", "|---|---:|---:|---:|---:|---:|"]
    for k, v in a["recall_by_injected_condition"].items():
        L.append(f"| {k} | {v['expected']} | {v['detected']} | {v['recall']} | {v['time_to_detect_min_median']} | {v['time_to_detect_min_p90']} |")
    L += ["", f"Transient single-reading spikes that wrongly alarmed: {a['transient_spikes_that_alarmed']}. "
          f"Drift culprit-sensor attribution accuracy: {a['drift_sensor_attribution_accuracy']}.", ""]
    w = res["workflow"]
    L += ["## C. Workflow KPIs", "", "```json", json.dumps(w, indent=1), "```", ""]
    L += ["## D. Distributions", "", "```json", json.dumps(res["distributions"], indent=1), "```", ""]
    return "\n".join(L)


def write_reports(res: dict, out_dir: str):
    os.makedirs(os.path.join(out_dir, "reports"), exist_ok=True)
    with open(os.path.join(out_dir, "reports", "evaluation_report.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(res, f, indent=1)
    with open(os.path.join(out_dir, "reports", "evaluation_report.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(markdown(res))
