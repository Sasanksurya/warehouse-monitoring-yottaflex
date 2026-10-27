CREATE TABLE warehouse (
  warehouse_id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  city TEXT NOT NULL,
  country TEXT NOT NULL,
  utc_offset_minutes INTEGER NOT NULL,
  floor_area_sqm INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IS NULL OR status IN ('ACTIVE', 'INACTIVE')),
  commissioned_date TEXT NOT NULL
);

CREATE TABLE zone (
  zone_id TEXT PRIMARY KEY,
  warehouse_id TEXT NOT NULL,
  zone_name TEXT NOT NULL,
  zone_type TEXT NOT NULL CHECK (zone_type IS NULL OR zone_type IN ('FROZEN', 'COLD', 'COOL', 'AMBIENT', 'HOT')),
  temp_min_c REAL NOT NULL,
  temp_max_c REAL NOT NULL,
  setpoint_c REAL NOT NULL,
  humidity_max_pct REAL NOT NULL,
  max_occupancy INTEGER NOT NULL,
  door_open_limit_s INTEGER NOT NULL,
  capacity_lots INTEGER NOT NULL,
  status TEXT NOT NULL CHECK (status IS NULL OR status IN ('ACTIVE', 'INACTIVE')),
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  FOREIGN KEY (warehouse_id) REFERENCES warehouse(warehouse_id)
);

CREATE TABLE sensor (
  sensor_id TEXT PRIMARY KEY,
  home_zone_id TEXT NOT NULL,
  sensor_type TEXT NOT NULL CHECK (sensor_type IS NULL OR sensor_type IN ('TEMP', 'HUM', 'OCC', 'DOOR')),
  unit TEXT NOT NULL CHECK (unit IS NULL OR unit IN ('C', 'PCT_RH', 'PERSONS', 'EVENT')),
  model TEXT NOT NULL,
  install_date TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IS NULL OR status IN ('ACTIVE', 'FAULTY', 'DECOMMISSIONED')),
  reading_interval_s INTEGER,
  FOREIGN KEY (home_zone_id) REFERENCES zone(zone_id)
);

CREATE TABLE sensor_zone_assignment (
  assignment_id TEXT PRIMARY KEY,
  sensor_id TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT,
  rationale TEXT CHECK (rationale IS NULL OR rationale IN ('PRIMARY_PLACEMENT', 'SHARED_AIRSPACE_COVERAGE')),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id),
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id)
);

CREATE TABLE storage_requirement (
  requirement_id TEXT PRIMARY KEY,
  product_category TEXT NOT NULL CHECK (product_category IS NULL OR product_category IN ('FROZEN_FOOD', 'DAIRY', 'PHARMA_COLD', 'PRODUCE', 'ELECTRONICS', 'DRY_GOODS', 'CURING_MATERIALS')),
  temp_min_c REAL NOT NULL,
  temp_max_c REAL NOT NULL,
  humidity_max_pct REAL,
  max_excursion_min INTEGER NOT NULL,
  version INTEGER NOT NULL,
  effective_from TEXT NOT NULL,
  effective_to TEXT
);

CREATE TABLE inventory_lot (
  lot_id TEXT PRIMARY KEY,
  product_code TEXT NOT NULL,
  product_category TEXT NOT NULL CHECK (product_category IS NULL OR product_category IN ('FROZEN_FOOD', 'DAIRY', 'PHARMA_COLD', 'PRODUCE', 'ELECTRONICS', 'DRY_GOODS', 'CURING_MATERIALS')),
  requirement_id TEXT NOT NULL,
  quantity_units INTEGER NOT NULL,
  received_at TEXT NOT NULL,
  current_state TEXT NOT NULL CHECK (current_state IS NULL OR current_state IN ('RECEIVED', 'STORED', 'QUARANTINED', 'DISPOSED', 'SHIPPED')),
  FOREIGN KEY (requirement_id) REFERENCES storage_requirement(requirement_id)
);

CREATE TABLE lot_zone_assignment (
  assignment_id TEXT PRIMARY KEY,
  lot_id TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  stored_from TEXT NOT NULL,
  stored_to TEXT,
  dwell_minutes INTEGER,
  assignment_reason TEXT NOT NULL CHECK (assignment_reason IS NULL OR assignment_reason IN ('PUTAWAY', 'TRANSFER')),
  FOREIGN KEY (lot_id) REFERENCES inventory_lot(lot_id),
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id)
);

CREATE TABLE sensor_reading (
  reading_id TEXT PRIMARY KEY,
  sensor_id TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  measured_at TEXT NOT NULL,
  value REAL NOT NULL,
  unit TEXT NOT NULL CHECK (unit IS NULL OR unit IN ('C', 'PCT_RH', 'PERSONS')),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id),
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id),
  UNIQUE (sensor_id, measured_at)
);

CREATE TABLE door_event (
  door_event_id TEXT PRIMARY KEY,
  zone_id TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT NOT NULL,
  duration_s INTEGER NOT NULL,
  open_reason TEXT NOT NULL CHECK (open_reason IS NULL OR open_reason IN ('LOADING', 'PICKING', 'INSPECTION', 'CLEANING', 'UNKNOWN')),
  exceeded_limit INTEGER NOT NULL,
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id)
);

CREATE TABLE sensor_gap (
  gap_id TEXT PRIMARY KEY,
  sensor_id TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  gap_start TEXT NOT NULL,
  gap_end TEXT NOT NULL,
  missed_readings INTEGER NOT NULL,
  alarm_raised INTEGER NOT NULL,
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id),
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id)
);

CREATE TABLE alarm (
  alarm_id TEXT PRIMARY KEY,
  zone_id TEXT NOT NULL,
  sensor_id TEXT NOT NULL,
  alarm_type TEXT NOT NULL CHECK (alarm_type IS NULL OR alarm_type IN ('TEMP_HIGH', 'TEMP_LOW', 'HUMIDITY_HIGH', 'DOOR_OPEN_TOO_LONG', 'OCCUPANCY_LIMIT', 'SENSOR_GAP', 'SENSOR_DRIFT')),
  severity TEXT NOT NULL CHECK (severity IS NULL OR severity IN ('WARNING', 'CRITICAL')),
  breach_start TEXT NOT NULL,
  breach_end TEXT NOT NULL,
  opened_at TEXT NOT NULL,
  closed_at TEXT,
  status TEXT NOT NULL CHECK (status IS NULL OR status IN ('OPEN', 'ACKNOWLEDGED', 'ESCALATED', 'UNDER_INSPECTION', 'REMEDIATED', 'CLOSED')),
  peak_value REAL NOT NULL,
  threshold_value REAL NOT NULL,
  threshold_unit TEXT NOT NULL CHECK (threshold_unit IS NULL OR threshold_unit IN ('C', 'PCT_RH', 'SECONDS', 'PERSONS', 'READINGS')),
  duration_minutes INTEGER NOT NULL,
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id)
);

CREATE TABLE alarm_state_history (
  event_id TEXT PRIMARY KEY,
  alarm_id TEXT NOT NULL,
  event_type TEXT NOT NULL CHECK (event_type IS NULL OR event_type IN ('OPENED', 'ACKNOWLEDGED', 'ESCALATED', 'INSPECTION_STARTED', 'REMEDIATION_COMPLETED', 'CLOSED')),
  from_status TEXT CHECK (from_status IS NULL OR from_status IN ('OPEN', 'ACKNOWLEDGED', 'ESCALATED', 'UNDER_INSPECTION', 'REMEDIATED', 'CLOSED')),
  to_status TEXT NOT NULL CHECK (to_status IS NULL OR to_status IN ('OPEN', 'ACKNOWLEDGED', 'ESCALATED', 'UNDER_INSPECTION', 'REMEDIATED', 'CLOSED')),
  event_ts TEXT NOT NULL,
  actor_role TEXT NOT NULL CHECK (actor_role IS NULL OR actor_role IN ('PLANT_OPERATOR', 'MAINTENANCE_ENGINEER', 'QUALITY_ENGINEER', 'PRODUCTION_PLANNER', 'OT_IT_ADMIN', 'SYSTEM')),
  reference_id TEXT,
  FOREIGN KEY (alarm_id) REFERENCES alarm(alarm_id)
);

CREATE TABLE inspection (
  inspection_id TEXT PRIMARY KEY,
  alarm_id TEXT NOT NULL,
  zone_id TEXT NOT NULL,
  inspector_role TEXT NOT NULL CHECK (inspector_role IS NULL OR inspector_role IN ('MAINTENANCE_ENGINEER', 'QUALITY_ENGINEER', 'OT_IT_ADMIN')),
  scheduled_at TEXT NOT NULL,
  started_at TEXT,
  completed_at TEXT,
  status TEXT NOT NULL CHECK (status IS NULL OR status IN ('SCHEDULED', 'IN_PROGRESS', 'COMPLETED')),
  outcome TEXT CHECK (outcome IS NULL OR outcome IN ('EQUIPMENT_FAULT', 'DOOR_PROCEDURE', 'SENSOR_FAULT', 'CONNECTIVITY_FAULT', 'NO_FAULT_FOUND')),
  FOREIGN KEY (alarm_id) REFERENCES alarm(alarm_id),
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id)
);

CREATE TABLE remediation (
  remediation_id TEXT PRIMARY KEY,
  alarm_id TEXT NOT NULL,
  inspection_id TEXT,
  zone_id TEXT NOT NULL,
  sensor_id TEXT,
  lot_id TEXT,
  action_type TEXT NOT NULL CHECK (action_type IS NULL OR action_type IN ('REPAIR_EQUIPMENT', 'DOOR_SEAL_REPAIR', 'RECALIBRATE_SENSOR', 'RESTORE_CONNECTIVITY', 'QUARANTINE_LOT', 'DISPOSE_LOT', 'RELEASE_LOT', 'NOTIFY_CUSTOMER')),
  owner_role TEXT NOT NULL CHECK (owner_role IS NULL OR owner_role IN ('PLANT_OPERATOR', 'MAINTENANCE_ENGINEER', 'QUALITY_ENGINEER', 'PRODUCTION_PLANNER', 'OT_IT_ADMIN', 'SYSTEM')),
  performed_at TEXT NOT NULL,
  status TEXT NOT NULL CHECK (status IS NULL OR status IN ('PLANNED', 'COMPLETED')),
  units_affected INTEGER,
  FOREIGN KEY (alarm_id) REFERENCES alarm(alarm_id),
  FOREIGN KEY (inspection_id) REFERENCES inspection(inspection_id),
  FOREIGN KEY (zone_id) REFERENCES zone(zone_id),
  FOREIGN KEY (sensor_id) REFERENCES sensor(sensor_id),
  FOREIGN KEY (lot_id) REFERENCES inventory_lot(lot_id)
);

CREATE TABLE alarm_lot_impact (
  impact_id TEXT PRIMARY KEY,
  alarm_id TEXT NOT NULL,
  lot_id TEXT NOT NULL,
  assignment_id TEXT NOT NULL,
  overlap_start TEXT NOT NULL,
  overlap_end TEXT NOT NULL,
  overlap_minutes INTEGER NOT NULL,
  impact_level TEXT NOT NULL CHECK (impact_level IS NULL OR impact_level IN ('NONE', 'MINOR', 'MAJOR', 'UNVERIFIED')),
  disposition TEXT NOT NULL CHECK (disposition IS NULL OR disposition IN ('NO_ACTION', 'HOLD_PLACED', 'ALREADY_HELD', 'SHIPPED_BEFORE_ACTION')),
  remediation_id TEXT,
  FOREIGN KEY (alarm_id) REFERENCES alarm(alarm_id),
  FOREIGN KEY (lot_id) REFERENCES inventory_lot(lot_id),
  FOREIGN KEY (assignment_id) REFERENCES lot_zone_assignment(assignment_id),
  FOREIGN KEY (remediation_id) REFERENCES remediation(remediation_id),
  UNIQUE (alarm_id, lot_id)
);

CREATE TABLE lot_state_history (
  event_id TEXT PRIMARY KEY,
  lot_id TEXT NOT NULL,
  from_state TEXT CHECK (from_state IS NULL OR from_state IN ('RECEIVED', 'STORED', 'QUARANTINED', 'DISPOSED', 'SHIPPED')),
  to_state TEXT NOT NULL CHECK (to_state IS NULL OR to_state IN ('RECEIVED', 'STORED', 'QUARANTINED', 'DISPOSED', 'SHIPPED')),
  event_ts TEXT NOT NULL,
  reason TEXT NOT NULL CHECK (reason IS NULL OR reason IN ('RECEIPT', 'PUTAWAY', 'ALARM_HOLD', 'DISPOSAL', 'RELEASED_FROM_HOLD', 'SHIPMENT')),
  remediation_id TEXT,
  FOREIGN KEY (lot_id) REFERENCES inventory_lot(lot_id),
  FOREIGN KEY (remediation_id) REFERENCES remediation(remediation_id)
);

CREATE INDEX idx_reading_zone_time ON sensor_reading(zone_id, measured_at);

CREATE INDEX idx_lot_assign_zone ON lot_zone_assignment(zone_id, stored_from, stored_to);

CREATE INDEX idx_alarm_zone ON alarm(zone_id, breach_start);
