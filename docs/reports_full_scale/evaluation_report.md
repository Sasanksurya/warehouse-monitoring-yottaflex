# Evaluation report

Detectors in part A read only the input tables; `ground_truth/` is used only to score them.

## A. Injected edge cases: detector vs ground truth

| Edge case | Truth | Flagged | TP | FP | FN | Precision | Recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| INCOMPATIBLE_ZONE_ASSIGNMENT | 100 | 100 | 100 | 0 | 0 | 1.0 | 1.0 |
| SENSOR_MULTI_ZONE_NO_RATIONALE | 10 | 10 | 10 | 0 | 0 | 1.0 | 1.0 |
| ALARM_NOT_LINKED_TO_LOTS | 14 | 14 | 14 | 0 | 0 | 1.0 | 1.0 |
| GAP_TREATED_AS_NORMAL | 8 | 8 | 8 | 0 | 0 | 1.0 | 1.0 |

Undeclared missing reading intervals: 532. Alarms with partially missing lot links: 0 (455 of 8120 expected alarm-lot pairs absent).

## B. Alarm quality

Alarms: 485; false-alarm rate (unexplained + drift-induced + spike-induced): 0.0577

| Alarm category | Count |
|---|---:|
| drift_induced_false_alarm | 28 |
| matched_injected_condition | 297 |
| natural_door_overrun_by_rule | 155 |
| secondary_to_door_left_open | 5 |

| Injected condition | Expected | Detected | Recall | TTD median (min) | TTD p90 (min) |
|---|---:|---:|---:|---:|---:|
| DOOR_LEFT_OPEN | 44 | 44 | 1.0 | 7.0 | 10.0 |
| HUMIDITY_EXCURSION | 25 | 25 | 1.0 | 30.0 | 45.0 |
| OCCUPANCY_EXCEEDED | 26 | 26 | 1.0 | 0.0 | 0.0 |
| SENSOR_DRIFT | 9 | 9 | 1.0 | 6210.0 | 7122.0 |
| SENSOR_OUTAGE | 87 | 87 | 1.0 | 45.0 | 45.0 |
| TEMP_BOUNDARY_MIN_PERSISTENCE | 21 | 21 | 1.0 | 15.0 | 15.0 |
| TEMP_HIGH_EXCURSION | 60 | 60 | 1.0 | 30.0 | 30.0 |
| TEMP_LOW_EXCURSION | 24 | 24 | 1.0 | 30.0 | 40.5 |

Transient single-reading spikes that wrongly alarmed: 0. Drift culprit-sensor attribution accuracy: 1.0.

## C. Workflow KPIs

```json
{
 "alarm_status_counts": {
  "CLOSED": 485
 },
 "time_to_acknowledge_min": {
  "median": 13.68,
  "p90": 33.61
 },
 "time_to_close_h": {
  "median": 4.64,
  "p90": 8.47
 },
 "critical_alarms_inspected_share": 0.9438,
 "inspections": 286,
 "inspection_outcomes": {
  "CONNECTIVITY_FAULT": 56,
  "EQUIPMENT_FAULT": 103,
  "NO_FAULT_FOUND": 15,
  "DOOR_PROCEDURE": 85,
  "SENSOR_FAULT": 27
 },
 "remediation_actions": {
  "RESTORE_CONNECTIVITY": 56,
  "REPAIR_EQUIPMENT": 103,
  "QUARANTINE_LOT": 602,
  "DISPOSE_LOT": 384,
  "RELEASE_LOT": 167,
  "DOOR_SEAL_REPAIR": 85,
  "NOTIFY_CUSTOMER": 10,
  "RECALIBRATE_SENSOR": 27
 },
 "lots_with_alarm_impact": 4164,
 "impact_levels": {
  "UNVERIFIED": 3834,
  "NONE": 954,
  "MAJOR": 670,
  "MINOR": 2207
 },
 "impact_dispositions": {
  "NO_ACTION": 6995,
  "HOLD_PLACED": 602,
  "ALREADY_HELD": 58,
  "SHIPPED_BEFORE_ACTION": 10
 },
 "units_quarantined": 123490,
 "units_disposed": 73189,
 "lot_final_states": {
  "SHIPPED": 6656,
  "DISPOSED": 384,
  "STORED": 2909,
  "QUARANTINED": 51
 },
 "lot_actions_linked_to_impact_share": 1.0
}
```

## D. Distributions

```json
{
 "readings_total": 1034768,
 "readings_by_sensor_type": {
  "HUM": 258729,
  "OCC": 258770,
  "TEMP": 517269
 },
 "reading_completeness": 0.998,
 "per_zone_type_stats": {
  "AMBIENT/HUM": {
   "n": 93089,
   "mean": 45.42,
   "std": 2.42,
   "share_outside_threshold": 0.00043
  },
  "AMBIENT/OCC": {
   "n": 93151,
   "mean": 3.05,
   "std": 2.78,
   "share_outside_threshold": 0.00015
  },
  "AMBIENT/TEMP": {
   "n": 186196,
   "mean": 20.13,
   "std": 1.3,
   "share_outside_threshold": 0.00428
  },
  "COLD/HUM": {
   "n": 56957,
   "mean": 55.17,
   "std": 2.49,
   "share_outside_threshold": 0.00119
  },
  "COLD/OCC": {
   "n": 56959,
   "mean": 0.98,
   "std": 1.21,
   "share_outside_threshold": 0.0003
  },
  "COLD/TEMP": {
   "n": 113923,
   "mean": 5.12,
   "std": 0.68,
   "share_outside_threshold": 0.00506
  },
  "COOL/HUM": {
   "n": 38767,
   "mean": 70.21,
   "std": 2.33,
   "share_outside_threshold": 0.00018
  },
  "COOL/OCC": {
   "n": 38815,
   "mean": 0.98,
   "std": 1.2,
   "share_outside_threshold": 0.00018
  },
  "COOL/TEMP": {
   "n": 77597,
   "mean": 11.54,
   "std": 0.67,
   "share_outside_threshold": 0.00295
  },
  "FROZEN/HUM": {
   "n": 33684,
   "mean": 65.02,
   "std": 2.31,
   "share_outside_threshold": 6e-05
  },
  "FROZEN/OCC": {
   "n": 33681,
   "mean": 0.49,
   "std": 0.78,
   "share_outside_threshold": 0.00039
  },
  "FROZEN/TEMP": {
   "n": 67178,
   "mean": -19.95,
   "std": 0.81,
   "share_outside_threshold": 0.00426
  },
  "HOT/HUM": {
   "n": 36232,
   "mean": 30.17,
   "std": 2.42,
   "share_outside_threshold": 0.00077
  },
  "HOT/OCC": {
   "n": 36164,
   "mean": 0.74,
   "std": 1.0,
   "share_outside_threshold": 0.00022
  },
  "HOT/TEMP": {
   "n": 72375,
   "mean": 34.9,
   "std": 1.15,
   "share_outside_threshold": 0.00249
  }
 },
 "door_events": {
  "total": 39384,
  "per_zone_per_day_mean": 14.59,
  "duration_s_p50": 122.0,
  "duration_s_p95": 304.0,
  "share_over_limit": 0.0051
 },
 "lots": {
  "total": 10000,
  "by_category": {
   "FROZEN_FOOD": 1631,
   "DRY_GOODS": 2207,
   "PRODUCE": 1388,
   "ELECTRONICS": 1179,
   "DAIRY": 1811,
   "CURING_MATERIALS": 778,
   "PHARMA_COLD": 1006
  },
  "dwell_days_p50": 8.59,
  "dwell_days_p90": 22.24,
  "zone_types_used": {
   "FROZEN": 1676,
   "AMBIENT": 3577,
   "COOL": 1389,
   "COLD": 2874,
   "HOT": 810
  }
 },
 "sensor_gaps": {
  "declared": 146,
  "missed_readings_p50": 4.5,
  "missed_readings_p90": 37.5
 },
 "ground_truth_issue_counts": {
  "ALARM_NOT_LINKED_TO_LOTS": 14,
  "DOOR_LEFT_OPEN": 44,
  "GAP_TREATED_AS_NORMAL": 8,
  "HUMIDITY_EXCURSION": 25,
  "INCOMPATIBLE_ZONE_ASSIGNMENT": 100,
  "OCCUPANCY_EXCEEDED": 26,
  "SENSOR_DRIFT": 9,
  "SENSOR_MULTI_ZONE_NO_RATIONALE": 10,
  "SENSOR_OUTAGE": 146,
  "TEMP_BOUNDARY_MIN_PERSISTENCE": 21,
  "TEMP_HIGH_EXCURSION": 60,
  "TEMP_LOW_EXCURSION": 24,
  "TRANSIENT_SPIKE": 38
 }
}
```
