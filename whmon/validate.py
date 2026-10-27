"""Integrity validation of an exported dataset (reads the CSV files from disk).

Covers: schema/header, required fields, types, enums, ID patterns, PK + natural-key uniqueness, FK integrity,
date ordering, arithmetic reconciliation of derived fields, lifecycle transitions, threshold consistency, duplicates.

Deliberately NOT errors here: the injected semantic defects (incompatible lot zone, sensor mapped to several zones
without rationale, undeclared gaps, alarms not linked to lots). They are structurally valid rows; the evaluator finds them."""
from __future__ import annotations

import json
import os
import re
from collections import defaultdict

from .config import RULES, INTERVAL_S, STEPS_PER_DAY
from .reader import iter_csv, load, fast_epoch, date_epoch, load_manifest
from .schema import (TABLES, TABLE_BY_NAME, ALARM_TRANSITIONS, LOT_TRANSITIONS, INTEGER, FLOAT, TIMESTAMP, DATE, BOOLEAN)

TS_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SENSOR_UNIT = {"TEMP": "C", "HUM": "PCT_RH", "OCC": "PERSONS", "DOOR": "EVENT"}


class Report:
    def __init__(self):
        self.c = {}

    def rec(self, category, name, ok, sample=None, severity="ERROR"):
        e = self.c.setdefault(name, {"category": category, "checked": 0, "failed": 0, "samples": [], "severity": severity})
        e["checked"] += 1
        if not ok:
            e["failed"] += 1
            if len(e["samples"]) < 3 and sample is not None:
                e["samples"].append(sample)

    def info(self, category, name, value):
        self.c[name] = {"category": category, "checked": 0, "failed": 0, "samples": [], "severity": "INFO", "value": value}

    @property
    def errors(self):
        return sum(1 for v in self.c.values() if v["severity"] == "ERROR" and v["failed"])

    def to_dict(self):
        checks = [{"name": k, **v, "status": ("INFO" if v["severity"] == "INFO" else ("FAIL" if v["failed"] else "PASS"))}
                  for k, v in sorted(self.c.items(), key=lambda kv: (kv[1]["category"], kv[0]))]
        return {"summary": {"checks": len(checks), "passed": sum(1 for c in checks if c["status"] == "PASS"),
                            "failed": sum(1 for c in checks if c["status"] == "FAIL"),
                            "rows_checked": sum(c["checked"] for c in checks)}, "checks": checks}

    def markdown(self):
        d = self.to_dict()
        s = d["summary"]
        out = [f"# Validation summary", "", f"**{s['passed']} passed, {s['failed']} failed** of {s['checks']} checks "
               f"({s['rows_checked']:,} individual assertions).", "", "| Category | Check | Status | Checked | Failed |", "|---|---|---|---:|---:|"]
        for c in d["checks"]:
            out.append(f"| {c['category']} | {c['name']} | {c['status']} | {c['checked']:,} | {c['failed']:,} |"
                       if c["status"] != "INFO" else f"| {c['category']} | {c['name']} | INFO | - | {c['value']} |")
        bad = [c for c in d["checks"] if c["status"] == "FAIL"]
        if bad:
            out += ["", "## Failures (samples)"] + [f"- **{c['name']}**: {c['samples']}" for c in bad]
        return "\n".join(out) + "\n"


def _typed(rep, t, f, v):
    if f.type == INTEGER:
        return re.fullmatch(r"-?\d+", v) is not None
    if f.type == FLOAT:
        try:
            float(v)
            return True
        except ValueError:
            return False
    if f.type == TIMESTAMP:
        return TS_RE.match(v) is not None
    if f.type == DATE:
        return DATE_RE.match(v) is not None
    if f.type == BOOLEAN:
        return v in ("true", "false")
    return True


def scan(rep, t, rows, pks, fkvals, extra=None):
    patterns = {f.name: re.compile(f.pattern) for f in t.fields if f.pattern}
    n_header_ok = True
    for row in rows:
        for f in t.fields:
            v = row.get(f.name, "")
            if v == "":
                rep.rec("required", f"{t.name}: required fields present", not f.required, f"{f.name} in {row.get(t.pk)}")
                continue
            rep.rec("types", f"{t.name}: field types parse", _typed(rep, t, f, v), f"{f.name}={v}")
            if f.enum:
                rep.rec("enums", f"{t.name}: enum values allowed", v in f.enum, f"{f.name}={v}")
            if f.name in patterns:
                rep.rec("ids", f"{t.name}: ID/pattern format", patterns[f.name].match(v) is not None, f"{f.name}={v}")
            if f.fk:
                fkvals[(t.name, f.name)].add(v)
        pk = row[t.pk]
        rep.rec("keys", f"{t.name}: primary key unique", pk not in pks, pk)
        pks.add(pk)
        if extra:
            extra(row)


def validate(out_dir: str) -> Report:
    rep = Report()
    manifest = load_manifest(out_dir)
    n_steps = manifest["scale"]["days"] * STEPS_PER_DAY
    period_start = fast_epoch(manifest["period_utc"][0])
    period_end = fast_epoch(manifest["period_utc"][1])

    # ---- headers
    for t in TABLES:
        with open(os.path.join(out_dir, "csv", f"{t.name}.csv"), encoding="utf-8") as f:
            rep.rec("schema", "CSV header equals schema field order", f.readline().rstrip("\n").split(",") == t.names, t.name)

    data = {t.name: load(out_dir, t.name) for t in TABLES if t.name != "sensor_reading"}
    pks = {t.name: set() for t in TABLES}
    fkvals = defaultdict(set)

    # ---- sensor readings (streamed): generic + semantic checks in one pass
    sensors = {r["sensor_id"]: r for r in data["sensor"]}
    assign = defaultdict(list)
    for a in data["sensor_zone_assignment"]:
        assign[a["sensor_id"]].append((a["zone_id"], date_epoch(a["effective_from"]),
                                       date_epoch(a["effective_to"]) if a["effective_to"] else None))
    install = {sid: date_epoch(s["install_date"]) for sid, s in sensors.items()}
    last_t, per_sensor = {}, defaultdict(int)
    seen_ts = defaultdict(set) if False else None
    RANGE = {"C": (-60.0, 80.0), "PCT_RH": (0.0, 100.0), "PERSONS": (0.0, 1000.0)}

    def reading_checks(r):
        sid, t = r["sensor_id"], fast_epoch(r["measured_at"])
        rep.rec("joins", "sensor_reading: reading_id == RDG-<sensor_id>-<timestamp>",
                r["reading_id"] == "RDG-" + sid + "-" + r["measured_at"].replace("-", "").replace(":", ""), r["reading_id"])
        s = sensors.get(sid)
        if s is None:
            return
        rep.rec("joins", "sensor_reading: zone has an active sensor assignment at measured_at",
                any(z == r["zone_id"] and fr <= t and (to is None or t < to) for z, fr, to in assign[sid]), r["reading_id"])
        rep.rec("dates", "sensor_reading: timestamp on the 15-minute grid, inside the period",
                (t - period_start) % INTERVAL_S == 0 and period_start <= t < period_end, r["measured_at"])
        rep.rec("dates", "sensor_reading: strictly increasing per sensor (no duplicate timestamps)",
                t > last_t.get(sid, -1), r["reading_id"])
        last_t[sid] = t
        rep.rec("dates", "sensor_reading: not before sensor install date", t >= install[sid], r["reading_id"])
        rep.rec("joins", "sensor_reading: unit equals sensor unit", r["unit"] == s["unit"], r["reading_id"])
        v = float(r["value"])
        lo, hi = RANGE.get(r["unit"], (-1e9, 1e9))
        rep.rec("ranges", "sensor_reading: value in physical range", lo <= v <= hi, r["reading_id"])
        if r["unit"] == "PERSONS":
            rep.rec("ranges", "sensor_reading: occupancy is a whole number", v == int(v), r["reading_id"])
        per_sensor[sid] += 1

    scan(rep, TABLE_BY_NAME["sensor_reading"], iter_csv(out_dir, "sensor_reading"), pks["sensor_reading"],
         fkvals, reading_checks)

    for t in TABLES:
        if t.name != "sensor_reading":
            scan(rep, t, data[t.name], pks[t.name], fkvals)

    # ---- foreign keys
    for (tname, fname), vals in sorted(fkvals.items()):
        parent, pcol = TABLE_BY_NAME[tname].field(fname).fk.split(".")
        missing = vals - pks[parent]
        rep.rec("joins", f"FK {tname}.{fname} -> {parent}.{pcol}", not missing, sorted(missing)[:3])
        # one assertion per distinct value so the checked count reflects the join volume
        rep.c[f"FK {tname}.{fname} -> {parent}.{pcol}"]["checked"] = len(vals)
        rep.c[f"FK {tname}.{fname} -> {parent}.{pcol}"]["failed"] = len(missing)

    # ---- natural keys
    seen = set()
    for r in data["alarm_lot_impact"]:
        k = (r["alarm_id"], r["lot_id"])
        rep.rec("keys", "alarm_lot_impact: (alarm_id, lot_id) unique", k not in seen, k)
        seen.add(k)
    seen = set()
    for r in data["door_event"]:
        k = (r["zone_id"], r["opened_at"])
        rep.rec("keys", "door_event: (zone_id, opened_at) unique", k not in seen, k)
        seen.add(k)
    seen = set()
    for r in data["alarm"]:
        k = (r["alarm_type"], r["sensor_id"], r["breach_start"])
        rep.rec("keys", "alarm: no duplicate (type, sensor, breach_start)", k not in seen, k)
        seen.add(k)

    joins_ok = all(v["failed"] == 0 for k, v in rep.c.items() if k.startswith("FK "))
    rep.rec("joins", "semantic checks ran (they need intact foreign keys)", joins_ok, "skipped: broken foreign keys")
    if joins_ok:
        _semantic(rep, data, per_sensor, n_steps, period_end)
    return rep


def _semantic(rep, d, per_sensor, n_steps, period_end):
    zones = {z["zone_id"]: z for z in d["zone"]}
    sensors = {s["sensor_id"]: s for s in d["sensor"]}
    lots = {l["lot_id"]: l for l in d["inventory_lot"]}
    reqs = {r["requirement_id"]: r for r in d["storage_requirement"]}
    alarms = {a["alarm_id"]: a for a in d["alarm"]}
    asg = {a["assignment_id"]: a for a in d["lot_zone_assignment"]}
    insp = {i["inspection_id"]: i for i in d["inspection"]}
    rems = {r["remediation_id"]: r for r in d["remediation"]}
    E = fast_epoch
    drift_windows = defaultdict(list)
    for x in d["alarm"]:
        if x["alarm_type"] == "SENSOR_DRIFT":
            drift_windows[x["sensor_id"]].append((E(x["breach_start"]), E(x["breach_end"])))

    for z in d["zone"]:
        rep.rec("joins", "zone: zone_id embeds its warehouse_id", z["zone_id"].startswith(f"ZONE-{z['warehouse_id']}-"), z["zone_id"])
        rep.rec("ranges", "zone: temp_min < setpoint < temp_max", float(z["temp_min_c"]) < float(z["setpoint_c"]) < float(z["temp_max_c"]), z["zone_id"])
    for s in d["sensor"]:
        rep.rec("joins", "sensor: sensor_id embeds home zone and type",
                s["sensor_id"].startswith(f"SNS-{s['home_zone_id']}-{s['sensor_type']}-"), s["sensor_id"])
        rep.rec("joins", "sensor: unit matches type", s["unit"] == SENSOR_UNIT[s["sensor_type"]], s["sensor_id"])
        rep.rec("required", "sensor: reading_interval_s only for non-DOOR", (s["reading_interval_s"] == "") == (s["sensor_type"] == "DOOR"), s["sensor_id"])
    for a in d["sensor_zone_assignment"]:
        rep.rec("dates", "sensor_zone_assignment: effective_to >= effective_from", not a["effective_to"] or a["effective_to"] >= a["effective_from"], a["assignment_id"])
    for l in d["inventory_lot"]:
        rep.rec("joins", "inventory_lot: requirement category equals lot category",
                reqs[l["requirement_id"]]["product_category"] == l["product_category"], l["lot_id"])
        rep.rec("ranges", "inventory_lot: quantity_units > 0", int(l["quantity_units"]) > 0, l["lot_id"])

    # ---- lot stays
    by_lot = defaultdict(list)
    for a in d["lot_zone_assignment"]:
        by_lot[a["lot_id"]].append(a)
        f, t = E(a["stored_from"]), (E(a["stored_to"]) if a["stored_to"] else None)
        rep.rec("dates", "lot_zone_assignment: stored_to > stored_from", t is None or t > f, a["assignment_id"])
        rep.rec("dates", "lot_zone_assignment: stored_from >= lot.received_at", f >= E(lots[a["lot_id"]]["received_at"]), a["assignment_id"])
        rep.rec("arithmetic", "lot_zone_assignment: dwell_minutes == (stored_to - stored_from)/60",
                (a["dwell_minutes"] == "") if t is None else int(a["dwell_minutes"]) == (t - f) // 60, a["assignment_id"])
    for lid, lst in by_lot.items():
        lst.sort(key=lambda a: E(a["stored_from"]))
        rep.rec("lifecycle", "lot_zone_assignment: first stay is PUTAWAY, later stays TRANSFER",
                lst[0]["assignment_reason"] == "PUTAWAY" and all(x["assignment_reason"] == "TRANSFER" for x in lst[1:]), lid)
        for p, n in zip(lst, lst[1:]):
            rep.rec("dates", "lot_zone_assignment: stays of one lot do not overlap", p["stored_to"] != "" and E(p["stored_to"]) <= E(n["stored_from"]), lid)

    # ---- doors
    last_close = {}
    for r in sorted(d["door_event"], key=lambda r: (r["zone_id"], r["opened_at"])):
        o, c = E(r["opened_at"]), E(r["closed_at"])
        rep.rec("dates", "door_event: closed_at > opened_at", c > o, r["door_event_id"])
        rep.rec("arithmetic", "door_event: duration_s == closed_at - opened_at", int(r["duration_s"]) == c - o, r["door_event_id"])
        rep.rec("arithmetic", "door_event: exceeded_limit == duration_s > zone limit",
                (r["exceeded_limit"] == "true") == (int(r["duration_s"]) > int(zones[r["zone_id"]]["door_open_limit_s"])), r["door_event_id"])
        s = sensors[r["sensor_id"]]
        rep.rec("joins", "door_event: sensor is a DOOR sensor homed in the zone", s["sensor_type"] == "DOOR" and s["home_zone_id"] == r["zone_id"], r["door_event_id"])
        rep.rec("ids", "door_event: id embeds zone and opened timestamp",
                r["door_event_id"] == f"DOOR-{r['zone_id']}-" + r["opened_at"].replace("-", "").replace(":", ""), r["door_event_id"])
        rep.rec("dates", "door_event: events of a zone do not overlap", o >= last_close.get(r["zone_id"], 0), r["door_event_id"])
        last_close[r["zone_id"]] = c

    # ---- gaps
    for g in d["sensor_gap"]:
        a, b = E(g["gap_start"]), E(g["gap_end"])
        rep.rec("arithmetic", "sensor_gap: missed_readings == (gap_end - gap_start)/interval", int(g["missed_readings"]) == (b - a) // INTERVAL_S and (b - a) % INTERVAL_S == 0, g["gap_id"])
        rep.rec("arithmetic", "sensor_gap: alarm_raised == missed >= min_gap_readings", (g["alarm_raised"] == "true") == (int(g["missed_readings"]) >= RULES["min_gap_readings"]), g["gap_id"])
        rep.rec("joins", "sensor_gap: sensor homed in gap zone and not a DOOR sensor", sensors[g["sensor_id"]]["home_zone_id"] == g["zone_id"] and sensors[g["sensor_id"]]["sensor_type"] != "DOOR", g["gap_id"])
    declared = defaultdict(int)
    for g in d["sensor_gap"]:
        declared[g["sensor_id"]] += int(g["missed_readings"])
    undeclared = 0
    for sid, s in sensors.items():
        if s["sensor_type"] != "DOOR":
            missing = n_steps - per_sensor.get(sid, 0)
            rep.rec("arithmetic", "sensor_reading: declared gap intervals never exceed missing intervals", declared[sid] <= missing, sid)
            undeclared += max(0, missing - declared[sid])
    rep.info("info", "missing reading intervals not covered by a sensor_gap row (see evaluation: GAP_TREATED_AS_NORMAL)", undeclared)

    # ---- alarms and histories
    thr = {"TEMP_HIGH": "temp_max_c", "TEMP_LOW": "temp_min_c", "HUMIDITY_HIGH": "humidity_max_pct",
           "DOOR_OPEN_TOO_LONG": "door_open_limit_s", "OCCUPANCY_LIMIT": "max_occupancy"}
    hist = defaultdict(list)
    for e in d["alarm_state_history"]:
        hist[e["alarm_id"]].append(e)
    prev_open = ""
    for aid in sorted(alarms):
        a = alarms[aid]
        z = zones[a["zone_id"]]
        b0, b1, o = E(a["breach_start"]), E(a["breach_end"]), E(a["opened_at"])
        rep.rec("dates", "alarm: breach_end > breach_start and opened_at >= breach_start", b1 > b0 and o >= b0, aid)
        rep.rec("arithmetic", "alarm: duration_minutes == (breach_end - breach_start)/60", int(a["duration_minutes"]) == (b1 - b0) // 60, aid)
        rep.rec("joins", "alarm: triggering sensor homed in alarm zone", sensors[a["sensor_id"]]["home_zone_id"] == a["zone_id"], aid)
        rep.rec("ordering", "alarm: ids follow opened_at order", a["opened_at"] >= prev_open, aid)
        prev_open = a["opened_at"]
        if a["alarm_type"] in thr:
            rep.rec("thresholds", "alarm: threshold_value equals the zone limit for its type", float(a["threshold_value"]) == float(z[thr[a["alarm_type"]]]), aid)
        elif a["alarm_type"] == "SENSOR_GAP":
            rep.rec("thresholds", "alarm: threshold_value equals the zone limit for its type", float(a["threshold_value"]) == RULES["min_gap_readings"], aid)
        else:
            rep.rec("thresholds", "alarm: threshold_value equals the zone limit for its type", float(a["threshold_value"]) == RULES["drift_threshold_c"], aid)
        rep.rec("thresholds", "alarm: peak is beyond the threshold (TEMP_HIGH/HUMIDITY/DOOR/OCC above, TEMP_LOW below)",
                (float(a["peak_value"]) < float(a["threshold_value"])) if a["alarm_type"] == "TEMP_LOW" else
                (float(a["peak_value"]) > float(a["threshold_value"])) if a["alarm_type"] in thr else True, aid)
        evs = hist[aid]
        evs.sort(key=lambda e: e["event_id"])
        rep.rec("lifecycle", "alarm_state_history: every alarm has a history", bool(evs), aid)
        if not evs:
            continue
        rep.rec("lifecycle", "alarm_state_history: first event OPENED at opened_at", evs[0]["event_type"] == "OPENED" and evs[0]["event_ts"] == a["opened_at"], aid)
        prev_status, prev_ts = None, 0
        for e in evs:
            ok = (e["from_status"] or None) == prev_status and e["to_status"] in ALARM_TRANSITIONS.get(prev_status, set())
            rep.rec("lifecycle", "alarm_state_history: transitions follow the allowed lifecycle", ok, (aid, e["from_status"], e["to_status"]))
            rep.rec("dates", "alarm_state_history: timestamps non-decreasing", E(e["event_ts"]) >= prev_ts, aid)
            prev_status, prev_ts = e["to_status"], E(e["event_ts"])
        rep.rec("arithmetic", "alarm: status equals the latest history status", a["status"] == prev_status, aid)
        rep.rec("arithmetic", "alarm: closed_at set exactly when CLOSED (and equals the CLOSED event)",
                (a["closed_at"] == next((e["event_ts"] for e in evs if e["to_status"] == "CLOSED"), "")), aid)
        if a["closed_at"]:
            rep.rec("dates", "alarm: closed_at >= opened_at", E(a["closed_at"]) >= o, aid)

    # ---- inspections / remediations
    for i in d["inspection"]:
        a = alarms[i["alarm_id"]]
        rep.rec("joins", "inspection: zone equals alarm zone", i["zone_id"] == a["zone_id"], i["inspection_id"])
        rep.rec("dates", "inspection: scheduled_at >= alarm.opened_at", E(i["scheduled_at"]) >= E(a["opened_at"]), i["inspection_id"])
        s, c = i["started_at"], i["completed_at"]
        rep.rec("dates", "inspection: scheduled <= started <= completed", (not s or E(s) >= E(i["scheduled_at"])) and (not c or (s and E(c) >= E(s))), i["inspection_id"])
        rep.rec("lifecycle", "inspection: status consistent with timestamps and outcome",
                (i["status"] == "COMPLETED") == bool(c and i["outcome"]) and (i["status"] != "SCHEDULED" or not s), i["inspection_id"])
    impact_keys = {(x["alarm_id"], x["lot_id"]): x for x in d["alarm_lot_impact"]}
    LOT_ACTIONS = {"QUARANTINE_LOT", "DISPOSE_LOT", "RELEASE_LOT", "NOTIFY_CUSTOMER"}
    for r in d["remediation"]:
        a = alarms[r["alarm_id"]]
        rid = r["remediation_id"]
        rep.rec("joins", "remediation: zone equals alarm zone", r["zone_id"] == a["zone_id"], rid)
        rep.rec("joins", "remediation: inspection belongs to the same alarm", bool(r["inspection_id"]) and insp[r["inspection_id"]]["alarm_id"] == r["alarm_id"], rid)
        rep.rec("dates", "remediation: performed_at >= inspection.completed_at", r["inspection_id"] != "" and insp[r["inspection_id"]]["completed_at"] != "" and E(r["performed_at"]) >= E(insp[r["inspection_id"]]["completed_at"]), rid)
        if r["action_type"] in LOT_ACTIONS:
            rep.rec("joins", "remediation: lot action has a lot and links to inventory impact (alarm_lot_impact)", bool(r["lot_id"]) and (r["alarm_id"], r["lot_id"]) in impact_keys, rid)
            rep.rec("arithmetic", "remediation: units_affected == lot.quantity_units", bool(r["lot_id"]) and r["units_affected"] == lots[r["lot_id"]]["quantity_units"], rid)
        else:
            rep.rec("joins", "remediation: non-lot action has no lot; sensor action has a sensor",
                    r["lot_id"] == "" and (r["action_type"] in ("REPAIR_EQUIPMENT", "DOOR_SEAL_REPAIR") or r["sensor_id"] != ""), rid)

    # ---- impacts
    for x in d["alarm_lot_impact"]:
        a, g, req = alarms[x["alarm_id"]], asg[x["assignment_id"]], reqs[lots[x["lot_id"]]["requirement_id"]]
        iid = x["impact_id"]
        rep.rec("joins", "alarm_lot_impact: assignment belongs to the lot and the alarm's zone", g["lot_id"] == x["lot_id"] and g["zone_id"] == a["zone_id"], iid)
        end = E(g["stored_to"]) if g["stored_to"] else period_end + 10 * 86400
        o0, o1 = max(E(g["stored_from"]), E(a["breach_start"])), min(end, E(a["breach_end"]))
        rep.rec("arithmetic", "alarm_lot_impact: overlap derived from breach window x stay", o1 > o0 and E(x["overlap_start"]) == o0 and E(x["overlap_end"]) == o1 and int(x["overlap_minutes"]) == (o1 - o0) // 60, iid)
        atype, pk = a["alarm_type"], float(a["peak_value"])
        if atype in ("SENSOR_GAP", "SENSOR_DRIFT") or (atype in ("TEMP_HIGH", "TEMP_LOW") and any(
                ds <= E(a["breach_end"]) and de >= E(a["breach_start"]) for ds, de in drift_windows.get(a["sensor_id"], []))):
            exp = "UNVERIFIED"
        else:
            viol = ((atype == "TEMP_HIGH" and pk > float(req["temp_max_c"])) or (atype == "TEMP_LOW" and pk < float(req["temp_min_c"])) or
                    (atype == "HUMIDITY_HIGH" and req["humidity_max_pct"] != "" and pk > float(req["humidity_max_pct"])))
            exp = "NONE" if not viol else ("MAJOR" if int(x["overlap_minutes"]) >= int(req["max_excursion_min"]) else "MINOR")
        rep.rec("arithmetic", "alarm_lot_impact: impact_level follows the requirement rule", x["impact_level"] == exp, (iid, x["impact_level"], exp))
        rem = rems.get(x["remediation_id"]) if x["remediation_id"] else None
        disp = x["disposition"]
        ok = ((disp == "NO_ACTION" and rem is None) or
              (disp == "HOLD_PLACED" and rem and rem["action_type"] == "QUARANTINE_LOT" and rem["alarm_id"] == x["alarm_id"] and rem["lot_id"] == x["lot_id"]) or
              (disp == "SHIPPED_BEFORE_ACTION" and rem and rem["action_type"] == "NOTIFY_CUSTOMER" and rem["lot_id"] == x["lot_id"]) or
              (disp == "ALREADY_HELD" and rem and rem["action_type"] == "QUARANTINE_LOT" and rem["lot_id"] == x["lot_id"]))
        rep.rec("lifecycle", "alarm_lot_impact: disposition consistent with linked remediation", bool(ok), (iid, disp))
        rep.rec("lifecycle", "alarm_lot_impact: every MAJOR impact has a remediation or is a cut-off artefact",
                x["impact_level"] != "MAJOR" or rem is not None or a["status"] in ("OPEN", "ACKNOWLEDGED", "ESCALATED", "UNDER_INSPECTION"), iid)

    # ---- lot history
    lh = defaultdict(list)
    for e in d["lot_state_history"]:
        lh[e["lot_id"]].append(e)
    for lid, l in lots.items():
        evs = sorted(lh[lid], key=lambda e: e["event_id"])
        rep.rec("lifecycle", "lot_state_history: every lot has a history", bool(evs), lid)
        if not evs:
            continue
        prev, pts = None, 0
        for e in evs:
            ok = (e["from_state"] or None) == prev and e["to_state"] in LOT_TRANSITIONS.get(prev, set())
            rep.rec("lifecycle", "lot_state_history: transitions follow the allowed lifecycle", ok, (lid, e["from_state"], e["to_state"]))
            rep.rec("dates", "lot_state_history: timestamps non-decreasing", E(e["event_ts"]) >= pts, lid)
            hold_ok = (e["reason"] == "ALARM_HOLD") == (e["to_state"] == "QUARANTINED")
            rep.rec("lifecycle", "lot_state_history: reason consistent with state", hold_ok, (lid, e["reason"], e["to_state"]))
            if e["to_state"] == "QUARANTINED":
                rep.rec("joins", "lot_state_history: ALARM_HOLD references a QUARANTINE_LOT remediation",
                        e["remediation_id"] in rems and rems[e["remediation_id"]]["action_type"] == "QUARANTINE_LOT" and rems[e["remediation_id"]]["lot_id"] == lid, lid)
            prev, pts = e["to_state"], E(e["event_ts"])
        rep.rec("arithmetic", "inventory_lot: current_state equals latest history state", l["current_state"] == prev, lid)
        rep.rec("dates", "lot_state_history: RECEIVED event equals received_at", evs[0]["event_ts"] == l["received_at"], lid)
        last_asg = max(by_lot[lid], key=lambda a: E(a["stored_from"]))
        rep.rec("lifecycle", "lot stay closed exactly when the lot is SHIPPED/DISPOSED",
                (last_asg["stored_to"] != "") == (prev in ("SHIPPED", "DISPOSED")), (lid, prev))


def write_reports(rep: Report, out_dir: str):
    os.makedirs(os.path.join(out_dir, "reports"), exist_ok=True)
    with open(os.path.join(out_dir, "reports", "validation_report.json"), "w", encoding="utf-8", newline="\n") as f:
        json.dump(rep.to_dict(), f, indent=1, default=str)
    with open(os.path.join(out_dir, "reports", "validation_summary.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write(rep.markdown())
