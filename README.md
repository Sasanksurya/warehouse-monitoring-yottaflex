# Warehouse environmental monitoring: synthetic data, rule engine, validation, evaluation

YottaFlex AI Round 2 — *72 Hours Code Challenge* — **Monitor temperature, humidity, occupancy and door events by
warehouse zone and alert on risk conditions.**

A deterministic, stdlib-only Python 3.11+ package (`whmon`) that generates a realistic synthetic dataset for 10 core
entities (16 tables), runs a monitoring rule engine and a response workflow over it, injects four labelled edge cases,
validates integrity, scores itself against a separate ground-truth file, and proves reproducibility.

## Quick start

```bash
python -m whmon generate --scale starter --out data/starter     # ~1 s, 14 days, 2 warehouses, 400 lots
python -m whmon generate --scale full    --out data/full        # ~20 s incl. validation: 10 wh, 100 zones, 500 sensors, ~1.03 M readings, 10 k lots
python -m whmon validate --data data/full                       # re-run integrity checks on any exported folder
python -m whmon evaluate --data data/full                       # score detectors/alarms against ground_truth/
python -m whmon reproduce --scale full --check-other-seed       # regenerate twice, compare row counts + SHA-256
pip install pytest && python -m pytest                          # 51 fast tests ( -m slow adds the full-scale test )
```

Options: `--seed N` (default **20261022**), `--formats csv,json,sql,sqlite` (CSV is always written),
`--warehouses --zones-per-warehouse --days --lots` to override the scale. No third-party runtime dependencies,
no network, no credentials.

## What is produced (`--out`)

| Path | Content |
|---|---|
| `csv/*.csv` | 16 tables (canonical input to validate/evaluate) |
| `json/`, `sql/schema.sql`, `sql/seed.sql`, `warehouse.db` | optional JSON/JSONL, SQL DDL + inserts, SQLite with FKs |
| `ground_truth/ground_truth.{csv,json}` | labelled injected defects/conditions — **never read by the generator's detectors or written into input tables** |
| `docs/` | data dictionary (md + csv), `schema.sql`, `monitoring_rules.json`, `injection_rates.json`, `source_manifest.json` |
| `reports/` | `validation_summary.md/json`, `evaluation_report.md/json` |
| `manifest.json` | generator command, seed, scale, row counts, SHA-256 + size of every file |

`sample_data/starter/` is a committed starter dataset (CSV + ground truth + docs + reports + manifest).
Full-scale reports are in `docs/reports_full_scale/`. The data dictionary is [docs/data_dictionary.md](docs/data_dictionary.md).

## Entities

Warehouse → Zone → Sensor → SensorReading / DoorEvent; InventoryLot ↔ StorageRequirement, lot stays
(`lot_zone_assignment`); Alarm → AlarmStateHistory, Inspection, Remediation, `alarm_lot_impact`, `lot_state_history`;
supporting: `sensor_zone_assignment` (sensor↔zone mapping with rationale), `sensor_gap`.
Parents are always generated before children, so every FK resolves; IDs are deterministic.

## Pipeline

`masters` (warehouses, zones, sensors, requirements) → `lots` (stays, transfers) → `telemetry` (physics, doors,
injected conditions, drift, outages) → `detect` (rule engine; sees only telemetry/doors/thresholds) → `workflow`
(ack → inspect → remediate → close; lot holds; lot-impact) → ground-truth ids → `export`. Each stage draws from its own
seeded RNG stream (`random.Random(f"{seed}/stage/key")`), so adding data in one stage cannot shift another.

## Monitoring rules (full detail in `docs/monitoring_rules.json`)

TEMP_HIGH/LOW (≥2 consecutive out-of-band readings, limit-equal is not a breach), HUMIDITY_HIGH, DOOR_OPEN_TOO_LONG,
OCCUPANCY_LIMIT, SENSOR_GAP (≥3 missing readings), SENSOR_DRIFT (twin-sensor daily mean divergence >1 °C for ≥2 days).
Severity CRITICAL when ≥3 °C / 10 %RH beyond limit, ≥120 min, door ≥3× limit, or gap ≥12 readings.

## The four injected edge cases (labelled in `ground_truth/`)

| Label | What is injected | Full-scale count |
|---|---|---:|
| `INCOMPATIBLE_ZONE_ASSIGNMENT` | lot stored in a zone outside its storage requirement | 100 |
| `SENSOR_MULTI_ZONE_NO_RATIONALE` | sensor mapped to >1 zone with no rationale (valid mappings with rationale also exist) | 10 |
| `GAP_TREATED_AS_NORMAL` | zone-wide outage hides a real excursion; no gap row, no alarm | 8 |
| `ALARM_NOT_LINKED_TO_LOTS` | alarm with lots present in the zone but no `alarm_lot_impact` rows | 14 |

Other labelled conditions (used to measure alarm recall, time-to-detect and false alarms): temperature high/low
excursions, humidity, occupancy, door left open, sensor drift, sensor outage, **boundary persistence** (exactly 2
readings — must alarm) and **transient spike** (1 reading — must not alarm).
Derived values (durations, dwell, overlap, units affected, current states, statuses) are computed from source records and re-checked by the validator.

## Results (seed 20261022, full scale)

* Rows: 1,034,768 readings, 10,000 lots, 39,384 door events, 485 alarms, 286 inspections, 1,434 remediations,
  7,665 alarm-lot impacts, 525 ground-truth rows.
* Validation: **173 passed, 0 failed** (18.5 M assertions: PK, FK, enums, patterns, date order, arithmetic, lifecycle, duplicates, semantic rules). SQLite FK check: 0 violations.
* Detection: edge-case detectors precision = recall = 1.0 (**by construction** — exact rule checks; see limitations);
  alarm recall 1.0 for every injected condition; 0 transient spikes alarmed; false-alarm rate 5.8 % (28 drift-induced).
* Reproducibility: two regenerations → identical row counts and SHA-256 for all 24 files; also identical across
  processes with different `PYTHONHASHSEED`; a different seed produces different data ([docs/reproducibility_report.json](docs/reproducibility_report.json)).

## Layout

```
whmon/        config, schema, util, masters, lots, telemetry, detect, workflow, pipeline, export, reader, validate, evaluate, cli
tests/        51 tests: schema, generation, rule-engine boundaries, validator mutation tests, evaluation, no-leak, reproducibility
docs/         data dictionary, assumptions & limitations, AI usage, prompt history, reproducibility + full-scale reports
sample_data/  committed starter dataset
```

## Honesty notes

* Built by an AI agent from the task documents — see [docs/AI_USAGE.md](docs/AI_USAGE.md) and [docs/prompt_history/](docs/prompt_history/README.md).
* Assumptions and limitations: [docs/ASSUMPTIONS_AND_LIMITATIONS.md](docs/ASSUMPTIONS_AND_LIMITATIONS.md).
* All data is synthetic; no personal data, secrets or third-party datasets are included.
