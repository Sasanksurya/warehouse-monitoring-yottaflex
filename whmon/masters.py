"""Stage 1: master data - warehouses, zones, sensors, sensor placements, storage requirements.
Also injects the labelled edge case SENSOR_MULTI_ZONE_NO_RATIONALE (and valid shared mappings)."""
from __future__ import annotations

import math

from .config import (REQUIREMENTS, ZONE_SPECS, ZONE_TYPE_ORDER, RATES, PERIOD_START_EPOCH)
from .util import World, rng_for, wh_id, zone_id, sensor_id, iso, iso_date, weighted_choice

CITIES = ["Hyderabad", "Bengaluru", "Chennai", "Pune", "Mumbai", "Delhi NCR", "Ahmedabad", "Kolkata", "Nagpur", "Kochi"]
SENSOR_KINDS = [("TEMP", 1, "C", "TH-200"), ("TEMP", 2, "C", "TH-200"), ("HUM", 1, "PCT_RH", "HX-50"),
                ("OCC", 1, "PERSONS", "OC-10"), ("DOOR", 1, "EVENT", "DR-7")]


def zone_types_for_warehouse(rng, n_zones: int) -> list:
    """Every warehouse gets at least one zone of each type when it has >= 5 zones."""
    types = list(ZONE_TYPE_ORDER[:min(5, n_zones)])
    pairs = [(t, ZONE_SPECS[t].type_weight) for t in ZONE_TYPE_ORDER]
    while len(types) < n_zones:
        types.append(weighted_choice(rng, pairs))
    rng.shuffle(types)
    return types


def build_masters(w: World) -> None:
    cfg = w.cfg
    rng = rng_for(cfg, "masters")
    sc = cfg.scale
    warehouses, zones, sensors, sza = [], [], [], []

    for k in range(1, sc.warehouses + 1):
        wid = wh_id(k)
        commissioned = PERIOD_START_EPOCH - rng.randint(400, 3000) * 86400
        warehouses.append({
            "warehouse_id": wid, "name": f"{CITIES[(k - 1) % len(CITIES)]} Distribution Centre",
            "city": CITIES[(k - 1) % len(CITIES)], "country": "IN", "utc_offset_minutes": 330,
            "floor_area_sqm": rng.randint(8000, 40000), "status": "ACTIVE", "commissioned_date": iso_date(commissioned),
        })
        for j, ztype in enumerate(zone_types_for_warehouse(rng, sc.zones_per_warehouse), start=1):
            spec = ZONE_SPECS[ztype]
            zid = zone_id(wid, j)
            zones.append({
                "zone_id": zid, "warehouse_id": wid, "zone_name": f"{ztype.title()} Bay {j:02d}", "zone_type": ztype,
                "temp_min_c": spec.temp_min_c, "temp_max_c": spec.temp_max_c, "setpoint_c": spec.setpoint_c,
                "humidity_max_pct": spec.humidity_max_pct, "max_occupancy": spec.max_occupancy,
                "door_open_limit_s": spec.door_open_limit_s, "capacity_lots": spec.capacity_lots,
                "status": "ACTIVE", "effective_from": iso_date(commissioned), "effective_to": None,
            })
            for stype, n, unit, model in SENSOR_KINDS:
                sid = sensor_id(zid, stype, n)
                install = PERIOD_START_EPOCH - rng.randint(20, 160) * 86400
                sensors.append({
                    "sensor_id": sid, "home_zone_id": zid, "sensor_type": stype, "unit": unit, "model": model,
                    "install_date": iso_date(install), "status": "ACTIVE",
                    "reading_interval_s": None if stype == "DOOR" else 900,
                })
                sza.append({"sensor_id": sid, "zone_id": zid, "effective_from": iso_date(install),
                            "effective_to": None, "rationale": "PRIMARY_PLACEMENT"})

    # ---- second placements: valid shared coverage, and the labelled edge case without rationale
    rng2 = rng_for(cfg, "multizone")
    shareable = sorted(s["sensor_id"] for s in sensors if s["sensor_type"] in ("HUM", "OCC"))
    zone_ids_by_wh = {}
    for z in zones:
        zone_ids_by_wh.setdefault(z["warehouse_id"], []).append(z["zone_id"])
    n_ok = max(1, round(RATES["multi_zone_with_rationale_fraction"] * len(sensors)))
    n_bad = max(1, round(RATES["multi_zone_no_rationale_fraction"] * len(sensors)))
    picks = rng2.sample(shareable, min(len(shareable), n_ok + n_bad))
    home = {s["sensor_id"]: s["home_zone_id"] for s in sensors}
    for idx, sid in enumerate(picks):
        wid = "-".join(home[sid].split("-")[1:3])  # ZONE-WH-001-004 -> WH-001
        others = [z for z in zone_ids_by_wh[wid] if z != home[sid]]
        if not others:
            continue
        other = rng2.choice(others)
        bad = idx >= n_ok
        sza.append({"sensor_id": sid, "zone_id": other, "effective_from": iso_date(PERIOD_START_EPOCH),
                    "effective_to": None, "rationale": None if bad else "SHARED_AIRSPACE_COVERAGE"})
        if bad:
            w.add_truth("SENSOR_MULTI_ZONE_NO_RATIONALE", "SENSOR", sid, zone_id=home[sid], sensor_id=sid,
                        window_start=iso(PERIOD_START_EPOCH), expected_decision="REQUIRE_RATIONALE_OR_REMOVE_MAPPING",
                        details={"home_zone": home[sid], "second_zone": other})

    for i, r in enumerate(sza, start=1):
        r["assignment_id"] = f"SZA-{i:06d}"

    reqs = []
    for cat, tmin, tmax, hmax, tol, _wt, _dw, _q in REQUIREMENTS:
        reqs.append({"requirement_id": f"REQ-{cat}-01", "product_category": cat, "temp_min_c": tmin, "temp_max_c": tmax,
                     "humidity_max_pct": hmax, "max_excursion_min": tol, "version": 1,
                     "effective_from": "2026-01-01", "effective_to": None})

    w.tables.update(warehouse=warehouses, zone=zones, sensor=sensors, sensor_zone_assignment=sza, storage_requirement=reqs)


def zone_compatible(zone: dict, req: dict) -> bool:
    """Documented compatibility rule: zone design band inside the requirement band, humidity ceiling not looser."""
    if zone["temp_min_c"] < req["temp_min_c"] or zone["temp_max_c"] > req["temp_max_c"]:
        return False
    if req["humidity_max_pct"] is not None and zone["humidity_max_pct"] > req["humidity_max_pct"]:
        return False
    return True
