# Validation summary

**172 passed, 0 failed** of 173 checks (938,952 individual assertions).

| Category | Check | Status | Checked | Failed |
|---|---|---|---:|---:|
| arithmetic | alarm: closed_at set exactly when CLOSED (and equals the CLOSED event) | PASS | 17 | 0 |
| arithmetic | alarm: duration_minutes == (breach_end - breach_start)/60 | PASS | 17 | 0 |
| arithmetic | alarm: status equals the latest history status | PASS | 17 | 0 |
| arithmetic | alarm_lot_impact: impact_level follows the requirement rule | PASS | 152 | 0 |
| arithmetic | alarm_lot_impact: overlap derived from breach window x stay | PASS | 152 | 0 |
| arithmetic | door_event: duration_s == closed_at - opened_at | PASS | 1,713 | 0 |
| arithmetic | door_event: exceeded_limit == duration_s > zone limit | PASS | 1,713 | 0 |
| arithmetic | inventory_lot: current_state equals latest history state | PASS | 400 | 0 |
| arithmetic | lot_zone_assignment: dwell_minutes == (stored_to - stored_from)/60 | PASS | 400 | 0 |
| arithmetic | remediation: units_affected == lot.quantity_units | PASS | 34 | 0 |
| arithmetic | sensor_gap: alarm_raised == missed >= min_gap_readings | PASS | 8 | 0 |
| arithmetic | sensor_gap: missed_readings == (gap_end - gap_start)/interval | PASS | 8 | 0 |
| arithmetic | sensor_reading: declared gap intervals never exceed missing intervals | PASS | 40 | 0 |
| dates | alarm: breach_end > breach_start and opened_at >= breach_start | PASS | 17 | 0 |
| dates | alarm: closed_at >= opened_at | PASS | 17 | 0 |
| dates | alarm_state_history: timestamps non-decreasing | PASS | 79 | 0 |
| dates | door_event: closed_at > opened_at | PASS | 1,713 | 0 |
| dates | door_event: events of a zone do not overlap | PASS | 1,713 | 0 |
| dates | inspection: scheduled <= started <= completed | PASS | 12 | 0 |
| dates | inspection: scheduled_at >= alarm.opened_at | PASS | 12 | 0 |
| dates | lot_state_history: RECEIVED event equals received_at | PASS | 400 | 0 |
| dates | lot_state_history: timestamps non-decreasing | PASS | 1,061 | 0 |
| dates | lot_zone_assignment: stored_from >= lot.received_at | PASS | 400 | 0 |
| dates | lot_zone_assignment: stored_to > stored_from | PASS | 400 | 0 |
| dates | remediation: performed_at >= inspection.completed_at | PASS | 45 | 0 |
| dates | sensor_reading: not before sensor install date | PASS | 53,603 | 0 |
| dates | sensor_reading: strictly increasing per sensor (no duplicate timestamps) | PASS | 53,603 | 0 |
| dates | sensor_reading: timestamp on the 15-minute grid, inside the period | PASS | 53,603 | 0 |
| dates | sensor_zone_assignment: effective_to >= effective_from | PASS | 52 | 0 |
| enums | alarm: enum values allowed | PASS | 68 | 0 |
| enums | alarm_lot_impact: enum values allowed | PASS | 304 | 0 |
| enums | alarm_state_history: enum values allowed | PASS | 299 | 0 |
| enums | door_event: enum values allowed | PASS | 1,713 | 0 |
| enums | inspection: enum values allowed | PASS | 36 | 0 |
| enums | inventory_lot: enum values allowed | PASS | 800 | 0 |
| enums | lot_state_history: enum values allowed | PASS | 2,783 | 0 |
| enums | lot_zone_assignment: enum values allowed | PASS | 400 | 0 |
| enums | remediation: enum values allowed | PASS | 135 | 0 |
| enums | sensor: enum values allowed | PASS | 150 | 0 |
| enums | sensor_reading: enum values allowed | PASS | 53,603 | 0 |
| enums | sensor_zone_assignment: enum values allowed | PASS | 51 | 0 |
| enums | storage_requirement: enum values allowed | PASS | 7 | 0 |
| enums | warehouse: enum values allowed | PASS | 2 | 0 |
| enums | zone: enum values allowed | PASS | 20 | 0 |
| ids | alarm: ID/pattern format | PASS | 17 | 0 |
| ids | alarm_lot_impact: ID/pattern format | PASS | 152 | 0 |
| ids | alarm_state_history: ID/pattern format | PASS | 79 | 0 |
| ids | door_event: ID/pattern format | PASS | 1,713 | 0 |
| ids | door_event: id embeds zone and opened timestamp | PASS | 1,713 | 0 |
| ids | inspection: ID/pattern format | PASS | 12 | 0 |
| ids | inventory_lot: ID/pattern format | PASS | 400 | 0 |
| ids | lot_state_history: ID/pattern format | PASS | 1,061 | 0 |
| ids | lot_zone_assignment: ID/pattern format | PASS | 400 | 0 |
| ids | remediation: ID/pattern format | PASS | 45 | 0 |
| ids | sensor: ID/pattern format | PASS | 50 | 0 |
| ids | sensor_gap: ID/pattern format | PASS | 8 | 0 |
| ids | sensor_reading: ID/pattern format | PASS | 53,603 | 0 |
| ids | sensor_zone_assignment: ID/pattern format | PASS | 52 | 0 |
| ids | storage_requirement: ID/pattern format | PASS | 7 | 0 |
| ids | warehouse: ID/pattern format | PASS | 2 | 0 |
| ids | zone: ID/pattern format | PASS | 10 | 0 |
| info | missing reading intervals not covered by a sensor_gap row (see evaluation: GAP_TREATED_AS_NORMAL) | INFO | - | 92 |
| joins | FK alarm.sensor_id -> sensor.sensor_id | PASS | 14 | 0 |
| joins | FK alarm.zone_id -> zone.zone_id | PASS | 8 | 0 |
| joins | FK alarm_lot_impact.alarm_id -> alarm.alarm_id | PASS | 9 | 0 |
| joins | FK alarm_lot_impact.assignment_id -> lot_zone_assignment.assignment_id | PASS | 114 | 0 |
| joins | FK alarm_lot_impact.lot_id -> inventory_lot.lot_id | PASS | 114 | 0 |
| joins | FK alarm_lot_impact.remediation_id -> remediation.remediation_id | PASS | 17 | 0 |
| joins | FK alarm_state_history.alarm_id -> alarm.alarm_id | PASS | 17 | 0 |
| joins | FK door_event.sensor_id -> sensor.sensor_id | PASS | 10 | 0 |
| joins | FK door_event.zone_id -> zone.zone_id | PASS | 10 | 0 |
| joins | FK inspection.alarm_id -> alarm.alarm_id | PASS | 12 | 0 |
| joins | FK inspection.zone_id -> zone.zone_id | PASS | 6 | 0 |
| joins | FK inventory_lot.requirement_id -> storage_requirement.requirement_id | PASS | 7 | 0 |
| joins | FK lot_state_history.lot_id -> inventory_lot.lot_id | PASS | 400 | 0 |
| joins | FK lot_state_history.remediation_id -> remediation.remediation_id | PASS | 34 | 0 |
| joins | FK lot_zone_assignment.lot_id -> inventory_lot.lot_id | PASS | 400 | 0 |
| joins | FK lot_zone_assignment.zone_id -> zone.zone_id | PASS | 10 | 0 |
| joins | FK remediation.alarm_id -> alarm.alarm_id | PASS | 12 | 0 |
| joins | FK remediation.inspection_id -> inspection.inspection_id | PASS | 12 | 0 |
| joins | FK remediation.lot_id -> inventory_lot.lot_id | PASS | 17 | 0 |
| joins | FK remediation.sensor_id -> sensor.sensor_id | PASS | 5 | 0 |
| joins | FK remediation.zone_id -> zone.zone_id | PASS | 6 | 0 |
| joins | FK sensor.home_zone_id -> zone.zone_id | PASS | 10 | 0 |
| joins | FK sensor_gap.sensor_id -> sensor.sensor_id | PASS | 8 | 0 |
| joins | FK sensor_gap.zone_id -> zone.zone_id | PASS | 5 | 0 |
| joins | FK sensor_reading.sensor_id -> sensor.sensor_id | PASS | 40 | 0 |
| joins | FK sensor_reading.zone_id -> zone.zone_id | PASS | 10 | 0 |
| joins | FK sensor_zone_assignment.sensor_id -> sensor.sensor_id | PASS | 50 | 0 |
| joins | FK sensor_zone_assignment.zone_id -> zone.zone_id | PASS | 10 | 0 |
| joins | FK zone.warehouse_id -> warehouse.warehouse_id | PASS | 2 | 0 |
| joins | alarm: triggering sensor homed in alarm zone | PASS | 17 | 0 |
| joins | alarm_lot_impact: assignment belongs to the lot and the alarm's zone | PASS | 152 | 0 |
| joins | door_event: sensor is a DOOR sensor homed in the zone | PASS | 1,713 | 0 |
| joins | inspection: zone equals alarm zone | PASS | 12 | 0 |
| joins | inventory_lot: requirement category equals lot category | PASS | 400 | 0 |
| joins | lot_state_history: ALARM_HOLD references a QUARANTINE_LOT remediation | PASS | 17 | 0 |
| joins | remediation: inspection belongs to the same alarm | PASS | 45 | 0 |
| joins | remediation: lot action has a lot and links to inventory impact (alarm_lot_impact) | PASS | 34 | 0 |
| joins | remediation: non-lot action has no lot; sensor action has a sensor | PASS | 11 | 0 |
| joins | remediation: zone equals alarm zone | PASS | 45 | 0 |
| joins | semantic checks ran (they need intact foreign keys) | PASS | 1 | 0 |
| joins | sensor: sensor_id embeds home zone and type | PASS | 50 | 0 |
| joins | sensor: unit matches type | PASS | 50 | 0 |
| joins | sensor_gap: sensor homed in gap zone and not a DOOR sensor | PASS | 8 | 0 |
| joins | sensor_reading: reading_id == RDG-<sensor_id>-<timestamp> | PASS | 53,603 | 0 |
| joins | sensor_reading: unit equals sensor unit | PASS | 53,603 | 0 |
| joins | sensor_reading: zone has an active sensor assignment at measured_at | PASS | 53,603 | 0 |
| joins | zone: zone_id embeds its warehouse_id | PASS | 10 | 0 |
| keys | alarm: no duplicate (type, sensor, breach_start) | PASS | 17 | 0 |
| keys | alarm: primary key unique | PASS | 17 | 0 |
| keys | alarm_lot_impact: (alarm_id, lot_id) unique | PASS | 152 | 0 |
| keys | alarm_lot_impact: primary key unique | PASS | 152 | 0 |
| keys | alarm_state_history: primary key unique | PASS | 79 | 0 |
| keys | door_event: (zone_id, opened_at) unique | PASS | 1,713 | 0 |
| keys | door_event: primary key unique | PASS | 1,713 | 0 |
| keys | inspection: primary key unique | PASS | 12 | 0 |
| keys | inventory_lot: primary key unique | PASS | 400 | 0 |
| keys | lot_state_history: primary key unique | PASS | 1,061 | 0 |
| keys | lot_zone_assignment: primary key unique | PASS | 400 | 0 |
| keys | remediation: primary key unique | PASS | 45 | 0 |
| keys | sensor: primary key unique | PASS | 50 | 0 |
| keys | sensor_gap: primary key unique | PASS | 8 | 0 |
| keys | sensor_reading: primary key unique | PASS | 53,603 | 0 |
| keys | sensor_zone_assignment: primary key unique | PASS | 52 | 0 |
| keys | storage_requirement: primary key unique | PASS | 7 | 0 |
| keys | warehouse: primary key unique | PASS | 2 | 0 |
| keys | zone: primary key unique | PASS | 10 | 0 |
| lifecycle | alarm_lot_impact: disposition consistent with linked remediation | PASS | 152 | 0 |
| lifecycle | alarm_lot_impact: every MAJOR impact has a remediation or is a cut-off artefact | PASS | 152 | 0 |
| lifecycle | alarm_state_history: every alarm has a history | PASS | 17 | 0 |
| lifecycle | alarm_state_history: first event OPENED at opened_at | PASS | 17 | 0 |
| lifecycle | alarm_state_history: transitions follow the allowed lifecycle | PASS | 79 | 0 |
| lifecycle | inspection: status consistent with timestamps and outcome | PASS | 12 | 0 |
| lifecycle | lot stay closed exactly when the lot is SHIPPED/DISPOSED | PASS | 400 | 0 |
| lifecycle | lot_state_history: every lot has a history | PASS | 400 | 0 |
| lifecycle | lot_state_history: reason consistent with state | PASS | 1,061 | 0 |
| lifecycle | lot_state_history: transitions follow the allowed lifecycle | PASS | 1,061 | 0 |
| lifecycle | lot_zone_assignment: first stay is PUTAWAY, later stays TRANSFER | PASS | 400 | 0 |
| ordering | alarm: ids follow opened_at order | PASS | 17 | 0 |
| ranges | inventory_lot: quantity_units > 0 | PASS | 400 | 0 |
| ranges | sensor_reading: occupancy is a whole number | PASS | 13,410 | 0 |
| ranges | sensor_reading: value in physical range | PASS | 53,603 | 0 |
| ranges | zone: temp_min < setpoint < temp_max | PASS | 10 | 0 |
| required | alarm_lot_impact: required fields present | PASS | 135 | 0 |
| required | alarm_state_history: required fields present | PASS | 72 | 0 |
| required | lot_state_history: required fields present | PASS | 1,427 | 0 |
| required | lot_zone_assignment: required fields present | PASS | 316 | 0 |
| required | remediation: required fields present | PASS | 62 | 0 |
| required | sensor: reading_interval_s only for non-DOOR | PASS | 50 | 0 |
| required | sensor: required fields present | PASS | 10 | 0 |
| required | sensor_zone_assignment: required fields present | PASS | 53 | 0 |
| required | storage_requirement: required fields present | PASS | 8 | 0 |
| required | zone: required fields present | PASS | 10 | 0 |
| schema | CSV header equals schema field order | PASS | 16 | 0 |
| thresholds | alarm: peak is beyond the threshold (TEMP_HIGH/HUMIDITY/DOOR/OCC above, TEMP_LOW below) | PASS | 17 | 0 |
| thresholds | alarm: threshold_value equals the zone limit for its type | PASS | 17 | 0 |
| types | alarm: field types parse | PASS | 238 | 0 |
| types | alarm_lot_impact: field types parse | PASS | 1,385 | 0 |
| types | alarm_state_history: field types parse | PASS | 560 | 0 |
| types | door_event: field types parse | PASS | 13,704 | 0 |
| types | inspection: field types parse | PASS | 108 | 0 |
| types | inventory_lot: field types parse | PASS | 2,800 | 0 |
| types | lot_state_history: field types parse | PASS | 6,000 | 0 |
| types | lot_zone_assignment: field types parse | PASS | 2,484 | 0 |
| types | remediation: field types parse | PASS | 433 | 0 |
| types | sensor: field types parse | PASS | 390 | 0 |
| types | sensor_gap: field types parse | PASS | 56 | 0 |
| types | sensor_reading: field types parse | PASS | 321,618 | 0 |
| types | sensor_zone_assignment: field types parse | PASS | 259 | 0 |
| types | storage_requirement: field types parse | PASS | 55 | 0 |
| types | warehouse: field types parse | PASS | 16 | 0 |
| types | zone: field types parse | PASS | 130 | 0 |
