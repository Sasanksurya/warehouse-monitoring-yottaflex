# Assumptions and limitations

## Assumptions
1. **Everything is synthetic.** No external dataset, scraped content or personal data (see `source_manifest.json`
   in every export). Public reference ranges (cold chain 2–8 °C, frozen −25…−15 °C) only inspired the bands.
2. **Time.** All timestamps are UTC ISO-8601 (`...Z`). Monitoring window: 2026-09-01 for 27 days (full) / 14 days
   (starter). Lots may be received up to 20 days before the window. Nothing after the data cutoff is emitted
   (no future alarms, inspections or lot events).
3. **Cadence.** TEMP/HUM/OCC sensors report every 15 min (96/day). DOOR sensors emit events, not readings.
   400 reading sensors × 27 days × 96 ≈ 1.03 M readings at full scale.
4. **Zones.** 5 types: FROZEN, COLD, COOL, AMBIENT, HOT, each with design temperature band, humidity ceiling,
   max occupancy and door-open limit (`docs/monitoring_rules.json`). Each zone has 5 sensors: 2 TEMP, 1 HUM, 1 OCC, 1 DOOR.
5. **Compatibility.** A lot may sit in a zone when the zone's design band lies inside the product's storage band
   and the zone humidity ceiling ≤ the product's ceiling. One active storage-requirement version per category.
6. **Alarm rules.** A limit-equal value is not a breach; ≥2 consecutive breaching readings (30 min) open an alarm; a
   single-reading spike never alarms; breach runs separated by <2 clear readings merge into one alarm; missing data
   ends a run. Gap alarm after ≥3 missing readings. Drift = daily mean |TEMP-01 − TEMP-02| > 1.0 °C for ≥2 days.
7. **Affected lots.** A lot is linked to an alarm when it was in the alarm's zone for ≥60 s of the breach window.
   Impact: `NONE` (within the product's excursion tolerance), `MINOR`, `MAJOR`, or `UNVERIFIED` (the evidence sensor
   is itself suspect, or the alarm is a gap/drift where no breach is known).
8. **Workflow.** Every alarm is acknowledged, most CRITICAL ones inspected, then remediated and closed within
   the data window; open work at the cutoff is not simulated, so all emitted alarms end `CLOSED`.
9. **IDs.** Deterministic and derived from parents, e.g. `WH-001`, `ZONE-WH-001-001`, `SNS-<zone>-TEMP-01`,
   `RDG-<sensor>-<yyyymmddThhmmssZ>`, `LOT-2026-000001`. Alarm/inspection/remediation IDs are renumbered in time order.

## Limitations
* Physics is a simple model (setpoint + diurnal term + AR(1) deviation + door load); it is not a thermal simulation.
* One incident cause per alarm; real incidents compound.
* Sensor model has bias, noise, slow drift and outages only; no stuck-at or spike faults.
* The rule-based detectors in `evaluate.py` get perfect scores on the four injected edge cases by construction
  (exact checks on structured data). This validates the labels and detectors, not real-world performance.
* False-alarm rate (5.8 % at full scale) is reported honestly: 28 alarms are drift-induced, 155 alarms are door
  overruns that the rule engine raises but were not injected (they are real rule hits, categorised as
  `natural_door_overrun_by_rule`, not counted as false).
* 532 reading intervals are missing but undeclared (short gaps <3 readings); they are reported as INFO.
* Starter sample is committed; the ~134 MB full dataset is regenerated with one command (≈15 s) rather than stored.
* Single-threaded stdlib Python; full pipeline ≈ 20 s including validation.
