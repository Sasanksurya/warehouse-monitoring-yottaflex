"""Unit tests of the monitoring rule engine on hand-built telemetry (boundary and exception paths)."""
from whmon.config import make_config, INTERVAL_S
from whmon.detect import detect
from whmon.util import World, Clock

ZONE = {"zone_id": "ZONE-WH-001-001", "warehouse_id": "WH-001", "zone_type": "COLD", "temp_min_c": 2.0, "temp_max_c": 8.0,
        "setpoint_c": 5.0, "humidity_max_pct": 70.0, "max_occupancy": 8, "door_open_limit_s": 300}
Z = ZONE["zone_id"]
SIDS = {k: f"SNS-{Z}-{k}-01" for k in ("TEMP", "HUM", "OCC", "DOOR")} | {"TEMP2": f"SNS-{Z}-TEMP-02"}


def world(days=5, doors=()):
    cfg = make_config("starter", days=days)
    w = World(cfg, Clock(cfg))
    n = cfg.n_steps
    sensors = [{"sensor_id": SIDS["TEMP"], "home_zone_id": Z, "sensor_type": "TEMP"},
               {"sensor_id": SIDS["TEMP2"], "home_zone_id": Z, "sensor_type": "TEMP"},
               {"sensor_id": SIDS["HUM"], "home_zone_id": Z, "sensor_type": "HUM"},
               {"sensor_id": SIDS["OCC"], "home_zone_id": Z, "sensor_type": "OCC"},
               {"sensor_id": SIDS["DOOR"], "home_zone_id": Z, "sensor_type": "DOOR"}]
    w.tables = {"zone": [ZONE], "sensor": sensors, "door_event": list(doors)}
    w.readings = {SIDS["TEMP"]: [5.0] * n, SIDS["TEMP2"]: [5.0] * n, SIDS["HUM"]: [55.0] * n, SIDS["OCC"]: [0] * n}
    w.plans = {}
    return w


def alarms(w):
    detect(w)
    return w.plans["raw_alarms"]


def test_quiet_zone_raises_nothing():
    assert alarms(world()) == []


def test_value_equal_to_limit_is_not_a_breach():
    w = world()
    for i in range(10, 20):
        w.readings[SIDS["TEMP"]][i] = 8.0          # == temp_max_c
    assert alarms(w) == []


def test_single_reading_spike_does_not_alarm():
    w = world()
    w.readings[SIDS["TEMP"]][50] = 12.0
    assert alarms(w) == []


def test_exactly_min_persistence_alarms_and_times_are_right():
    w = world()
    w.readings[SIDS["TEMP"]][50] = 8.01
    w.readings[SIDS["TEMP"]][51] = 9.5
    (a,) = alarms(w)
    assert a["alarm_type"] == "TEMP_HIGH" and a["peak_value"] == 9.5 and a["threshold_value"] == 8.0
    assert a["_start"] == w.clock.epoch(50) and a["_end"] == w.clock.epoch(52)
    assert a["_open"] == w.clock.epoch(51)          # opens on the 2nd consecutive breaching reading
    assert a["severity"] == "WARNING"


def test_low_breach_and_critical_by_margin():
    w = world()
    for i in range(30, 33):
        w.readings[SIDS["TEMP2"]][i] = -2.0         # 4 C below the lower limit
    (a,) = alarms(w)
    assert a["alarm_type"] == "TEMP_LOW" and a["severity"] == "CRITICAL" and a["sensor_id"] == SIDS["TEMP2"]


def test_critical_by_duration():
    w = world()
    for i in range(30, 38):                          # 8 readings = 120 min, only 0.5 C over
        w.readings[SIDS["TEMP"]][i] = 8.5
    (a,) = alarms(w)
    assert a["severity"] == "CRITICAL"


def test_hysteresis_merges_runs_separated_by_one_clean_reading():
    w = world()
    for i in (40, 41, 43, 44):
        w.readings[SIDS["TEMP"]][i] = 9.0
    (a,) = alarms(w)
    assert a["_start"] == w.clock.epoch(40) and a["_end"] == w.clock.epoch(45)


def test_two_clean_readings_clear_the_alarm():
    w = world()
    for i in (40, 41, 44, 45):
        w.readings[SIDS["TEMP"]][i] = 9.0
    assert len(alarms(w)) == 2


def test_humidity_alarm():
    w = world()
    for i in (60, 61, 62):
        w.readings[SIDS["HUM"]][i] = 85.0
    (a,) = alarms(w)
    assert a["alarm_type"] == "HUMIDITY_HIGH" and a["severity"] == "CRITICAL" and a["threshold_value"] == 70.0


def test_occupancy_alarm_on_first_reading_over_limit_but_not_at_limit():
    w = world()
    w.readings[SIDS["OCC"]][10] = 8                  # at limit
    w.readings[SIDS["OCC"]][20] = 9                  # above limit
    (a,) = alarms(w)
    assert a["alarm_type"] == "OCCUPANCY_LIMIT" and a["_open"] == w.clock.epoch(20)


def test_door_open_longer_than_limit_alarms_but_equal_does_not():
    start = make_config("starter", days=5).start_epoch
    doors = [{"zone_id": Z, "sensor_id": SIDS["DOOR"], "duration_s": 300, "_open": start + 1000, "_close": start + 1300},
             {"zone_id": Z, "sensor_id": SIDS["DOOR"], "duration_s": 301, "_open": start + 5000, "_close": start + 5301},
             {"zone_id": Z, "sensor_id": SIDS["DOOR"], "duration_s": 950, "_open": start + 9000, "_close": start + 9950}]
    a = alarms(world(doors=doors))
    assert [x["alarm_type"] for x in a] == ["DOOR_OPEN_TOO_LONG"] * 2
    assert a[0]["severity"] == "WARNING" and a[1]["severity"] == "CRITICAL"     # 950 >= 3 x 300
    assert a[0]["_open"] == start + 5000 + 300                                   # opens when the limit is crossed


def test_gap_of_two_is_recorded_but_does_not_alarm_gap_of_three_does():
    w = world()
    for i in (10, 11):
        w.readings[SIDS["HUM"]][i] = None
    for i in (30, 31, 32):
        w.readings[SIDS["OCC"]][i] = None
    a = alarms(w)
    gaps = {g["sensor_id"]: g for g in w.tables["sensor_gap"]}
    assert gaps[SIDS["HUM"]]["missed_readings"] == 2 and gaps[SIDS["HUM"]]["alarm_raised"] is False
    assert gaps[SIDS["OCC"]]["missed_readings"] == 3 and gaps[SIDS["OCC"]]["alarm_raised"] is True
    assert [x["alarm_type"] for x in a] == ["SENSOR_GAP"] and a[0]["sensor_id"] == SIDS["OCC"]


def test_missing_data_does_not_count_as_a_breach_or_as_normal_alarm():
    w = world()
    for i in range(40, 48):
        w.readings[SIDS["TEMP"]][i] = None
        w.readings[SIDS["TEMP2"]][i] = None
    a = alarms(w)
    assert {x["alarm_type"] for x in a} == {"SENSOR_GAP"} and len(a) == 2       # explicit gap alarms, no TEMP alarm


def test_suppressed_gap_window_models_the_defect_edge_case():
    w = world()
    for sid in (SIDS["TEMP"], SIDS["TEMP2"]):
        for i in range(40, 48):
            w.readings[sid][i] = None
    w.plans["hidden_gaps"] = {Z: (40, 48)}
    assert alarms(w) == [] and w.tables["sensor_gap"] == []


def test_drift_between_redundant_sensors_is_detected_with_culprit():
    w = world(days=6)
    n = w.cfg.n_steps
    for i in range(96, n):
        w.readings[SIDS["TEMP2"]][i] = 6.4           # +1.4 C vs TEMP-01, still inside the band
    a = alarms(w)
    drift = [x for x in a if x["alarm_type"] == "SENSOR_DRIFT"]
    assert len(drift) == 1 and drift[0]["sensor_id"] == SIDS["TEMP2"] and drift[0]["peak_value"] == 1.4
    assert drift[0]["_start"] == w.cfg.start_epoch + 86400


def test_small_disagreement_is_not_drift():
    w = world(days=6)
    for i in range(w.cfg.n_steps):
        w.readings[SIDS["TEMP2"]][i] = 5.8
    assert alarms(w) == []
