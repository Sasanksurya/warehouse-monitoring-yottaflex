"""Stage 3: door events and sensor readings per zone, with labelled injected conditions.

Physics model (per zone, per 15-minute step):
  zone temperature = setpoint + diurnal + AR(1) deviation (door-open load pushes it) + injected overlay
  sensors add bias + noise (+ slow drift on one sensor in selected zones)
Injected conditions are written to the ground-truth list, never into the input tables."""
from __future__ import annotations

import math

from .config import ZONE_SPECS, RATES, INTERVAL_S, STEPS_PER_DAY, DOOR_REASONS, RULES
from .util import World, rng_for, poisson, weighted_choice, iso, compact


def _shape(L: int, r: int):
    """Trapezoid fractions: ramp up r steps, plateau, ramp down r steps."""
    fr = []
    for j in range(L):
        if j < r:
            fr.append((j + 1) / (r + 1))
        elif j >= L - r:
            fr.append((L - j) / (r + 1))
        else:
            fr.append(1.0)
    return fr


class _Zone:
    """Per-zone injection planner; keeps a list of busy step windows to avoid overlapping injections."""

    def __init__(self, n, rng):
        self.n, self.rng, self.busy = n, rng, []

    def place(self, L, buffer=6):
        for _ in range(40):
            s = self.rng.randint(2, max(2, self.n - L - 3))
            if s + L > self.n - 2:
                continue
            if all(s + L + buffer <= b0 or s >= b1 + buffer for b0, b1 in self.busy):
                self.busy.append((s, s + L))
                return s
        return None


def build_telemetry(w: World) -> None:
    cfg, clock, n = w.cfg, w.clock, w.cfg.n_steps
    zones = sorted(w.tables["zone"], key=lambda z: z["zone_id"])
    wh_offset = {x["warehouse_id"]: x["utc_offset_minutes"] * 60 for x in w.tables["warehouse"]}
    by_zone = {}
    for s in sorted(w.tables["sensor"], key=lambda s: s["sensor_id"]):
        by_zone.setdefault(s["home_zone_id"], {}).setdefault(s["sensor_type"], []).append(s["sensor_id"])

    plan_rng = rng_for(cfg, "plan")
    nz = len(zones)
    k_hidden = max(1, round(RATES["hidden_gap_zone_fraction"] * nz)) if cfg.scale.days >= 6 else 0
    hidden = {}
    for zid in sorted(plan_rng.sample([z["zone_id"] for z in zones], min(k_hidden, nz))):
        gl = plan_rng.randint(8, 24)
        gs = plan_rng.randint(2 * STEPS_PER_DAY, n - 3 * STEPS_PER_DAY - gl)
        hidden[zid] = (gs, gs + gl)
    w.plans["hidden_gaps"] = hidden
    w.plans["drift"] = {}
    w.plans["door_events"] = []
    door_rows = []
    for z in zones:
        door_rows += _build_zone(w, z, by_zone[z["zone_id"]], hidden.get(z["zone_id"]), wh_offset[z["warehouse_id"]])
    door_rows.sort(key=lambda d: (d["zone_id"], d["_open"]))
    w.tables["door_event"] = door_rows


def _build_zone(w, z, sensors, hidden, offset):
    cfg, clock, n = w.cfg, w.clock, w.cfg.n_steps
    zid = z["zone_id"]
    spec = ZONE_SPECS[z["zone_type"]]
    rng = rng_for(cfg, "telemetry", zid)
    days = cfg.scale.days
    start, end = cfg.start_epoch, cfg.end_epoch
    half = (spec.temp_max_c - spec.temp_min_c) / 2
    plan = _Zone(n, rng)
    ovT, ovH, occ_over = [0.0] * n, [0.0] * n, {}
    injected_doors = []

    local_hour = [((start + i * INTERVAL_S + offset) % 86400) / 3600 for i in range(n)]

    def add_truth(issue, entity_id, s, L, decision, alarm_types, details, sensor_id="", entity_type="ZONE_EVENT"):
        w.add_truth(issue, entity_type, entity_id, zone_id=zid, sensor_id=sensor_id, window_start=clock.iso(s),
                    window_end=clock.iso(s + L), expected_decision=decision, expected_alarm_types=alarm_types, details=details)

    # ---- edge case: zone-wide outage hiding a real excursion (all reading sensors silent)
    hidden_gap = None
    if hidden:
        gs, ge = hidden
        plan.busy.append((gs, ge))
        direction = -1 if z["zone_type"] == "HOT" else 1
        margin = rng.uniform(4.0, 8.0)
        L2 = ge - gs - 2
        fr = _shape(L2, 2)
        for j in range(L2):
            ovT[gs + 1 + j] = direction * (half + margin) * fr[j]
        hidden_gap = (gs, ge)
        add_truth("GAP_TREATED_AS_NORMAL", f"HGAP-{zid}-{clock.compact(gs)}", gs, ge - gs,
                  "RAISE_SENSOR_GAP_ALARM_AND_INSPECT", "SENSOR_GAP",
                  {"silent_sensors": [s for t in ("TEMP", "HUM", "OCC") for s in sensors[t]],
                   "hidden_peak_offset_c": round(direction * (half + margin), 2), "missed_readings": ge - gs})

    # ---- temperature excursions
    hot = z["zone_type"] == "HOT"
    for kind, rate, direction in (("fail", RATES["temp_fail"], -1 if hot else 1),
                                  ("overshoot", RATES["temp_overshoot"], 1 if hot else -1)):
        for _ in range(poisson(rng, rate * days)):
            L = min(40, 6 + int(rng.expovariate(1 / 7)))   # skewed: most failures last 2-4 h, a few last ~10 h
            s = plan.place(L)
            if s is None:
                continue
            margin = rng.uniform(2.0, 7.0)
            peak = direction * (half + margin)
            fr = _shape(L, min(2, (L - 2) // 2))
            for j in range(L):
                ovT[s + j] = peak * fr[j]
            hi = direction > 0
            add_truth("TEMP_HIGH_EXCURSION" if hi else "TEMP_LOW_EXCURSION", f"EXC-{zid}-{clock.compact(s)}", s, L,
                      "RAISE_ALARM", "TEMP_HIGH" if hi else "TEMP_LOW",
                      {"cause": "EQUIPMENT_FAULT", "mode": kind, "margin_beyond_limit_c": round(margin, 2), "steps": L})

    # ---- humidity excursions
    for _ in range(poisson(rng, RATES["humidity"] * days)):
        L = min(24, 5 + int(rng.expovariate(1 / 5)))
        s = plan.place(L)
        if s is None:
            continue
        margin = rng.uniform(4.0, 15.0)
        peak = (spec.humidity_max_pct - spec.humidity_set_pct) + margin
        fr = _shape(L, min(2, (L - 2) // 2))
        for j in range(L):
            ovH[s + j] = peak * fr[j]
        add_truth("HUMIDITY_EXCURSION", f"EXC-{zid}-{clock.compact(s)}", s, L, "RAISE_ALARM", "HUMIDITY_HIGH",
                  {"cause": "EQUIPMENT_FAULT", "margin_beyond_limit_pct": round(margin, 2), "steps": L})

    # ---- boundary (exactly min persistence -> must alarm) and transient (one reading -> must NOT alarm)
    for issue, rate, L, decision, alarm in (
            ("TEMP_BOUNDARY_MIN_PERSISTENCE", RATES["boundary_min_persistence"], RULES["min_breach_readings"], "RAISE_ALARM", None),
            ("TRANSIENT_SPIKE", RATES["transient_spike"], 1, "NO_ALARM", "")):
        for _ in range(poisson(rng, rate * days)):
            s = plan.place(L, buffer=8)
            if s is None:
                continue
            direction = rng.choice((-1, 1))
            margin = spec.diurnal_amp_c + 1.0 + rng.uniform(0, 0.8)
            for j in range(L):
                ovT[s + j] = direction * (half + margin)
            at = ("TEMP_HIGH" if direction > 0 else "TEMP_LOW") if alarm is None else alarm
            add_truth(issue, f"EXC-{zid}-{clock.compact(s)}", s, L, decision, at,
                      {"cause": "SENSOR_NOISE" if L == 1 else "EQUIPMENT_FAULT", "steps": L, "margin_beyond_limit_c": round(margin, 2)})

    # ---- occupancy excursions
    for _ in range(poisson(rng, RATES["occupancy"] * days)):
        L = rng.randint(1, 4)
        s = plan.place(L)
        if s is None:
            continue
        for j in range(L):
            occ_over[s + j] = spec.max_occupancy + rng.randint(1, 3)
        add_truth("OCCUPANCY_EXCEEDED", f"EXC-{zid}-{clock.compact(s)}", s, L, "RAISE_ALARM", "OCCUPANCY_LIMIT",
                  {"limit": spec.max_occupancy, "steps": L})

    # ---- doors left open (long events); natural events are generated around them
    for _ in range(poisson(rng, RATES["door_left_open"] * days)):
        dur = rng.randint(1500, 7200)
        L = dur // INTERVAL_S + 2
        s = plan.place(L)
        if s is None:
            continue
        opened = clock.epoch(s) + rng.randint(0, INTERVAL_S - 1)
        injected_doors.append((opened, dur))
        did = f"DOOR-{zid}-{compact(opened)}"
        w.add_truth("DOOR_LEFT_OPEN", "DOOR_EVENT", did, zone_id=zid, sensor_id=sensors["DOOR"][0],
                    window_start=iso(opened), window_end=iso(opened + dur), expected_decision="RAISE_ALARM",
                    expected_alarm_types="DOOR_OPEN_TOO_LONG",
                    details={"cause": "DOOR_PROCEDURE", "duration_s": dur, "limit_s": spec.door_open_limit_s,
                             "secondary_alarm_types": ["TEMP_HIGH", "TEMP_LOW", "HUMIDITY_HIGH"]})

    doors = _door_events(w, z, spec, sensors["DOOR"][0], rng, offset, injected_doors)

    # ---- sensor drift: one TEMP sensor drifts slowly, then is recalibrated
    drift = None
    if days >= 14 and rng.random() < RATES["drift_zone_fraction"]:
        sid = rng.choice(sensors["TEMP"])
        ramp = rng.uniform(6, 9)
        t0 = rng.uniform(0.5, max(0.6, days - 13))
        recal = t0 + ramp + rng.uniform(2, 4)
        mag = rng.choice((-1, 1)) * rng.uniform(1.8, 4.0)
        recal_epoch = start + int(recal * 86400)
        drift = (sid, t0 * 86400, ramp * 86400, mag, recal * 86400)
        w.plans["drift"][sid] = recal_epoch
        s0 = int(t0 * STEPS_PER_DAY)
        w.add_truth("SENSOR_DRIFT", "SENSOR", sid, zone_id=zid, sensor_id=sid, window_start=clock.iso(s0),
                    window_end=iso(recal_epoch), expected_decision="RAISE_ALARM_AND_RECALIBRATE",
                    expected_alarm_types="SENSOR_DRIFT",
                    details={"magnitude_c": round(mag, 2), "ramp_days": round(ramp, 2), "recalibrated_at": iso(recal_epoch),
                             "cause": "SENSOR_FAULT"})

    # ---- door load per step (fraction of the step the door was open)
    load = [0.0] * n
    for d in doors:
        a, b = d["_open"], d["_close"]
        i = max(0, (a - start) // INTERVAL_S)
        while i < n and clock.epoch(i) < b:
            lo, hi = max(a, clock.epoch(i)), min(b, clock.epoch(i) + INTERVAL_S)
            if hi > lo:
                load[i] += (hi - lo) / INTERVAL_S
            i += 1

    # ---- true zone state series
    sp, hs = spec.setpoint_c, spec.humidity_set_pct
    dsin = [spec.diurnal_amp_c * math.sin(2 * math.pi * (local_hour[i] - 9) / 24) for i in range(min(n, STEPS_PER_DAY))]
    dev = hdev = 0.0
    true_t, true_h, occ = [0.0] * n, [0.0] * n, [0] * n
    max_occ = spec.max_occupancy
    for i in range(n):
        ld = min(1.0, load[i])
        dev = 0.85 * dev + rng.gauss(0, spec.temp_noise_c) + spec.door_kick_c * ld
        hdev = 0.80 * hdev + rng.gauss(0, 1.0) + (1.0 if z["zone_type"] == "HOT" else 2.0) * ld
        true_t[i] = sp + dsin[i % STEPS_PER_DAY] + dev + ovT[i]
        true_h[i] = hs + 2.0 * math.sin(2 * math.pi * (local_hour[i] - 14) / 24) + hdev + ovH[i]
        active = 6 <= local_hour[i] < 22
        lam = (0.18 * max_occ if active else 0.02) + 0.8 * ld
        occ[i] = occ_over.get(i, min(max_occ, poisson(rng, lam)))

    # ---- sensors: bias + noise (+ drift), then outages (gaps)
    outage_windows = {}
    outage_rate = RATES["outage_per_sensor_27d"] * days / 27
    for stype in ("TEMP", "HUM", "OCC"):
        for sid in sensors[stype]:
            bias = rng.gauss(0, 0.10 if stype == "TEMP" else 0.4)
            vals = [None] * n
            for i in range(n):
                if stype == "TEMP":
                    v = true_t[i] + bias + rng.gauss(0, 0.12)
                    if drift and drift[0] == sid:
                        t = i * INTERVAL_S
                        if t < drift[4]:
                            v += drift[3] * min(1.0, max(0.0, (t - drift[1]) / drift[2]))
                    vals[i] = round(v, 2)
                elif stype == "HUM":
                    vals[i] = round(min(100.0, max(0.0, true_h[i] + bias + rng.gauss(0, 0.6))), 1)
                else:
                    vals[i] = occ[i]
            wins = []
            for _ in range(poisson(rng, outage_rate)):
                r = rng.random()
                L = rng.randint(1, 2) if r < 0.55 else (rng.randint(3, 12) if r < 0.90 else rng.randint(13, 60))
                s = rng.randint(1, n - L - 3)
                if any(s < b + 2 and s + L + 2 > a for a, b in wins):
                    continue
                if hidden_gap and s < hidden_gap[1] + 2 and s + L + 2 > hidden_gap[0]:
                    continue
                wins.append((s, s + L))
            for s, e in wins:
                for i in range(s, e):
                    vals[i] = None
                add_truth("SENSOR_OUTAGE", f"OUT-{sid}-{clock.compact(s)}", s, e - s,
                          "RAISE_SENSOR_GAP_ALARM" if e - s >= RULES["min_gap_readings"] else "RECORD_GAP_NO_ALARM",
                          "SENSOR_GAP" if e - s >= RULES["min_gap_readings"] else "",
                          {"missed_readings": e - s, "cause": "CONNECTIVITY_FAULT"}, sensor_id=sid, entity_type="SENSOR")
            if hidden_gap:
                for i in range(hidden_gap[0], hidden_gap[1]):
                    vals[i] = None
            w.readings[sid] = vals
    return doors


def _door_events(w, z, spec, door_sensor, rng, offset, injected):
    """Natural events (lognormal durations, working hours) plus injected long ones. Events of a zone never overlap:
    injected events are fixed, natural ones are dropped if they collide with an injected event and are pushed
    forward if they collide with a previous event."""
    cfg = w.cfg
    start, end = cfg.start_epoch, cfg.end_epoch
    items = [(o, d, "UNKNOWN", True) for o, d in injected]
    for day in range(cfg.scale.days):
        for _ in range(poisson(rng, spec.door_rate_per_day)):
            sec = rng.randint(6 * 3600, 22 * 3600 - 1)
            opened = start + day * 86400 + sec - offset
            dur = int(min(1800, max(8, rng.lognormvariate(math.log(spec.door_median_s), 0.5))))
            reason = weighted_choice(rng, DOOR_REASONS)
            if any(opened < o + d + 60 and opened + dur > o - 60 for o, d in injected):
                continue
            items.append((opened, dur, reason, False))
    items.sort(key=lambda r: r[0])
    rows, prev_close = [], start - 10
    for k, (opened, dur, reason, inj) in enumerate(items):
        if not inj:
            opened = max(opened, prev_close + 5)
            nxt = next((o for o, _d, _r, i2 in items[k + 1:] if i2), None)
            if nxt is not None and opened + dur + 5 > nxt and opened < nxt:
                continue
        closed = opened + dur
        if closed > end:
            continue
        rows.append({"door_event_id": f"DOOR-{z['zone_id']}-{compact(opened)}", "zone_id": z["zone_id"],
                     "sensor_id": door_sensor, "opened_at": iso(opened), "closed_at": iso(closed),
                     "duration_s": dur, "open_reason": reason, "exceeded_limit": dur > spec.door_open_limit_s,
                     "_open": opened, "_close": closed})
        prev_close = closed
    return rows
