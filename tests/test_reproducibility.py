import json

from whmon.config import make_config
from whmon.export import export_all
from whmon.pipeline import build_dataset


def run(tmp, seed, name):
    out = str(tmp / name)
    w = build_dataset(make_config("starter", seed=seed))
    m, _ = export_all(w, out, ("csv", "json", "sql"), "test")
    return m


def test_same_seed_gives_identical_files(tmp_path):
    a, b = run(tmp_path, 20261022, "a"), run(tmp_path, 20261022, "b")
    assert a["row_counts"] == b["row_counts"]
    assert a["files"] == b["files"]                      # sizes and SHA-256 of every file, including json/sql and ground truth


def test_different_seed_changes_the_data(tmp_path):
    a, b = run(tmp_path, 20261022, "a"), run(tmp_path, 7, "b")
    assert a["files"]["csv/sensor_reading.csv"]["sha256"] != b["files"]["csv/sensor_reading.csv"]["sha256"]


def test_manifest_records_seed_and_command(starter):
    m = starter["manifest"]
    assert m["seed"] == 20261022 and m["generator_command"] and m["files"]["csv/zone.csv"]["sha256"]
