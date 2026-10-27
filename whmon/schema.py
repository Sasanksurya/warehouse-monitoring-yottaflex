"""Single source of truth for the data model. The data dictionary, SQL DDL, CSV headers and the
validator are all generated from the TABLES defined here."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

STRING, INTEGER, FLOAT, TIMESTAMP, DATE, BOOLEAN = "STRING", "INTEGER", "FLOAT", "TIMESTAMP", "DATE", "BOOLEAN"

ZONE_TYPES = ["FROZEN", "COLD", "COOL", "AMBIENT", "HOT"]
CATEGORIES = ["FROZEN_FOOD", "DAIRY", "PHARMA_COLD", "PRODUCE", "ELECTRONICS", "DRY_GOODS", "CURING_MATERIALS"]
ALARM_TYPES = ["TEMP_HIGH", "TEMP_LOW", "HUMIDITY_HIGH", "DOOR_OPEN_TOO_LONG", "OCCUPANCY_LIMIT",
               "SENSOR_GAP", "SENSOR_DRIFT"]
ROLES = ["PLANT_OPERATOR", "MAINTENANCE_ENGINEER", "QUALITY_ENGINEER", "PRODUCTION_PLANNER", "OT_IT_ADMIN", "SYSTEM"]
ALARM_STATUSES = ["OPEN", "ACKNOWLEDGED", "ESCALATED", "UNDER_INSPECTION", "REMEDIATED", "CLOSED"]
LOT_STATES = ["RECEIVED", "STORED", "QUARANTINED", "DISPOSED", "SHIPPED"]
ALARM_TRANSITIONS = {
    None: {"OPEN"},
    "OPEN": {"ACKNOWLEDGED"},
    "ACKNOWLEDGED": {"ESCALATED", "UNDER_INSPECTION", "CLOSED"},
    "ESCALATED": {"UNDER_INSPECTION"},
    "UNDER_INSPECTION": {"REMEDIATED", "CLOSED"},
    "REMEDIATED": {"CLOSED"},
    "CLOSED": set(),
}
LOT_TRANSITIONS = {
    None: {"RECEIVED"},
    "RECEIVED": {"STORED"},
    "STORED": {"QUARANTINED", "SHIPPED"},
    "QUARANTINED": {"DISPOSED", "STORED"},
    "DISPOSED": set(),
    "SHIPPED": set(),
}


@dataclass
class Field:
    name: str
    type: str
    required: bool = True
    enum: Optional[list] = None
    unit: str = ""
    unique: bool = False
    rule: str = ""
    fk: str = ""            # "table.column"
    pattern: str = ""       # regex for IDs


@dataclass
class Table:
    name: str
    description: str
    pk: str
    fields: list
    relationships: list = field(default_factory=list)
    natural_key: tuple = ()  # additional uniqueness constraint

    def field(self, name):
        return next(f for f in self.fields if f.name == name)

    @property
    def names(self):
        return [f.name for f in self.fields]


def F(name, type=STRING, required=True, **kw):
    return Field(name, type, required, **kw)


TABLES = [
    Table("warehouse", "A physical warehouse site (master data).", "warehouse_id", [
        F("warehouse_id", pattern=r"^WH-\d{3}$", unique=True, rule="Immutable, zero-padded counter"),
        F("name"), F("city"), F("country"),
        F("utc_offset_minutes", INTEGER, unit="minutes", rule="Local offset used for shift patterns; timestamps stay UTC"),
        F("floor_area_sqm", INTEGER, unit="m2", rule="> 0"),
        F("status", enum=["ACTIVE", "INACTIVE"]),
        F("commissioned_date", DATE),
    ], ["warehouse 1:N zone"]),

    Table("zone", "Climate/occupancy-controlled area inside a warehouse (master data). Band = alert thresholds.", "zone_id", [
        F("zone_id", pattern=r"^ZONE-WH-\d{3}-\d{3}$", unique=True, rule="ZONE-<warehouse-id>-NNN"),
        F("warehouse_id", fk="warehouse.warehouse_id", rule="Must match the warehouse embedded in zone_id"),
        F("zone_name"),
        F("zone_type", enum=ZONE_TYPES),
        F("temp_min_c", FLOAT, unit="C", rule="< temp_max_c; lower alert threshold"),
        F("temp_max_c", FLOAT, unit="C", rule="upper alert threshold"),
        F("setpoint_c", FLOAT, unit="C", rule="Within [temp_min_c, temp_max_c]"),
        F("humidity_max_pct", FLOAT, unit="%RH", rule="0-100; alert threshold"),
        F("max_occupancy", INTEGER, unit="persons", rule=">= 1; alert threshold"),
        F("door_open_limit_s", INTEGER, unit="seconds", rule="> 0; alert threshold"),
        F("capacity_lots", INTEGER, unit="lots", rule="> 0, informational"),
        F("status", enum=["ACTIVE", "INACTIVE"]),
        F("effective_from", DATE), F("effective_to", DATE, False, rule=">= effective_from when present"),
    ], ["zone 1:N sensor (home zone)", "zone N:M sensor via sensor_zone_assignment", "zone N:M inventory_lot via lot_zone_assignment"]),

    Table("sensor", "Physical sensor (master data). One TEMP x2, HUM, OCC, DOOR per zone.", "sensor_id", [
        F("sensor_id", pattern=r"^SNS-ZONE-WH-\d{3}-\d{3}-(TEMP|HUM|OCC|DOOR)-\d{2}$", unique=True,
          rule="SNS-<zone-id>-<TYPE>-NN; embeds home zone and type"),
        F("home_zone_id", fk="zone.zone_id", rule="Equals the zone embedded in sensor_id"),
        F("sensor_type", enum=["TEMP", "HUM", "OCC", "DOOR"]),
        F("unit", enum=["C", "PCT_RH", "PERSONS", "EVENT"], rule="TEMP->C, HUM->PCT_RH, OCC->PERSONS, DOOR->EVENT"),
        F("model"), F("install_date", DATE),
        F("status", enum=["ACTIVE", "FAULTY", "DECOMMISSIONED"]),
        F("reading_interval_s", INTEGER, False, unit="seconds", rule="Required for TEMP/HUM/OCC, empty for DOOR"),
    ], ["sensor N:M zone via sensor_zone_assignment"]),

    Table("sensor_zone_assignment", "Bridge: effective-dated placement of a sensor in a zone (N:M). A second active zone requires a rationale.",
          "assignment_id", [
        F("assignment_id", pattern=r"^SZA-\d{6}$", unique=True),
        F("sensor_id", fk="sensor.sensor_id"), F("zone_id", fk="zone.zone_id"),
        F("effective_from", DATE), F("effective_to", DATE, False, rule=">= effective_from; empty = still active"),
        F("rationale", STRING, False, enum=["PRIMARY_PLACEMENT", "SHARED_AIRSPACE_COVERAGE"],
          rule="Mandatory for every assignment except it may be empty only by defect (edge case SENSOR_MULTI_ZONE_NO_RATIONALE)"),
    ], ["sensor 1:N assignment N:1 zone"]),

    Table("storage_requirement", "Per product-category storage requirement (versioned, effective-dated).", "requirement_id", [
        F("requirement_id", pattern=r"^REQ-[A-Z_]+-\d{2}$", unique=True),
        F("product_category", enum=CATEGORIES),
        F("temp_min_c", FLOAT, unit="C"), F("temp_max_c", FLOAT, unit="C", rule="> temp_min_c"),
        F("humidity_max_pct", FLOAT, False, unit="%RH", rule="Empty = humidity not controlled"),
        F("max_excursion_min", INTEGER, unit="minutes", rule="Tolerated exposure before impact is MAJOR"),
        F("version", INTEGER, rule=">= 1"),
        F("effective_from", DATE), F("effective_to", DATE, False),
    ], ["requirement 1:N inventory_lot"]),

    Table("inventory_lot", "A received lot of product. current_state is derived from lot_state_history.", "lot_id", [
        F("lot_id", pattern=r"^LOT-2026-\d{6}$", unique=True),
        F("product_code"), F("product_category", enum=CATEGORIES),
        F("requirement_id", fk="storage_requirement.requirement_id", rule="Category must equal the requirement's category"),
        F("quantity_units", INTEGER, unit="units", rule="> 0"),
        F("received_at", TIMESTAMP),
        F("current_state", enum=LOT_STATES, rule="DERIVED: to_state of the latest lot_state_history row"),
    ], ["lot N:M zone via lot_zone_assignment", "lot 1:N lot_state_history", "lot N:M alarm via alarm_lot_impact"]),

    Table("lot_zone_assignment", "Bridge: where a lot was stored and for how long (N:M over time). Dwell = stored_to - stored_from.",
          "assignment_id", [
        F("assignment_id", pattern=r"^LZA-\d{6}$", unique=True),
        F("lot_id", fk="inventory_lot.lot_id"), F("zone_id", fk="zone.zone_id"),
        F("stored_from", TIMESTAMP, rule=">= lot.received_at"),
        F("stored_to", TIMESTAMP, False, rule="> stored_from; empty = still stored at data cutoff"),
        F("dwell_minutes", INTEGER, False, unit="minutes", rule="DERIVED: (stored_to - stored_from)/60; empty if open"),
        F("assignment_reason", enum=["PUTAWAY", "TRANSFER"]),
    ], ["Assignments of one lot never overlap in time"]),

    Table("sensor_reading", "Telemetry. One row per sensor per interval; missing intervals are gaps (see sensor_gap).", "reading_id", [
        F("reading_id", pattern=r"^RDG-SNS-ZONE-WH-\d{3}-\d{3}-(TEMP|HUM|OCC)-\d{2}-\d{8}T\d{6}Z$", unique=True,
          rule="RDG-<sensor-id>-<timestamp>; must equal sensor_id + measured_at"),
        F("sensor_id", fk="sensor.sensor_id"), F("zone_id", fk="zone.zone_id", rule="A zone with an active assignment for the sensor at measured_at"),
        F("measured_at", TIMESTAMP, rule="UTC, aligned to the 15-minute grid; unique per sensor"),
        F("value", FLOAT, unit="per sensor unit", rule="TEMP -60..80, HUM 0..100, OCC >= 0 integer"),
        F("unit", enum=["C", "PCT_RH", "PERSONS"], rule="Equals sensor.unit"),
    ], ["sensor 1:N reading"], natural_key=("sensor_id", "measured_at")),

    Table("door_event", "Door open/close event from a DOOR sensor.", "door_event_id", [
        F("door_event_id", pattern=r"^DOOR-ZONE-WH-\d{3}-\d{3}-\d{8}T\d{6}Z$", unique=True, rule="DOOR-<zone-id>-<opened-timestamp>"),
        F("zone_id", fk="zone.zone_id"), F("sensor_id", fk="sensor.sensor_id", rule="A DOOR sensor homed in zone_id"),
        F("opened_at", TIMESTAMP), F("closed_at", TIMESTAMP, rule="> opened_at"),
        F("duration_s", INTEGER, unit="seconds", rule="DERIVED: closed_at - opened_at"),
        F("open_reason", enum=["LOADING", "PICKING", "INSPECTION", "CLEANING", "UNKNOWN"]),
        F("exceeded_limit", BOOLEAN, rule="DERIVED: duration_s > zone.door_open_limit_s"),
    ], ["zone 1:N door_event", "Events of one zone never overlap"]),

    Table("sensor_gap", "Explicit record of missing readings, detected by the monitoring engine from the telemetry itself.",
          "gap_id", [
        F("gap_id", pattern=r"^GAP-SNS-ZONE-WH-\d{3}-\d{3}-(TEMP|HUM|OCC)-\d{2}-\d{8}T\d{6}Z$", unique=True),
        F("sensor_id", fk="sensor.sensor_id"), F("zone_id", fk="zone.zone_id"),
        F("gap_start", TIMESTAMP, rule="First missing grid timestamp"),
        F("gap_end", TIMESTAMP, rule="Timestamp of the next received reading (exclusive)"),
        F("missed_readings", INTEGER, rule="DERIVED: (gap_end - gap_start)/interval"),
        F("alarm_raised", BOOLEAN, rule="DERIVED: missed_readings >= rules.min_gap_readings"),
    ], ["sensor 1:N gap"]),

    Table("alarm", "Alert raised by the rule engine; status mirrors the latest alarm_state_history row.", "alarm_id", [
        F("alarm_id", pattern=r"^ALM-2026-\d{6}$", unique=True, rule="Numbered in opened_at order"),
        F("zone_id", fk="zone.zone_id"), F("sensor_id", fk="sensor.sensor_id", rule="Triggering sensor; homed in zone_id"),
        F("alarm_type", enum=ALARM_TYPES), F("severity", enum=["WARNING", "CRITICAL"]),
        F("breach_start", TIMESTAMP), F("breach_end", TIMESTAMP, rule="> breach_start (exclusive end of the breach window)"),
        F("opened_at", TIMESTAMP, rule=">= breach_start"),
        F("closed_at", TIMESTAMP, False, rule=">= opened_at; empty unless status = CLOSED"),
        F("status", enum=ALARM_STATUSES, rule="DERIVED: to_status of latest alarm_state_history row"),
        F("peak_value", FLOAT, unit="threshold_unit", rule="Worst observed value (drift: max |daily mean diff|; gap: missed readings)"),
        F("threshold_value", FLOAT, unit="threshold_unit", rule="Must equal the zone limit (or rule parameter) for alarm_type"),
        F("threshold_unit", enum=["C", "PCT_RH", "SECONDS", "PERSONS", "READINGS"]),
        F("duration_minutes", INTEGER, unit="minutes", rule="DERIVED: (breach_end - breach_start)/60"),
    ], ["zone 1:N alarm", "alarm N:M lot via alarm_lot_impact", "alarm 1:N inspection", "alarm 1:N remediation"]),

    Table("alarm_state_history", "Append-only log of alarm lifecycle transitions.", "event_id", [
        F("event_id", pattern=r"^AEV-\d{6}$", unique=True),
        F("alarm_id", fk="alarm.alarm_id"),
        F("event_type", enum=["OPENED", "ACKNOWLEDGED", "ESCALATED", "INSPECTION_STARTED", "REMEDIATION_COMPLETED", "CLOSED"]),
        F("from_status", enum=ALARM_STATUSES, required=False, rule="Empty only for the first event"),
        F("to_status", enum=ALARM_STATUSES), F("event_ts", TIMESTAMP, rule="Non-decreasing per alarm"),
        F("actor_role", enum=ROLES), F("reference_id", STRING, False, rule="Inspection/remediation id when relevant"),
    ], ["alarm 1:N state event"]),

    Table("inspection", "Physical inspection ordered for an alarm.", "inspection_id", [
        F("inspection_id", pattern=r"^INS-2026-\d{6}$", unique=True),
        F("alarm_id", fk="alarm.alarm_id"), F("zone_id", fk="zone.zone_id"),
        F("inspector_role", enum=["MAINTENANCE_ENGINEER", "QUALITY_ENGINEER", "OT_IT_ADMIN"]),
        F("scheduled_at", TIMESTAMP, rule=">= alarm.opened_at"),
        F("started_at", TIMESTAMP, False, rule=">= scheduled_at"),
        F("completed_at", TIMESTAMP, False, rule=">= started_at"),
        F("status", enum=["SCHEDULED", "IN_PROGRESS", "COMPLETED"], rule="COMPLETED requires completed_at and outcome"),
        F("outcome", enum=["EQUIPMENT_FAULT", "DOOR_PROCEDURE", "SENSOR_FAULT", "CONNECTIVITY_FAULT", "NO_FAULT_FOUND"],
          required=False),
    ], ["alarm 1:N inspection", "inspection 1:N remediation"]),

    Table("remediation", "Corrective action. Lot actions reference the lot and, through alarm_lot_impact, the inventory impact.",
          "remediation_id", [
        F("remediation_id", pattern=r"^REM-2026-\d{6}$", unique=True),
        F("alarm_id", fk="alarm.alarm_id"), F("inspection_id", fk="inspection.inspection_id", required=False),
        F("zone_id", fk="zone.zone_id"),
        F("sensor_id", fk="sensor.sensor_id", required=False, rule="Required for sensor actions"),
        F("lot_id", fk="inventory_lot.lot_id", required=False, rule="Required for lot actions; must have an alarm_lot_impact row for the alarm"),
        F("action_type", enum=["REPAIR_EQUIPMENT", "DOOR_SEAL_REPAIR", "RECALIBRATE_SENSOR", "RESTORE_CONNECTIVITY",
                               "QUARANTINE_LOT", "DISPOSE_LOT", "RELEASE_LOT", "NOTIFY_CUSTOMER"]),
        F("owner_role", enum=ROLES), F("performed_at", TIMESTAMP, rule=">= inspection.completed_at"),
        F("status", enum=["PLANNED", "COMPLETED"]),
        F("units_affected", INTEGER, False, unit="units", rule="DERIVED: lot.quantity_units for lot actions"),
    ], ["inspection 1:N remediation"]),

    Table("alarm_lot_impact", "Bridge (N:M): lots affected by an alarm, identified from time + zone overlap of the breach window with the lot's stay.",
          "impact_id", [
        F("impact_id", pattern=r"^IMP-\d{6}$", unique=True),
        F("alarm_id", fk="alarm.alarm_id"), F("lot_id", fk="inventory_lot.lot_id"),
        F("assignment_id", fk="lot_zone_assignment.assignment_id", rule="Assignment in the alarm's zone overlapping the breach window"),
        F("overlap_start", TIMESTAMP), F("overlap_end", TIMESTAMP, rule="> overlap_start"),
        F("overlap_minutes", INTEGER, unit="minutes", rule="DERIVED: intersection of breach window and assignment"),
        F("impact_level", enum=["NONE", "MINOR", "MAJOR", "UNVERIFIED"],
          rule="NONE: peak inside lot requirement; MINOR/MAJOR: outside requirement for < / >= max_excursion_min; UNVERIFIED: sensor gap/drift"),
        F("disposition", enum=["NO_ACTION", "HOLD_PLACED", "ALREADY_HELD", "SHIPPED_BEFORE_ACTION"]),
        F("remediation_id", fk="remediation.remediation_id", required=False),
    ], ["alarm N:M lot"], natural_key=("alarm_id", "lot_id")),

    Table("lot_state_history", "Append-only log of lot lifecycle transitions.", "event_id", [
        F("event_id", pattern=r"^LSE-\d{6}$", unique=True),
        F("lot_id", fk="inventory_lot.lot_id"),
        F("from_state", enum=LOT_STATES, required=False), F("to_state", enum=LOT_STATES),
        F("event_ts", TIMESTAMP, rule="Non-decreasing per lot"),
        F("reason", enum=["RECEIPT", "PUTAWAY", "ALARM_HOLD", "DISPOSAL", "RELEASED_FROM_HOLD", "SHIPMENT"]),
        F("remediation_id", fk="remediation.remediation_id", required=False),
    ], ["lot 1:N state event"]),
]

TABLE_BY_NAME = {t.name: t for t in TABLES}
TABLE_ORDER = [t.name for t in TABLES]


def data_dictionary_rows():
    for t in TABLES:
        for f in t.fields:
            yield {
                "table": t.name, "field": f.name, "type": f.type, "required": "yes" if f.required else "no",
                "allowed_values": "|".join(f.enum) if f.enum else (f"regex {f.pattern}" if f.pattern else ""),
                "unit": f.unit, "unique": "yes" if f.unique else "no",
                "key": ("PK" if f.name == t.pk else ("FK -> " + f.fk if f.fk else "")),
                "validation_rule": f.rule,
            }


def data_dictionary_markdown() -> str:
    out = ["# Data dictionary", "",
           "Generated from `whmon/schema.py` (do not edit by hand). Timestamps are UTC ISO-8601 (`YYYY-MM-DDTHH:MM:SSZ`).",
           "`DERIVED` fields are computed from source records, never generated independently.", ""]
    for t in TABLES:
        out += [f"## {t.name}", "", t.description, "",
                "| Field | Type | Req | Allowed values / pattern | Unit | Key | Rule |", "|---|---|---|---|---|---|---|"]
        for r in (x for x in data_dictionary_rows() if x["table"] == t.name):
            allowed = r["allowed_values"].replace("|", ", ").replace("regex ", "regex `") + ("`" if r["allowed_values"].startswith("regex") else "")
            out.append(f"| {r['field']} | {r['type']} | {r['required']} | {allowed} | {r['unit']} | {r['key']} | {r['validation_rule']} |")
        if t.natural_key:
            out.append(f"\nUnique together: `{', '.join(t.natural_key)}`")
        out += ["", "Relationships / cardinality: " + "; ".join(t.relationships), ""]
    return "\n".join(out)


SQL_TYPES = {STRING: "TEXT", INTEGER: "INTEGER", FLOAT: "REAL", TIMESTAMP: "TEXT", DATE: "TEXT", BOOLEAN: "INTEGER"}


def ddl() -> str:
    parts = []
    for t in TABLES:
        cols = []
        for f in t.fields:
            c = f"  {f.name} {SQL_TYPES[f.type]}"
            if f.name == t.pk:
                c += " PRIMARY KEY"
            elif f.required:
                c += " NOT NULL"
            if f.enum:
                vals = ", ".join(f"'{v}'" for v in f.enum)
                c += f" CHECK ({f.name} IS NULL OR {f.name} IN ({vals}))"
            cols.append(c)
        for f in t.fields:
            if f.fk:
                pt, pc = f.fk.split(".")
                cols.append(f"  FOREIGN KEY ({f.name}) REFERENCES {pt}({pc})")
        if t.natural_key:
            cols.append(f"  UNIQUE ({', '.join(t.natural_key)})")
        parts.append(f"CREATE TABLE {t.name} (\n" + ",\n".join(cols) + "\n);")
    parts.append("CREATE INDEX idx_reading_zone_time ON sensor_reading(zone_id, measured_at);")
    parts.append("CREATE INDEX idx_lot_assign_zone ON lot_zone_assignment(zone_id, stored_from, stored_to);")
    parts.append("CREATE INDEX idx_alarm_zone ON alarm(zone_id, breach_start);")
    return "\n\n".join(parts) + "\n"
