"""Exports: CSV (default), JSON/JSONL, SQL seed, SQLite, plus documentation artefacts and a manifest with checksums.
Ground truth is written to its own directory and never mixed into the input tables."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import sqlite3
import sys

from .config import RULES, RATES, REQUIREMENTS, ZONE_SPECS, INTERVAL_S
from .schema import TABLES, TABLE_BY_NAME, TABLE_ORDER, data_dictionary_markdown, data_dictionary_rows, ddl
from .util import World, reading_id

TRUTH_COLS = ["truth_id", "issue_type", "entity_type", "entity_id", "zone_id", "sensor_id", "window_start", "window_end",
              "expected_decision", "expected_alarm_types", "linked_entities", "details"]
READING_UNIT = {"TEMP": "C", "HUM": "PCT_RH", "OCC": "PERSONS"}


def iter_readings(w: World):
    sensors = {s["sensor_id"]: s for s in w.tables["sensor"]}
    for sid in sorted(w.readings):
        s = sensors[sid]
        unit = READING_UNIT[s["sensor_type"]]
        vals = w.readings[sid]
        for i, v in enumerate(vals):
            if v is not None:
                yield {"reading_id": reading_id(sid, w.clock.compact(i)), "sensor_id": sid, "zone_id": s["home_zone_id"],
                       "measured_at": w.clock.iso(i), "value": v, "unit": unit}


def iter_table(w: World, name: str):
    if name == "sensor_reading":
        yield from iter_readings(w)
    else:
        yield from w.tables[name]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _sql_lit(v):
    if v is None:
        return "NULL"
    if isinstance(v, bool):
        return "1" if v else "0"
    if isinstance(v, (int, float)):
        return repr(v)
    return "'" + str(v).replace("'", "''") + "'"


def export_csv(w, out):
    os.makedirs(f"{out}/csv", exist_ok=True)
    counts = {}
    for t in TABLES:
        with open(f"{out}/csv/{t.name}.csv", "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f, lineterminator="\n")
            wr.writerow(t.names)
            n = 0
            for row in iter_table(w, t.name):
                wr.writerow([_cell(row.get(c)) for c in t.names])
                n += 1
            counts[t.name] = n
    return counts


def export_json(w, out):
    os.makedirs(f"{out}/json", exist_ok=True)
    for t in TABLES:
        if t.name == "sensor_reading":
            with open(f"{out}/json/{t.name}.jsonl", "w", encoding="utf-8") as f:
                for row in iter_table(w, t.name):
                    f.write(json.dumps({c: row.get(c) for c in t.names}, separators=(",", ":")) + "\n")
        else:
            with open(f"{out}/json/{t.name}.json", "w", encoding="utf-8") as f:
                json.dump([{c: row.get(c) for c in t.names} for row in iter_table(w, t.name)], f, indent=1)


def export_sql(w, out, batch=500):
    os.makedirs(f"{out}/sql", exist_ok=True)
    with open(f"{out}/sql/schema.sql", "w", encoding="utf-8") as f:
        f.write(ddl())
    with open(f"{out}/sql/seed.sql", "w", encoding="utf-8") as f:
        f.write("PRAGMA foreign_keys = ON;\nBEGIN;\n")
        for t in TABLES:
            buf = []
            cols = ", ".join(t.names)
            for row in iter_table(w, t.name):
                buf.append("(" + ", ".join(_sql_lit(row.get(c)) for c in t.names) + ")")
                if len(buf) >= batch:
                    f.write(f"INSERT INTO {t.name} ({cols}) VALUES\n" + ",\n".join(buf) + ";\n")
                    buf = []
            if buf:
                f.write(f"INSERT INTO {t.name} ({cols}) VALUES\n" + ",\n".join(buf) + ";\n")
        f.write("COMMIT;\n")


def export_sqlite(w, out):
    path = f"{out}/warehouse.db"
    if os.path.exists(path):
        os.remove(path)
    con = sqlite3.connect(path)
    con.executescript(ddl())
    con.execute("PRAGMA foreign_keys = ON")
    for t in TABLES:
        ph = ", ".join("?" * len(t.names))
        rows = ([_cell_sql(r.get(c)) for c in t.names] for r in iter_table(w, t.name))
        con.executemany(f"INSERT INTO {t.name} ({', '.join(t.names)}) VALUES ({ph})", rows)
    con.commit()
    bad = con.execute("PRAGMA foreign_key_check").fetchall()
    con.close()
    return len(bad)


def _cell_sql(v):
    return int(v) if isinstance(v, bool) else v


def export_ground_truth(w, out):
    os.makedirs(f"{out}/ground_truth", exist_ok=True)
    with open(f"{out}/ground_truth/ground_truth.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.writer(f, lineterminator="\n")
        wr.writerow(TRUTH_COLS)
        for t in w.truth:
            wr.writerow([t.get(c, "") for c in TRUTH_COLS])
    with open(f"{out}/ground_truth/ground_truth.json", "w", encoding="utf-8") as f:
        json.dump([{**{c: t.get(c, "") for c in TRUTH_COLS}, "details": json.loads(t["details"])} for t in w.truth], f, indent=1)


def export_docs(w, out):
    os.makedirs(f"{out}/docs", exist_ok=True)
    with open(f"{out}/docs/data_dictionary.md", "w", encoding="utf-8") as f:
        f.write(data_dictionary_markdown())
    rows = list(data_dictionary_rows())
    with open(f"{out}/docs/data_dictionary.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        wr.writeheader()
        wr.writerows(rows)
    with open(f"{out}/docs/schema.sql", "w", encoding="utf-8") as f:
        f.write(ddl())
    with open(f"{out}/docs/monitoring_rules.json", "w", encoding="utf-8") as f:
        json.dump({"rules": RULES,
                   "zone_types": {k: {"temp_band_c": [v.temp_min_c, v.temp_max_c], "humidity_max_pct": v.humidity_max_pct,
                                      "max_occupancy": v.max_occupancy, "door_open_limit_s": v.door_open_limit_s}
                                  for k, v in ZONE_SPECS.items()},
                   "storage_requirements": [{"category": r[0], "temp_band_c": [r[1], r[2]], "humidity_max_pct": r[3],
                                             "max_excursion_min": r[4]} for r in REQUIREMENTS]}, f, indent=1)
    with open(f"{out}/docs/injection_rates.json", "w", encoding="utf-8") as f:
        json.dump(RATES, f, indent=1)
    with open(f"{out}/docs/source_manifest.json", "w", encoding="utf-8") as f:
        json.dump({"external_data_used": False,
                   "note": "All data is synthetic, generated from documented rules and a fixed seed. No third-party dataset, "
                           "scraped content or personal information is used; public reference ranges (e.g. cold-chain "
                           "2-8 C, frozen -25..-15 C) informed the zone and requirement bands as schema inspiration only.",
                   "sources": []}, f, indent=1)


def write_manifest(w, out, counts, command):
    files = {}
    for root, _d, names in os.walk(out):
        for n in sorted(names):
            if n == "manifest.json" or n.endswith(".db"):
                continue
            p = os.path.join(root, n)
            files[os.path.relpath(p, out)] = {"bytes": os.path.getsize(p), "sha256": _sha(p)}
    manifest = {
        "generator_command": command, "seed": w.cfg.seed, "scale": w.cfg.scale.__dict__ | {"zones": w.cfg.scale.zones,
                                                                                         "sensors": w.cfg.scale.sensors},
        "period_utc": [w.clock.iso(0), w.clock.iso(w.cfg.n_steps)], "reading_interval_s": INTERVAL_S,
        "row_counts": counts, "ground_truth_rows": len(w.truth),
        "python": platform.python_version(), "files": dict(sorted(files.items())),
    }
    with open(f"{out}/manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=1)
    return manifest


def export_all(w: World, out: str, formats=("csv",), command: str = ""):
    os.makedirs(out, exist_ok=True)
    counts = export_csv(w, out)  # CSV is always written: it is the canonical input for validation and evaluation
    if "json" in formats:
        export_json(w, out)
    if "sql" in formats:
        export_sql(w, out)
    fk_bad = None
    if "sqlite" in formats:
        fk_bad = export_sqlite(w, out)
    export_ground_truth(w, out)
    export_docs(w, out)
    manifest = write_manifest(w, out, counts, command)
    return manifest, fk_bad
