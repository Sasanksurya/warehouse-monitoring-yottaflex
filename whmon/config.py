"""All tunable parameters in one place: scale presets, zone-type physics,
storage requirements, monitoring rules and injection rates."""
from __future__ import annotations

import calendar
import time
from dataclasses import dataclass

DEFAULT_SEED = 20261022
INTERVAL_S = 900                       # reading cadence for TEMP / HUM / OCC sensors
STEPS_PER_DAY = 86400 // INTERVAL_S
LOT_YEAR = 2026
LOT_LOOKBACK_DAYS = 20                 # lots may be received before the monitoring window
PERIOD_START_ISO = "2026-09-01T00:00:00Z"
PERIOD_START_EPOCH = calendar.timegm(time.strptime("2026-09-01T00:00:00", "%Y-%m-%dT%H:%M:%S"))


@dataclass(frozen=True)
class Scale:
    name: str
    warehouses: int
    zones_per_warehouse: int
    days: int
    lots: int

    @property
    def zones(self) -> int:
        return self.warehouses * self.zones_per_warehouse

    @property
    def sensors(self) -> int:
        return self.zones * 5

    @property
    def n_steps(self) -> int:
        return self.days * STEPS_PER_DAY


# full: 10 warehouses, 100 zones, 500 sensors, ~1.03M readings (400 reading sensors x 27 days x 96), 10,000 lots
SCALES = {
    "starter": Scale("starter", 2, 5, 14, 400),
    "full": Scale("full", 10, 10, 27, 10000),
}


@dataclass(frozen=True)
class ZoneSpec:
    zone_type: str
    temp_min_c: float
    temp_max_c: float
    setpoint_c: float
    humidity_max_pct: float
    humidity_set_pct: float
    max_occupancy: int
    door_open_limit_s: int
    capacity_lots: int
    door_rate_per_day: float      # mean door events per day
    door_median_s: float          # median door-open duration
    temp_noise_c: float           # AR(1) innovation sigma
    door_kick_c: float            # deviation added per fully-open step (sign = direction of heat exchange)
    diurnal_amp_c: float
    type_weight: float


ZONE_SPECS = {
    "FROZEN":  ZoneSpec("FROZEN", -25, -15, -20.0, 85, 65, 4, 240, 150, 6, 70, 0.25, 0.9, 0.10, 1.0),
    "COLD":    ZoneSpec("COLD", 2, 8, 5.0, 70, 55, 8, 300, 150, 14, 90, 0.20, 0.7, 0.15, 2.0),
    "COOL":    ZoneSpec("COOL", 8, 15, 11.5, 85, 70, 8, 420, 150, 10, 100, 0.20, 0.5, 0.30, 1.0),
    "AMBIENT": ZoneSpec("AMBIENT", 15, 25, 20.0, 60, 45, 25, 600, 200, 22, 150, 0.35, 0.2, 1.20, 3.0),
    "HOT":     ZoneSpec("HOT", 30, 40, 35.0, 45, 30, 6, 480, 150, 8, 120, 0.40, -0.8, 1.00, 0.7),
}
ZONE_TYPE_ORDER = ["FROZEN", "COLD", "COOL", "AMBIENT", "HOT"]
DOOR_REASONS = [("LOADING", 40), ("PICKING", 35), ("INSPECTION", 5), ("CLEANING", 5), ("UNKNOWN", 15)]

# Storage requirements, one active version per product category.
# A zone is COMPATIBLE with a requirement when the zone's design band lies inside the requirement band
# and the zone's humidity ceiling does not exceed the requirement's humidity ceiling.
REQUIREMENTS = [
    # category, tmin, tmax, hum_max (None = not controlled), max_excursion_min, weight, dwell_days(min,max), qty (lo,hi)
    ("FROZEN_FOOD",      -25, -15, None, 180,  16, (6, 30),  (50, 1500)),
    ("DAIRY",              2,   8, 80,  120,  18, (2, 10),  (40, 1200)),
    ("PHARMA_COLD",        2,   8, 70,   60,  10, (3, 20),  (10, 400)),
    ("PRODUCE",            8,  15, 90,  240,  14, (1, 6),   (80, 2000)),
    ("ELECTRONICS",       15,  25, 60,  480,  12, (5, 40),  (20, 800)),
    ("DRY_GOODS",         10,  30, 70,  720,  22, (7, 45),  (100, 3000)),
    ("CURING_MATERIALS",  30,  40, 50,  240,   8, (4, 25),  (30, 900)),
]

# Documented monitoring rules (exported to monitoring_rules.json and used by the rule engine).
RULES = {
    "reading_interval_s": INTERVAL_S,
    "min_breach_readings": 2,            # consecutive out-of-band readings before an alarm opens (30 min)
    "clear_readings": 2,                 # hysteresis: breach runs separated by fewer than this many readings are one alarm
    "band_inclusive": True,              # value == limit is NOT a breach
    "critical_temp_margin_c": 3.0,       # beyond limit by >= this => CRITICAL
    "critical_humidity_margin_pct": 10.0,
    "critical_duration_min": 120,
    "door_critical_multiple": 3.0,       # door open >= 3x limit => CRITICAL
    "min_gap_readings": 3,               # missing readings (45 min) before SENSOR_GAP alarm
    "gap_critical_readings": 12,
    "drift_threshold_c": 1.0,            # |daily mean(TEMP-01 - TEMP-02)| above this
    "drift_min_days": 2,
    "occupancy_rule": "reading > zone.max_occupancy raises OCCUPANCY_LIMIT on first reading",
    "lot_link_alarm_types": ["TEMP_HIGH", "TEMP_LOW", "HUMIDITY_HIGH", "SENSOR_GAP", "SENSOR_DRIFT"],
}

# Injection rates. Counts are Poisson per zone: rate_per_zone_day * days.
RATES = {
    "temp_fail": 0.022,          # equipment failure (HOT zones: heating loss)
    "temp_overshoot": 0.006,     # opposite direction
    "humidity": 0.010,
    "door_left_open": 0.018,
    "occupancy": 0.010,
    "transient_spike": 0.015,    # one reading beyond limit: must NOT alarm
    "boundary_min_persistence": 0.010,  # exactly min_breach_readings: must alarm
    "drift_zone_fraction": 0.10,
    "outage_per_sensor_27d": 0.35,
    "hidden_gap_zone_fraction": 0.08,        # edge case: reading gap treated as normal
    "incompatible_lot_fraction": 0.01,       # edge case: lot assigned to incompatible zone
    "multi_zone_no_rationale_fraction": 0.02,  # edge case: sensor mapped to >1 zone, no rationale
    "multi_zone_with_rationale_fraction": 0.01,  # valid shared-coverage mappings
    "alarm_unlinked_prob": 0.08,             # edge case: alarm not linked to affected lots
    "transfer_fraction": 0.08,
}


@dataclass(frozen=True)
class Config:
    seed: int = DEFAULT_SEED
    scale: Scale = SCALES["full"]

    @property
    def n_steps(self) -> int:
        return self.scale.n_steps

    @property
    def start_epoch(self) -> int:
        return PERIOD_START_EPOCH

    @property
    def end_epoch(self) -> int:
        return PERIOD_START_EPOCH + self.scale.days * 86400


def make_config(scale: str = "full", seed: int = DEFAULT_SEED, **overrides) -> Config:
    base = SCALES[scale]
    if overrides:
        base = Scale(overrides.get("name", "custom"), overrides.get("warehouses", base.warehouses),
                     overrides.get("zones_per_warehouse", base.zones_per_warehouse),
                     overrides.get("days", base.days), overrides.get("lots", base.lots))
    return Config(seed=seed, scale=base)
