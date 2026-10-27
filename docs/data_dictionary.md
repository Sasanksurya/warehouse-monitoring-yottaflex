# Data dictionary

Generated from `whmon/schema.py` (do not edit by hand). Timestamps are UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`).
`DERIVED` fields are computed from source records, never generated independently.

## warehouse

A physical warehouse site (master data).

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| warehouse_id | STRING | yes | regex `^WH-\d{3}$` |  | PK | Immutable, zero-padded counter |
| name | STRING | yes |  |  |  |  |
| city | STRING | yes |  |  |  |  |
| country | STRING | yes |  |  |  |  |
| utc_offset_minutes | INTEGER | yes |  | minutes |  | Local offset used for shift patterns; timestamps stay UTC |
| floor_area_sqm | INTEGER | yes |  | m2 |  | > 0 |
| status | STRING | yes | ACTIVE, INACTIVE |  |  |  |
| commissioned_date | DATE | yes |  |  |  |  |

Relationships / cardinality: warehouse 1:N zone

## zone

Climate/occupancy-controlled area inside a warehouse (master data). Band = alert thresholds.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| zone_id | STRING | yes | regex `^ZONE-WH-\d{3}-\d{3}$` |  | PK | ZONE-<warehouse-id>-NNN |
| warehouse_id | STRING | yes |  |  | FK -> warehouse.warehouse_id | Must match the warehouse embedded in zone_id |
| zone_name | STRING | yes |  |  |  |  |
| zone_type | STRING | yes | FROZEN, COLD, COOL, AMBIENT, HOT |  |  |  |
| temp_min_c | FLOAT | yes |  | C |  | < temp_max_c; lower alert threshold |
| temp_max_c | FLOAT | yes |  | C |  | upper alert threshold |
| setpoint_c | FLOAT | yes |  | C |  | Within [temp_min_c, temp_max_c] |
| humidity_max_pct | FLOAT | yes |  | %RH |  | 0-100; alert threshold |
| max_occupancy | INTEGER | yes |  | persons |  | >= 1; alert threshold |
| door_open_limit_s | INTEGER | yes |  | seconds |  | > 0; alert threshold |
| capacity_lots | INTEGER | yes |  | lots |  | > 0, informational |
| status | STRING | yes | ACTIVE, INACTIVE |  |  |  |
| effective_from | DATE | yes |  |  |  |  |
| effective_to | DATE | no |  |  |  | >= effective_from when present |

Relationships / cardinality: zone 1:N sensor (home zone); zone N:M sensor via sensor_zone_assignment; zone N:M inventory_lot via lot_zone_assignment

## sensor

Physical sensor (master data). One TEMP x2, HUM, OCC, DOOR per zone.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| sensor_id | STRING | yes | regex `^SNS-ZONE-WH-\d{3}-\d{3}-(TEMP, HUM, OCC, DOOR)-\d{2}$` |  | PK | SNS-<zone-id>-<TYPE>-NN; embeds home zone and type |
| home_zone_id | STRING | yes |  |  | FK -> zone.zone_id | Equals the zone embedded in sensor_id |
| sensor_type | STRING | yes | TEMP, HUM, OCC, DOOR |  |  |  |
| unit | STRING | yes | C, PCT_RH, PERSONS, EVENT |  |  | TEMP->C, HUM->PCT_RH, OCC->PERSONS, DOOR->EVENT |
| model | STRING | yes |  |  |  |  |
| install_date | DATE | yes |  |  |  |  |
| status | STRING | yes | ACTIVE, FAULTY, DECOMMISSIONED |  |  |  |
| reading_interval_s | INTEGER | no |  | seconds |  | Required for TEMP/HUM/OCC, empty for DOOR |

Relationships / cardinality: sensor N:M zone via sensor_zone_assignment

## sensor_zone_assignment

Bridge: effective-dated placement of a sensor in a zone (N:M). A second active zone requires a rationale.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| assignment_id | STRING | yes | regex `^SZA-\d{6}$` |  | PK |  |
| sensor_id | STRING | yes |  |  | FK -> sensor.sensor_id |  |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| effective_from | DATE | yes |  |  |  |  |
| effective_to | DATE | no |  |  |  | >= effective_from; empty = still active |
| rationale | STRING | no | PRIMARY_PLACEMENT, SHARED_AIRSPACE_COVERAGE |  |  | Mandatory for every assignment except it may be empty only by defect (edge case SENSOR_MULTI_ZONE_NO_RATIONALE) |

Relationships / cardinality: sensor 1:N assignment N:1 zone

## storage_requirement

Per product-category storage requirement (versioned, effective-dated).

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| requirement_id | STRING | yes | regex `^REQ-[A-Z_]+-\d{2}$` |  | PK |  |
| product_category | STRING | yes | FROZEN_FOOD, DAIRY, PHARMA_COLD, PRODUCE, ELECTRONICS, DRY_GOODS, CURING_MATERIALS |  |  |  |
| temp_min_c | FLOAT | yes |  | C |  |  |
| temp_max_c | FLOAT | yes |  | C |  | > temp_min_c |
| humidity_max_pct | FLOAT | no |  | %RH |  | Empty = humidity not controlled |
| max_excursion_min | INTEGER | yes |  | minutes |  | Tolerated exposure before impact is MAJOR |
| version | INTEGER | yes |  |  |  | >= 1 |
| effective_from | DATE | yes |  |  |  |  |
| effective_to | DATE | no |  |  |  |  |

Relationships / cardinality: requirement 1:N inventory_lot

## inventory_lot

A received lot of product. current_state is derived from lot_state_history.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| lot_id | STRING | yes | regex `^LOT-2026-\d{6}$` |  | PK |  |
| product_code | STRING | yes |  |  |  |  |
| product_category | STRING | yes | FROZEN_FOOD, DAIRY, PHARMA_COLD, PRODUCE, ELECTRONICS, DRY_GOODS, CURING_MATERIALS |  |  |  |
| requirement_id | STRING | yes |  |  | FK -> storage_requirement.requirement_id | Category must equal the requirement's category |
| quantity_units | INTEGER | yes |  | units |  | > 0 |
| received_at | TIMESTAMP | yes |  |  |  |  |
| current_state | STRING | yes | RECEIVED, STORED, QUARANTINED, DISPOSED, SHIPPED |  |  | DERIVED: to_state of the latest lot_state_history row |

Relationships / cardinality: lot N:M zone via lot_zone_assignment; lot 1:N lot_state_history; lot N:M alarm via alarm_lot_impact

## lot_zone_assignment

Bridge: where a lot was stored and for how long (N:M over time). Dwell = stored_to - stored_from.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| assignment_id | STRING | yes | regex `^LZA-\d{6}$` |  | PK |  |
| lot_id | STRING | yes |  |  | FK -> inventory_lot.lot_id |  |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| stored_from | TIMESTAMP | yes |  |  |  | >= lot.received_at |
| stored_to | TIMESTAMP | no |  |  |  | > stored_from; empty = still stored at data cutoff |
| dwell_minutes | INTEGER | no |  | minutes |  | DERIVED: (stored_to - stored_from)/60; empty if open |
| assignment_reason | STRING | yes | PUTAWAY, TRANSFER |  |  |  |

Relationships / cardinality: Assignments of one lot never overlap in time

## sensor_reading

Telemetry. One row per sensor per interval; missing intervals are gaps (see sensor_gap).

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| reading_id | STRING | yes | regex `^RDG-SNS-ZONE-WH-\d{3}-\d{3}-(TEMP, HUM, OCC)-\d{2}-\d{8}T\d{6}Z$` |  | PK | RDG-<sensor-id>-<timestamp>; must equal sensor_id + measured_at |
| sensor_id | STRING | yes |  |  | FK -> sensor.sensor_id |  |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id | A zone with an active assignment for the sensor at measured_at |
| measured_at | TIMESTAMP | yes |  |  |  | UTC, aligned to the 15-minute grid; unique per sensor |
| value | FLOAT | yes |  | per sensor unit |  | TEMP -60..80, HUM 0..100, OCC >= 0 integer |
| unit | STRING | yes | C, PCT_RH, PERSONS |  |  | Equals sensor.unit |

Unique together: `sensor_id, measured_at`

Relationships / cardinality: sensor 1:N reading

## door_event

Door open/close event from a DOOR sensor.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| door_event_id | STRING | yes | regex `^DOOR-ZONE-WH-\d{3}-\d{3}-\d{8}T\d{6}Z$` |  | PK | DOOR-<zone-id>-<opened-timestamp> |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| sensor_id | STRING | yes |  |  | FK -> sensor.sensor_id | A DOOR sensor homed in zone_id |
| opened_at | TIMESTAMP | yes |  |  |  |  |
| closed_at | TIMESTAMP | yes |  |  |  | > opened_at |
| duration_s | INTEGER | yes |  | seconds |  | DERIVED: closed_at - opened_at |
| open_reason | STRING | yes | LOADING, PICKING, INSPECTION, CLEANING, UNKNOWN |  |  |  |
| exceeded_limit | BOOLEAN | yes |  |  |  | DERIVED: duration_s > zone.door_open_limit_s |

Relationships / cardinality: zone 1:N door_event; Events of one zone never overlap

## sensor_gap

Explicit record of missing readings, detected by the monitoring engine from the telemetry itself.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| gap_id | STRING | yes | regex `^GAP-SNS-ZONE-WH-\d{3}-\d{3}-(TEMP, HUM, OCC)-\d{2}-\d{8}T\d{6}Z$` |  | PK |  |
| sensor_id | STRING | yes |  |  | FK -> sensor.sensor_id |  |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| gap_start | TIMESTAMP | yes |  |  |  | First missing grid timestamp |
| gap_end | TIMESTAMP | yes |  |  |  | Timestamp of the next received reading (exclusive) |
| missed_readings | INTEGER | yes |  |  |  | DERIVED: (gap_end - gap_start)/interval |
| alarm_raised | BOOLEAN | yes |  |  |  | DERIVED: missed_readings >= rules.min_gap_readings |

Relationships / cardinality: sensor 1:N gap

## alarm

Alert raised by the rule engine; status mirrors the latest alarm_state_history row.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| alarm_id | STRING | yes | regex `^ALM-2026-\d{6}$` |  | PK | Numbered in opened_at order |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| sensor_id | STRING | yes |  |  | FK -> sensor.sensor_id | Triggering sensor; homed in zone_id |
| alarm_type | STRING | yes | TEMP_HIGH, TEMP_LOW, HUMIDITY_HIGH, DOOR_OPEN_TOO_LONG, OCCUPANCY_LIMIT, SENSOR_GAP, SENSOR_DRIFT |  |  |  |
| severity | STRING | yes | WARNING, CRITICAL |  |  |  |
| breach_start | TIMESTAMP | yes |  |  |  |  |
| breach_end | TIMESTAMP | yes |  |  |  | > breach_start (exclusive end of the breach window) |
| opened_at | TIMESTAMP | yes |  |  |  | >= breach_start |
| closed_at | TIMESTAMP | no |  |  |  | >= opened_at; empty unless status = CLOSED |
| status | STRING | yes | OPEN, ACKNOWLEDGED, ESCALATED, UNDER_INSPECTION, REMEDIATED, CLOSED |  |  | DERIVED: to_status of latest alarm_state_history row |
| peak_value | FLOAT | yes |  | threshold_unit |  | Worst observed value (drift: max |daily mean diff|; gap: missed readings) |
| threshold_value | FLOAT | yes |  | threshold_unit |  | Must equal the zone limit (or rule parameter) for alarm_type |
| threshold_unit | STRING | yes | C, PCT_RH, SECONDS, PERSONS, READINGS |  |  |  |
| duration_minutes | INTEGER | yes |  | minutes |  | DERIVED: (breach_end - breach_start)/60 |

Relationships / cardinality: zone 1:N alarm; alarm N:M lot via alarm_lot_impact; alarm 1:N inspection; alarm 1:N remediation

## alarm_state_history

Append-only log of alarm lifecycle transitions.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| event_id | STRING | yes | regex `^AEV-\d{6}$` |  | PK |  |
| alarm_id | STRING | yes |  |  | FK -> alarm.alarm_id |  |
| event_type | STRING | yes | OPENED, ACKNOWLEDGED, ESCALATED, INSPECTION_STARTED, REMEDIATION_COMPLETED, CLOSED |  |  |  |
| from_status | STRING | no | OPEN, ACKNOWLEDGED, ESCALATED, UNDER_INSPECTION, REMEDIATED, CLOSED |  |  | Empty only for the first event |
| to_status | STRING | yes | OPEN, ACKNOWLEDGED, ESCALATED, UNDER_INSPECTION, REMEDIATED, CLOSED |  |  |  |
| event_ts | TIMESTAMP | yes |  |  |  | Non-decreasing per alarm |
| actor_role | STRING | yes | PLANT_OPERATOR, MAINTENANCE_ENGINEER, QUALITY_ENGINEER, PRODUCTION_PLANNER, OT_IT_ADMIN, SYSTEM |  |  |  |
| reference_id | STRING | no |  |  |  | Inspection/remediation id when relevant |

Relationships / cardinality: alarm 1:N state event

## inspection

Physical inspection ordered for an alarm.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| inspection_id | STRING | yes | regex `^INS-2026-\d{6}$` |  | PK |  |
| alarm_id | STRING | yes |  |  | FK -> alarm.alarm_id |  |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| inspector_role | STRING | yes | MAINTENANCE_ENGINEER, QUALITY_ENGINEER, OT_IT_ADMIN |  |  |  |
| scheduled_at | TIMESTAMP | yes |  |  |  | >= alarm.opened_at |
| started_at | TIMESTAMP | no |  |  |  | >= scheduled_at |
| completed_at | TIMESTAMP | no |  |  |  | >= started_at |
| status | STRING | yes | SCHEDULED, IN_PROGRESS, COMPLETED |  |  | COMPLETED requires completed_at and outcome |
| outcome | STRING | no | EQUIPMENT_FAULT, DOOR_PROCEDURE, SENSOR_FAULT, CONNECTIVITY_FAULT, NO_FAULT_FOUND |  |  |  |

Relationships / cardinality: alarm 1:N inspection; inspection 1:N remediation

## remediation

Corrective action. Lot actions reference the lot and, through alarm_lot_impact, the inventory impact.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| remediation_id | STRING | yes | regex `^REM-2026-\d{6}$` |  | PK |  |
| alarm_id | STRING | yes |  |  | FK -> alarm.alarm_id |  |
| inspection_id | STRING | no |  |  | FK -> inspection.inspection_id |  |
| zone_id | STRING | yes |  |  | FK -> zone.zone_id |  |
| sensor_id | STRING | no |  |  | FK -> sensor.sensor_id | Required for sensor actions |
| lot_id | STRING | no |  |  | FK -> inventory_lot.lot_id | Required for lot actions; must have an alarm_lot_impact row for the alarm |
| action_type | STRING | yes | REPAIR_EQUIPMENT, DOOR_SEAL_REPAIR, RECALIBRATE_SENSOR, RESTORE_CONNECTIVITY, QUARANTINE_LOT, DISPOSE_LOT, RELEASE_LOT, NOTIFY_CUSTOMER |  |  |  |
| owner_role | STRING | yes | PLANT_OPERATOR, MAINTENANCE_ENGINEER, QUALITY_ENGINEER, PRODUCTION_PLANNER, OT_IT_ADMIN, SYSTEM |  |  |  |
| performed_at | TIMESTAMP | yes |  |  |  | >= inspection.completed_at |
| status | STRING | yes | PLANNED, COMPLETED |  |  |  |
| units_affected | INTEGER | no |  | units |  | DERIVED: lot.quantity_units for lot actions |

Relationships / cardinality: inspection 1:N remediation

## alarm_lot_impact

Bridge (N:M): lots affected by an alarm, identified from time + zone overlap of the breach window with the lot's stay.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| impact_id | STRING | yes | regex `^IMP-\d{6}$` |  | PK |  |
| alarm_id | STRING | yes |  |  | FK -> alarm.alarm_id |  |
| lot_id | STRING | yes |  |  | FK -> inventory_lot.lot_id |  |
| assignment_id | STRING | yes |  |  | FK -> lot_zone_assignment.assignment_id | Assignment in the alarm's zone overlapping the breach window |
| overlap_start | TIMESTAMP | yes |  |  |  |  |
| overlap_end | TIMESTAMP | yes |  |  |  | > overlap_start |
| overlap_minutes | INTEGER | yes |  | minutes |  | DERIVED: intersection of breach window and assignment |
| impact_level | STRING | yes | NONE, MINOR, MAJOR, UNVERIFIED |  |  | NONE: peak inside lot requirement; MINOR/MAJOR: outside requirement for < / >= max_excursion_min; UNVERIFIED: sensor gap/drift |
| disposition | STRING | yes | NO_ACTION, HOLD_PLACED, ALREADY_HELD, SHIPPED_BEFORE_ACTION |  |  |  |
| remediation_id | STRING | no |  |  | FK -> remediation.remediation_id |  |

Unique together: `alarm_id, lot_id`

Relationships / cardinality: alarm N:M lot

## lot_state_history

Append-only log of lot lifecycle transitions.

| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |
|---|---|---|---|---|---|---|
| event_id | STRING | yes | regex `^LSE-\d{6}$` |  | PK |  |
| lot_id | STRING | yes |  |  | FK -> inventory_lot.lot_id |  |
| from_state | STRING | no | RECEIVED, STORED, QUARANTINED, DISPOSED, SHIPPED |  |  |  |
| to_state | STRING | yes | RECEIVED, STORED, QUARANTINED, DISPOSED, SHIPPED |  |  |  |
| event_ts | TIMESTAMP | yes |  |  |  | Non-decreasing per lot |
| reason | STRING | yes | RECEIPT, PUTAWAY, ALARM_HOLD, DISPOSAL, RELEASED_FROM_HOLD, SHIPMENT |  |  |  |
| remediation_id | STRING | no |  |  | FK -> remediation.remediation_id |  |

Relationships / cardinality: lot 1:N state event
