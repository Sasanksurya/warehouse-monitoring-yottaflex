"""Stage 4: the monitoring rule engine. It sees ONLY telemetry, door events and zone thresholds
(never the ground truth) and produces alarms and explicit sensor-gap records.

Rules (see RULES in config.py, exported as monitoring_rules.json):
  TEMP_HIGH / TEMP_LOW   any TEMP sensor outside [temp_min_c, temp_max_c] for >= min_breach_readings consecutive
                         intervals; a limit-equal value is not a breach; missing data ends a run
  HUMIDITY_HIGH          HUM reading above humidity_max_pct for >= min_breach_readings consecutive intervals
  DOOR_OPEN_TOO_LONG     door open longer than zone.door_open_limit_s (alarm opens when the limit is crossed)
  OCCUPANCY_LIMIT        OCC reading above zone.max_occupancy
  SENSOR_GAP             >= min_gap_readings consecutive missing readings (every gap is also recorded in sensor_gap)
  SENSOR_DRIFT           |daily mean(TEMP-01 - TEMP-02)| > drift_threshold_c for >= drift_min_days consecutive days
"""
from __future__ import annotations

from .config import RULES, INTERVAL_S, STEPS_PER_DAY
from .util import World, iso


def _runs(flags):
    """Yield (start, end_exclusive) of consecutive True values."""
    start = None
    for i, f in enumerate(flags):
        if f and start is None:
            start = i
        elif not f and start is not None:
            yield start, i
            start = None
    if start is not None:
        yield start, len(flags)


def _alarm_runs(flags, min_len, clear):
    """Breach runs of >= min_len consecutive readings, merged when separated by fewer than `clear` readings."""
    out = []
    for a, b in _runs(flags):
        if b - a < min_len:
            continue
        if out and a - out[-1][1] < clear:
            out[-1] = (out[-1][0], b)
        else:
            out.append((a, b))
    return out


def detect(w: World) -> None:
    clock, n = w.clock, w.cfg.n_steps
    zones = sorted(w.tables["zone"], key=lambda z: z["zone_id"])
    sensors_by_zone = {}
    for s in sorted(w.tables["sensor"], key=lambda s: s["sensor_id"]):
        sensors_by_zone.setdefault(s["home_zone_id"], {}).setdefault(s["sensor_type"], []).append(s["sensor_id"])
    doors_by_zone = {}
    for d in w.tables["door_event"]:
        doors_by_zone.setdefault(d["zone_id"], []).append(d)
    # Pipeline defect used for the edge case "reading gap treated as normal": gap detection is suppressed
    # for these zone windows, so neither a sensor_gap row nor a SENSOR_GAP alarm is produced.
    suppressed = w.plans.get("hidden_gaps", {})
    minb = RULES["min_breach_readings"]
    alarms, gaps = [], []

    def alarm(atype, zone, sensor, sev, b0, b1, opened, peak, thr, unit):
        alarms.append({"alarm_type": atype, "zone_id": zone["zone_id"], "sensor_id": sensor, "severity": sev,
                       "_start": b0, "_end": b1, "_open": opened, "peak_value": round(peak, 2),
                       "threshold_value": thr, "threshold_unit": unit})

    for z in zones:
        zid = z["zone_id"]
        sens = sensors_by_zone[zid]
        temps = [(sid, w.readings[sid]) for sid in sens["TEMP"]]
        hum = [(sid, w.readings[sid]) for sid in sens["HUM"]]
        occ = [(sid, w.readings[sid]) for sid in sens["OCC"]]

        # ---- temperature (high and low) and humidity
        tmax_v, tmin_v = [None] * n, [None] * n
        for i in range(n):
            vs = [(v[i], sid) for sid, v in temps if v[i] is not None]
            if vs:
                tmax_v[i], tmin_v[i] = max(vs), min(vs)
        for atype, vals, limit, high in (("TEMP_HIGH", tmax_v, z["temp_max_c"], True), ("TEMP_LOW", tmin_v, z["temp_min_c"], False)):
            flags = [(v is not None and ((v[0] > limit) if high else (v[0] < limit))) for v in vals]
            for a, b in _alarm_runs(flags, minb, RULES["clear_readings"]):
                seen = [vals[i] for i in range(a, b) if vals[i] is not None]
                pk = max(seen) if high else min(seen)
                dev = abs(pk[0] - limit)
                dur_min = (b - a) * INTERVAL_S / 60
                sev = "CRITICAL" if dev >= RULES["critical_temp_margin_c"] or dur_min >= RULES["critical_duration_min"] else "WARNING"
                alarm(atype, z, pk[1], sev, clock.epoch(a), clock.epoch(b), clock.epoch(a + minb - 1), pk[0], limit, "C")
        for sid, vals in hum:
            limit = z["humidity_max_pct"]
            flags = [(v is not None and v > limit) for v in vals]
            for a, b in _alarm_runs(flags, minb, RULES["clear_readings"]):
                pk = max(v for v in vals[a:b] if v is not None)
                dur_min = (b - a) * INTERVAL_S / 60
                sev = "CRITICAL" if pk - limit >= RULES["critical_humidity_margin_pct"] or dur_min >= RULES["critical_duration_min"] else "WARNING"
                alarm("HUMIDITY_HIGH", z, sid, sev, clock.epoch(a), clock.epoch(b), clock.epoch(a + minb - 1), pk, limit, "PCT_RH")

        # ---- occupancy
        for sid, vals in occ:
            flags = [(v is not None and v > z["max_occupancy"]) for v in vals]
            for a, b in _runs(flags):
                alarm("OCCUPANCY_LIMIT", z, sid, "WARNING", clock.epoch(a), clock.epoch(b), clock.epoch(a),
                      max(vals[a:b]), z["max_occupancy"], "PERSONS")

        # ---- doors
        limit = z["door_open_limit_s"]
        for d in doors_by_zone.get(zid, []):
            if d["duration_s"] > limit:
                sev = "CRITICAL" if d["duration_s"] >= RULES["door_critical_multiple"] * limit else "WARNING"
                alarm("DOOR_OPEN_TOO_LONG", z, d["sensor_id"], sev, d["_open"], d["_close"], d["_open"] + limit,
                      d["duration_s"], limit, "SECONDS")

        # ---- explicit sensor gaps
        sup = suppressed.get(zid)
        for sid, vals in temps + hum + occ:
            for a, b in _runs([v is None for v in vals]):
                if sup and sup[0] <= a < sup[1]:
                    continue
                gaps.append({"gap_id": f"GAP-{sid}-{clock.compact(a)}", "sensor_id": sid, "zone_id": zid,
                             "gap_start": clock.iso(a), "gap_end": clock.iso(b), "missed_readings": b - a,
                             "alarm_raised": (b - a) >= RULES["min_gap_readings"]})
                if b - a >= RULES["min_gap_readings"]:
                    sev = "CRITICAL" if b - a >= RULES["gap_critical_readings"] else "WARNING"
                    alarm("SENSOR_GAP", z, sid, sev, clock.epoch(a), clock.epoch(b), clock.epoch(a + RULES["min_gap_readings"]),
                          b - a, RULES["min_gap_readings"], "READINGS")

        # ---- drift between the two TEMP sensors (daily means)
        if len(temps) == 2:
            (s1, v1), (s2, v2) = temps
            days = n // STEPS_PER_DAY
            means, flagged = [], []
            for d in range(days):
                diffs = [v1[i] - v2[i] for i in range(d * STEPS_PER_DAY, (d + 1) * STEPS_PER_DAY)
                         if v1[i] is not None and v2[i] is not None]
                m = sum(diffs) / len(diffs) if len(diffs) >= STEPS_PER_DAY // 2 else 0.0
                means.append(m)
                flagged.append(abs(m) > RULES["drift_threshold_c"])
            for a, b in _runs(flagged):
                if b - a < RULES["drift_min_days"]:
                    continue
                sp = z["setpoint_c"]
                dev1 = sum(abs(v - sp) for v in v1[a * STEPS_PER_DAY:b * STEPS_PER_DAY] if v is not None)
                dev2 = sum(abs(v - sp) for v in v2[a * STEPS_PER_DAY:b * STEPS_PER_DAY] if v is not None)
                culprit = s1 if dev1 >= dev2 else s2
                alarm("SENSOR_DRIFT", z, culprit, "WARNING", w.cfg.start_epoch + a * 86400, w.cfg.start_epoch + b * 86400,
                      w.cfg.start_epoch + (a + RULES["drift_min_days"]) * 86400,
                      max(abs(m) for m in means[a:b]), RULES["drift_threshold_c"], "C")

    alarms.sort(key=lambda a: (a["_open"], a["zone_id"], a["alarm_type"], a["sensor_id"]))
    gaps.sort(key=lambda g: g["gap_id"])
    w.plans["raw_alarms"] = alarms
    w.tables["sensor_gap"] = gaps
