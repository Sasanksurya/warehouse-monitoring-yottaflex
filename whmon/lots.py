"""Stage 2: inventory lots, their stay in zones (bridge table), and the labelled edge case
INCOMPATIBLE_ZONE_ASSIGNMENT. Lot state/ids are finalised later by the workflow stage."""
from __future__ import annotations

import math

from .config import REQUIREMENTS, RATES, LOT_YEAR, LOT_LOOKBACK_DAYS
from .masters import zone_compatible
from .util import World, rng_for, iso, lot_id, weighted_choice


def build_lots(w: World) -> None:
    cfg = w.cfg
    rng = rng_for(cfg, "lots")
    zones = w.tables["zone"]
    reqs = {r["product_category"]: r for r in w.tables["storage_requirement"]}
    spec_by_cat = {c: (wt, dw, q) for c, _a, _b, _c, _d, wt, dw, q in REQUIREMENTS}
    compat = {c: [z for z in zones if zone_compatible(z, reqs[c])] for c in reqs}
    cutoff = cfg.end_epoch
    lo = cfg.start_epoch - LOT_LOOKBACK_DAYS * 86400
    hi = cutoff - 7 * 3600
    cat_pairs = [(c, spec_by_cat[c][0]) for c in reqs]

    plans = []
    for _ in range(cfg.scale.lots):
        cat = weighted_choice(rng, cat_pairs)
        candidates = compat[cat]
        if not candidates:
            continue
        zone = rng.choice(candidates)
        received = rng.randint(lo, hi)
        stored_from = received + rng.randint(30 * 60, 6 * 3600)
        dwell_lo, dwell_hi = spec_by_cat[cat][1]
        dwell_s = int(rng.triangular(dwell_lo, dwell_hi, dwell_lo + (dwell_hi - dwell_lo) * 0.35) * 86400)
        qlo, qhi = spec_by_cat[cat][2]
        qty = int(min(qhi, max(qlo, math.exp(rng.gauss(math.log((qlo * qhi) ** 0.5), 0.5)))))
        plans.append((received, cat, zone, stored_from, dwell_s, qty, rng.randint(1, 40)))
    plans.sort(key=lambda p: (p[0], p[1], p[2]["zone_id"]))

    lots, assigns = [], []
    for i, (received, cat, zone, stored_from, dwell_s, qty, sku) in enumerate(plans, start=1):
        lid = lot_id(LOT_YEAR, i)
        lots.append({"lot_id": lid, "product_code": f"SKU-{cat[:4]}-{sku:03d}", "product_category": cat,
                     "requirement_id": reqs[cat]["requirement_id"], "quantity_units": qty,
                     "received_at": iso(received), "current_state": None})
        planned_end = stored_from + dwell_s
        segments = [(zone, stored_from, planned_end, "PUTAWAY")]
        if dwell_s >= 8 * 86400 and rng.random() < RATES["transfer_fraction"]:
            same_wh = [z for z in compat[cat] if z["warehouse_id"] == zone["warehouse_id"] and z["zone_id"] != zone["zone_id"]]
            t = stored_from + int(dwell_s * rng.uniform(0.4, 0.6))
            if same_wh and t < cutoff - 3600:      # no planned transfer may lie in the future of the data cutoff
                segments = [(zone, stored_from, t, "PUTAWAY"), (rng.choice(same_wh), t, planned_end, "TRANSFER")]
        for z, a, b, reason in segments:
            assigns.append({"lot_id": lid, "zone_id": z["zone_id"], "stored_from": a,
                            "stored_to": b if b <= cutoff else None, "assignment_reason": reason, "_planned_to": b})

    # ---- edge case: lots put into a zone whose band is incompatible with their requirement
    rng2 = rng_for(cfg, "incompatible")
    single = {}
    for a in assigns:
        single.setdefault(a["lot_id"], []).append(a)
    cands = sorted(l for l, v in single.items() if len(v) == 1)
    n_bad = max(1, round(RATES["incompatible_lot_fraction"] * len(lots))) if cands else 0
    lot_by_id = {l["lot_id"]: l for l in lots}
    for lid in rng2.sample(cands, min(n_bad, len(cands))):
        a = single[lid][0]
        cat = lot_by_id[lid]["product_category"]
        bad_zones = [z for z in zones if not zone_compatible(z, reqs[cat])]
        if not bad_zones:
            continue
        z = rng2.choice(bad_zones)
        original = a["zone_id"]
        a["zone_id"] = z["zone_id"]
        req = reqs[cat]
        w.add_truth("INCOMPATIBLE_ZONE_ASSIGNMENT", "LOT", lid, zone_id=z["zone_id"],
                    window_start=iso(a["stored_from"]), window_end=iso(a["stored_to"]) if a["stored_to"] else "",
                    expected_decision="REJECT_PUTAWAY_OR_RELOCATE",
                    details={"zone_type": z["zone_type"], "zone_band_c": [z["temp_min_c"], z["temp_max_c"]],
                             "requirement_id": req["requirement_id"], "requirement_band_c": [req["temp_min_c"], req["temp_max_c"]],
                             "valid_zone_before_injection": original})

    for i, a in enumerate(sorted(assigns, key=lambda a: (a["lot_id"], a["stored_from"])), start=1):
        a["assignment_id"] = f"LZA-{i:06d}"
    w.tables["inventory_lot"] = lots
    w.tables["lot_zone_assignment"] = sorted(assigns, key=lambda a: a["assignment_id"])  # epochs until finalize
