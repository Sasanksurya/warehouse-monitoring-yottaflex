"""The validator must pass a clean dataset and catch deliberately corrupted ones (mutation tests)."""
import csv
import os

import pytest

from whmon.validate import validate


def mutate(root, table, fn):
    path = os.path.join(root, "csv", f"{table}.csv")
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.reader(f))
    fn(rows)
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f, lineterminator="\n").writerows(rows)


def failed(rep):
    return {c["name"] for c in rep.to_dict()["checks"] if c["status"] == "FAIL"}


def col(rows, name):
    return rows[0].index(name)


def test_clean_dataset_passes(starter):
    rep = validate(starter["out"])
    assert rep.errors == 0 and rep.to_dict()["summary"]["checks"] > 150


def test_duplicate_primary_key(copy_of_starter):
    mutate(copy_of_starter, "zone", lambda r: r.append(list(r[1])))
    assert "zone: primary key unique" in failed(validate(copy_of_starter))


def test_orphan_foreign_key(copy_of_starter):
    def f(rows):
        rows[1][col(rows, "zone_id")] = "ZONE-WH-999-999"
    mutate(copy_of_starter, "alarm", f)
    assert any(n.startswith("FK alarm.zone_id") for n in failed(validate(copy_of_starter)))


def test_invalid_enum(copy_of_starter):
    def f(rows):
        rows[1][col(rows, "severity")] = "PANIC"
    mutate(copy_of_starter, "alarm", f)
    assert "alarm: enum values allowed" in failed(validate(copy_of_starter))


def test_date_ordering_violation(copy_of_starter):
    def f(rows):
        i, j = col(rows, "opened_at"), col(rows, "closed_at")
        rows[1][i], rows[1][j] = rows[1][j], rows[1][i]
    mutate(copy_of_starter, "door_event", f)
    assert "door_event: closed_at > opened_at" in failed(validate(copy_of_starter))


def test_arithmetic_reconciliation_door_duration(copy_of_starter):
    def f(rows):
        rows[1][col(rows, "duration_s")] = "99999"
    mutate(copy_of_starter, "door_event", f)
    assert "door_event: duration_s == closed_at - opened_at" in failed(validate(copy_of_starter))


def test_threshold_consistency(copy_of_starter):
    def f(rows):
        rows[1][col(rows, "threshold_value")] = "123.45"
    mutate(copy_of_starter, "alarm", f)
    assert "alarm: threshold_value equals the zone limit for its type" in failed(validate(copy_of_starter))


def test_lifecycle_transition(copy_of_starter):
    def f(rows):
        i = col(rows, "to_status")
        rows[2][i] = "CLOSED" if rows[2][i] != "CLOSED" else "OPEN"
    mutate(copy_of_starter, "alarm_state_history", f)
    assert "alarm_state_history: transitions follow the allowed lifecycle" in failed(validate(copy_of_starter))


def test_reading_id_must_match_sensor_and_timestamp(copy_of_starter):
    def f(rows):
        rows[5][col(rows, "reading_id")] = "RDG-wrong"
    mutate(copy_of_starter, "sensor_reading", f)
    assert "sensor_reading: reading_id == RDG-<sensor_id>-<timestamp>" in failed(validate(copy_of_starter))


def test_duplicate_reading_timestamp(copy_of_starter):
    def f(rows):
        rows.insert(3, list(rows[2]))
    mutate(copy_of_starter, "sensor_reading", f)
    assert "sensor_reading: strictly increasing per sensor (no duplicate timestamps)" in failed(validate(copy_of_starter))


def test_remediation_must_link_to_inventory_impact(copy_of_starter):
    def f(rows):
        i = col(rows, "lot_id")
        for r in rows[1:]:
            if r[i]:
                r[i] = "LOT-2026-000001"
                break
    mutate(copy_of_starter, "remediation", f)
    bad = failed(validate(copy_of_starter))
    assert any("remediation" in n for n in bad)


def test_missing_required_value(copy_of_starter):
    def f(rows):
        rows[1][col(rows, "zone_name")] = ""
    mutate(copy_of_starter, "zone", f)
    assert "zone: required fields present" in failed(validate(copy_of_starter))
