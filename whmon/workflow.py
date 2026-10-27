"""Stage 5: operational workflow simulation on top of the engine's alarms.

For every alarm (numbered in opened_at order): acknowledgement, escalation, inspection, remediation, closure,
with all state changes persisted as events (alarm_state_history, lot_state_history). Affected lots are found by
time + zone overlap between the breach window and each lot's stay; impact level follows the lot's storage
requirement. Hold / dispose / release actions change lot lifecycle state. Events after the data cutoff are not emitted.

The simulated 'world' (inspection outcomes, whether a hold ends in disposal) may consult the generator's
ground truth, because a real inspector would find the real cause; the detection stage never does."""
from __future__ import annotations

import json

from .config import RULES, RATES, LOT_YEAR
from .util import World, rng_for, iso, parse_iso

ELIGIBLE = set(RULES["lot_link_alarm_types"])
SECONDARY = {"TEMP_HIGH", "TEMP_LOW", "HUMIDITY_HIGH"}


def _truth_index(w):
    idx = {}
    for t in w.truth:
        if not t["zone_id"] or not t["window_start"] or not t["window_end"]:
            continue
        if t["entity_type"] not in ("ZONE_EVENT", "SENSOR", "DOOR_EVENT"):
            continue
        d = json.loads(t["details"])
        idx.setdefault(t["zone_id"], []).append({
            "s": parse_iso(t["window_start"]), "e": parse_iso(t["window_end"]), "types": set(filter(None, t["expected_alarm_types"].split("|"))),
            "secondary": set(d.get("secondary_alarm_types", [])), "cause": d.get("cause", ""), "issue": t["issue_type"],
            "sensor": t["sensor_id"]})
    return idx


def _cause(a, tidx, drift_plan):
    for t in tidx.get(a["zone_id"], []):
        if a["alarm_type"] in t["types"] and a["_start"] < t["e"] + 1800 and a["_end"] > t["s"] - 1800:
            return t["cause"]
        if a["alarm_type"] in t["secondary"] and a["_start"] < t["e"] + 4 * 3600 and a["_end"] > t["s"] - 1800:
            return t["cause"]
    if a["alarm_type"] in ("SENSOR_DRIFT",) or a["sensor_id"] in drift_plan:
        return "SENSOR_FAULT"
    if a["alarm_type"] == "DOOR_OPEN_TOO_LONG":
        return "DOOR_PROCEDURE"
    if a["alarm_type"] == "SENSOR_GAP":
        return "CONNECTIVITY_FAULT"
    return "NONE"


def run_workflow(w: World) -> None:
    cfg = w.cfg
    cutoff = cfg.end_epoch
    zones = {z["zone_id"]: z for z in w.tables["zone"]}
    reqs = {r["requirement_id"]: r for r in w.tables["storage_requirement"]}
    lots = {l["lot_id"]: l for l in w.tables["inventory_lot"]}
    tidx = _truth_index(w)
    drift_plan = w.plans.get("drift", {})
    drift_alarms = {}
    for x in w.plans["raw_alarms"]:
        if x["alarm_type"] == "SENSOR_DRIFT":
            drift_alarms.setdefault(x["sensor_id"], []).append((x["_start"], x["_end"]))

    # ---- lot runtime state
    rt = {}
    for a in sorted(w.tables["lot_zone_assignment"], key=lambda a: (a["lot_id"], a["stored_from"])):
        rt.setdefault(a["lot_id"], {"assigns": []})["assigns"].append(a)
    zone_assigns = {}
    for lid, r in rt.items():
        l = lots[lid]
        first, last = r["assigns"][0], r["assigns"][-1]
        r.update(ship_at=last["stored_to"], disposed=False, holds=[], last_ts=first["stored_from"],
                 events=[(parse_iso(l["received_at"]), None, "RECEIVED", "RECEIPT", None),
                         (first["stored_from"], "RECEIVED", "STORED", "PUTAWAY", None)], orig_ship=last["stored_to"])
        for a in r["assigns"]:
            zone_assigns.setdefault(a["zone_id"], []).append(a)

    out = {k: [] for k in ("alarm", "alarm_state_history", "inspection", "remediation", "alarm_lot_impact")}
    counters = {"ins": 0, "rem": 0, "imp": 0}

    def nid(prefix, key, year=True):
        counters[key] += 1
        return f"{prefix}-{LOT_YEAR}-{counters[key]:06d}" if year else f"{prefix}-{counters[key]:06d}"

    for idx, a in enumerate(w.plans["raw_alarms"], start=1):
        aid = f"ALM-{LOT_YEAR}-{idx:06d}"
        rng = rng_for(cfg, "workflow", aid)
        zone = zones[a["zone_id"]]
        atype, crit = a["alarm_type"], a["severity"] == "CRITICAL"
        events, status, stopped = [], None, False

        def ev(etype, to, ts, role, ref=None):
            nonlocal status, stopped
            if stopped or ts > cutoff:
                stopped = True
                return False
            events.append({"alarm_id": aid, "event_type": etype, "from_status": status, "to_status": to,
                           "event_ts": ts, "actor_role": role, "reference_id": ref})
            status = to
            return True

        # ---- affected lots (time + zone overlap)
        impacts, candidates = [], []
        if atype in ELIGIBLE:
            for asg in zone_assigns.get(a["zone_id"], []):
                a_end = asg["stored_to"] if asg["stored_to"] is not None else cutoff + 10 * 86400
                o0, o1 = max(asg["stored_from"], a["_start"]), min(a_end, a["_end"])
                if o1 - o0 >= 60:
                    candidates.append((asg, o0, o1))
            candidates.sort(key=lambda c: c[0]["lot_id"])
        unlinked = bool(candidates) and rng.random() < RATES["alarm_unlinked_prob"]
        if unlinked:
            w.add_truth("ALARM_NOT_LINKED_TO_LOTS", "ALARM", aid, zone_id=a["zone_id"], sensor_id=a["sensor_id"],
                        window_start=iso(a["_start"]), window_end=iso(a["_end"]),
                        expected_decision="LINK_AFFECTED_LOTS", linked_entities="|".join(c[0]["lot_id"] for c in candidates),
                        details={"alarm_type": atype, "expected_lot_count": len(candidates)})
        else:
            for asg, o0, o1 in candidates:
                req = reqs[lots[asg["lot_id"]]["requirement_id"]]
                if atype in ("SENSOR_GAP", "SENSOR_DRIFT") or (
                        atype in ("TEMP_HIGH", "TEMP_LOW") and any(
                            ds <= a["_end"] and de >= a["_start"] for ds, de in drift_alarms.get(a["sensor_id"], []))):
                    level = "UNVERIFIED"   # redundant-sensor cross-check: a breach seen only by a drifting sensor is unverified
                else:
                    pk = a["peak_value"]
                    viol = ((atype == "TEMP_HIGH" and pk > req["temp_max_c"]) or (atype == "TEMP_LOW" and pk < req["temp_min_c"]) or
                            (atype == "HUMIDITY_HIGH" and req["humidity_max_pct"] is not None and pk > req["humidity_max_pct"]))
                    level = "NONE" if not viol else ("MAJOR" if (o1 - o0) // 60 >= req["max_excursion_min"] else "MINOR")
                impacts.append({"impact_id": nid("IMP", "imp", False), "alarm_id": aid, "lot_id": asg["lot_id"],
                                "assignment_id": asg["assignment_id"], "_o0": o0, "_o1": o1, "impact_level": level,
                                "disposition": "NO_ACTION", "remediation_id": None})
        major = [i for i in impacts if i["impact_level"] == "MAJOR"]

        # ---- acknowledgement / escalation
        t = a["_open"]
        ev("OPENED", "OPEN", t, "SYSTEM")
        ack = t + (rng.randint(60, 900) if crit else rng.randint(120, 2400))
        ev("ACKNOWLEDGED", "ACKNOWLEDGED", ack, "PLANT_OPERATOR")
        esc = None
        if crit and atype in SECONDARY:
            esc = ack + rng.randint(300, 1500)
            ev("ESCALATED", "ESCALATED", esc, "PLANT_OPERATOR")

        # ---- inspection decision
        role = None
        if atype in SECONDARY:
            role = "QUALITY_ENGINEER" if (crit or major) else ("MAINTENANCE_ENGINEER" if rng.random() < 0.5 else None)
        elif atype == "DOOR_OPEN_TOO_LONG":
            role = "MAINTENANCE_ENGINEER" if rng.random() < (0.8 if crit else 0.3) else None
        elif atype == "SENSOR_GAP":
            role = "OT_IT_ADMIN" if (a["peak_value"] >= RULES["gap_critical_readings"] or rng.random() < 0.4) else None
        elif atype == "SENSOR_DRIFT":
            role = "MAINTENANCE_ENGINEER"

        ins, rems, immediate_ts = None, [], []
        if role is None:
            ev("CLOSED", "CLOSED", ack + rng.randint(600, 7200), "PLANT_OPERATOR")
        else:
            sched = (esc or ack) + rng.randint(20, 180) * 60
            if sched <= cutoff:
                started = sched + rng.randint(5, 60) * 60
                completed = started + rng.randint(30, 240) * 60
                cause = _cause(a, tidx, drift_plan)
                outcome = {"EQUIPMENT_FAULT": "EQUIPMENT_FAULT" if rng.random() < 0.9 else "NO_FAULT_FOUND",
                           "DOOR_PROCEDURE": "DOOR_PROCEDURE", "SENSOR_FAULT": "SENSOR_FAULT",
                           "CONNECTIVITY_FAULT": "CONNECTIVITY_FAULT"}.get(cause, "NO_FAULT_FOUND")
                ins = {"inspection_id": nid("INS", "ins"), "alarm_id": aid, "zone_id": a["zone_id"], "inspector_role": role,
                       "scheduled_at": sched, "started_at": started if started <= cutoff else None,
                       "completed_at": completed if completed <= cutoff else None,
                       "status": "COMPLETED" if completed <= cutoff else ("IN_PROGRESS" if started <= cutoff else "SCHEDULED"),
                       "outcome": outcome if completed <= cutoff else None}
                out["inspection"].append(ins)
                ev("INSPECTION_STARTED", "UNDER_INSPECTION", started, role, ins["inspection_id"])
                if completed <= cutoff:
                    rem_ts = completed + rng.randint(600, 7200)

                    def add_rem(action, owner, ts, sensor=None, lot=None, units=None):
                        r = {"remediation_id": nid("REM", "rem"), "alarm_id": aid, "inspection_id": ins["inspection_id"],
                             "zone_id": a["zone_id"], "sensor_id": sensor, "lot_id": lot, "action_type": action,
                             "owner_role": owner, "performed_at": ts, "status": "COMPLETED", "units_affected": units}
                        out["remediation"].append(r)
                        rems.append(r)
                        return r

                    simple = {"EQUIPMENT_FAULT": ("REPAIR_EQUIPMENT", "MAINTENANCE_ENGINEER", None),
                              "DOOR_PROCEDURE": ("DOOR_SEAL_REPAIR", "MAINTENANCE_ENGINEER", None),
                              "SENSOR_FAULT": ("RECALIBRATE_SENSOR", "MAINTENANCE_ENGINEER", a["sensor_id"]),
                              "CONNECTIVITY_FAULT": ("RESTORE_CONNECTIVITY", "OT_IT_ADMIN", a["sensor_id"])}.get(outcome)
                    if simple:
                        ts = rem_ts
                        if outcome == "SENSOR_FAULT" and a["sensor_id"] in drift_plan:
                            ts = max(ts, drift_plan[a["sensor_id"]])
                        if ts <= cutoff:
                            add_rem(simple[0], simple[1], ts, sensor=simple[2])
                            immediate_ts.append(ts)
                    for k, imp in enumerate(sorted(major, key=lambda i: i["lot_id"])):
                        _lot_action(w, a, imp, ins, rt, lots, add_rem, rng, rem_ts + 30 * k, cutoff, immediate_ts)
                    if immediate_ts:
                        last = max(immediate_ts)
                        owner = next((r["owner_role"] for r in rems if r["performed_at"] == last), "MAINTENANCE_ENGINEER")
                        ev("REMEDIATION_COMPLETED", "REMEDIATED", last, owner, next(r["remediation_id"] for r in rems if r["performed_at"] == last))
                        ev("CLOSED", "CLOSED", last + rng.randint(300, 3600), "PLANT_OPERATOR")
                    else:
                        ev("CLOSED", "CLOSED", completed + rng.randint(300, 3600), "PLANT_OPERATOR")
        closed_ev = next((e for e in events if e["to_status"] == "CLOSED"), None)
        out["alarm"].append({
            "alarm_id": aid, "zone_id": a["zone_id"], "sensor_id": a["sensor_id"], "alarm_type": atype, "severity": a["severity"],
            "breach_start": iso(a["_start"]), "breach_end": iso(a["_end"]), "opened_at": iso(a["_open"]),
            "closed_at": iso(closed_ev["event_ts"]) if closed_ev else None, "status": status,
            "peak_value": a["peak_value"], "threshold_value": a["threshold_value"], "threshold_unit": a["threshold_unit"],
            "duration_minutes": (a["_end"] - a["_start"]) // 60, "_start": a["_start"], "_end": a["_end"]})
        out["alarm_state_history"] += events
        out["alarm_lot_impact"] += impacts

    for k, v in out.items():
        w.tables[k] = v
    _finalize(w, rt, lots, cutoff)


def _lot_action(w, a, imp, ins, rt, lots, add_rem, rng, q0, cutoff, immediate_ts):
    lot = lots[imp["lot_id"]]
    r = rt[imp["lot_id"]]
    qty = lot["quantity_units"]
    q_raw = max(q0, r["assigns"][0]["stored_from"] + 1800)
    if q_raw > cutoff:
        return
    # Simplification (documented): if the lot is held at, or at any time after, this action time, the earlier
    # hold already covers it, so the impact is linked to that hold instead of creating overlapping holds.
    for rem_id, hs, he in r["holds"]:
        if he is None or q_raw < he:
            imp["disposition"], imp["remediation_id"] = "ALREADY_HELD", rem_id
            return
    if r["disposed"]:
        imp["disposition"], imp["remediation_id"] = "ALREADY_HELD", r["holds"][-1][0]
        return
    q = max(q_raw, r["last_ts"] + 60)
    if r["ship_at"] is not None and q >= r["ship_at"]:
        rem = add_rem("NOTIFY_CUSTOMER", "PRODUCTION_PLANNER", q, lot=imp["lot_id"], units=qty)
        imp["disposition"], imp["remediation_id"] = "SHIPPED_BEFORE_ACTION", rem["remediation_id"]
        immediate_ts.append(q)
        return
    rem = add_rem("QUARANTINE_LOT", "QUALITY_ENGINEER", q, lot=imp["lot_id"], units=qty)
    imp["disposition"], imp["remediation_id"] = "HOLD_PLACED", rem["remediation_id"]
    immediate_ts.append(q)
    r["events"].append((q, "STORED", "QUARANTINED", "ALARM_HOLD", rem["remediation_id"]))
    r["last_ts"] = q
    last_asg = r["assigns"][-1]
    resolve = max(q + rng.randint(1 * 86400, 4 * 86400), last_asg["stored_from"] + 3600)
    p_dispose = {"PHARMA_COLD": 0.85, "FROZEN_FOOD": 0.7}.get(lot["product_category"], 0.55)
    dispose = rng.random() < p_dispose
    if resolve > cutoff:                              # still on hold at the data cutoff
        r["holds"].append((rem["remediation_id"], q, None))
        r["ship_at"], last_asg["stored_to"] = None, None
        return
    if dispose:
        rem2 = add_rem("DISPOSE_LOT", "QUALITY_ENGINEER", resolve, lot=imp["lot_id"], units=qty)
        r["events"].append((resolve, "QUARANTINED", "DISPOSED", "DISPOSAL", rem2["remediation_id"]))
        r["holds"].append((rem["remediation_id"], q, resolve))
        r.update(disposed=True, ship_at=None, last_ts=resolve)
        last_asg["stored_to"] = resolve
    else:
        rem2 = add_rem("RELEASE_LOT", "PRODUCTION_PLANNER", resolve, lot=imp["lot_id"], units=qty)
        r["events"].append((resolve, "QUARANTINED", "STORED", "RELEASED_FROM_HOLD", rem2["remediation_id"]))
        r["holds"].append((rem["remediation_id"], q, resolve))
        r["last_ts"] = resolve
        ship = max(resolve + rng.randint(3600, 86400), r["orig_ship"] or 0)
        r["ship_at"] = ship if ship <= cutoff else None
        last_asg["stored_to"] = r["ship_at"]


def _finalize(w, rt, lots, cutoff):
    """Persist runtime state as rows: lot history, current_state, ISO timestamps, derived fields."""
    from collections import defaultdict
    lse = []
    for lid in sorted(rt):
        r = rt[lid]
        evs = list(r["events"])
        if r["ship_at"] is not None and not r["disposed"]:
            evs.append((r["ship_at"], "STORED", "SHIPPED", "SHIPMENT", None))
        evs.sort(key=lambda e: e[0])
        for ts, frm, to, reason, rem in evs:
            lse.append({"lot_id": lid, "from_state": frm, "to_state": to, "event_ts": iso(ts), "reason": reason, "remediation_id": rem})
        lots[lid]["current_state"] = evs[-1][2]
    for i, e in enumerate(lse, start=1):
        e["event_id"] = f"LSE-{i:06d}"
    w.tables["lot_state_history"] = lse

    for a in w.tables["lot_zone_assignment"]:
        a["dwell_minutes"] = (a["stored_to"] - a["stored_from"]) // 60 if a["stored_to"] is not None else None
        a["_from"], a["_to"] = a["stored_from"], a["stored_to"]
        a["stored_from"] = iso(a["stored_from"])
        a["stored_to"] = iso(a["stored_to"]) if a["stored_to"] is not None else None

    # recompute impact overlap from FINAL stays (derived value); drop zero-overlap rows that carry no action
    asg = {a["assignment_id"]: a for a in w.tables["lot_zone_assignment"]}
    alarm_win = {x["alarm_id"]: (x["_start"], x["_end"]) for x in w.tables["alarm"]}
    kept = []
    for imp in w.tables["alarm_lot_impact"]:
        s, e = alarm_win[imp["alarm_id"]]
        a = asg[imp["assignment_id"]]
        o0, o1 = max(a["_from"], s), min(a["_to"] if a["_to"] is not None else cutoff + 10 * 86400, e)
        if o1 - o0 < 60 and imp["remediation_id"] is None:
            continue
        imp["overlap_start"], imp["overlap_end"], imp["overlap_minutes"] = iso(o0), iso(max(o1, o0 + 60)), max(1, (o1 - o0) // 60)
        kept.append(imp)
    for i, imp in enumerate(kept, start=1):
        imp["impact_id"] = f"IMP-{i:06d}"
    w.tables["alarm_lot_impact"] = kept

    for tname, fields in (("inspection", ("scheduled_at", "started_at", "completed_at")), ("remediation", ("performed_at",))):
        for row in w.tables[tname]:
            for f in fields:
                row[f] = iso(row[f]) if row[f] is not None else None
    hist = sorted(w.tables["alarm_state_history"], key=lambda e: (e["alarm_id"], e["event_ts"]))
    for i, e in enumerate(hist, start=1):
        e["event_id"] = f"AEV-{i:06d}"
        e["event_ts"] = iso(e["event_ts"])
    w.tables["alarm_state_history"] = hist
