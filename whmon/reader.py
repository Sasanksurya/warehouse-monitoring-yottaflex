"""Reads an exported dataset directory back from disk (used by validator and evaluator, so both
work on the artefacts a reviewer would receive, not on in-memory objects)."""
from __future__ import annotations

import calendar
import csv
import json
import os
import time

_DAY = {}


def fast_epoch(s: str) -> int:
    """'YYYY-MM-DDTHH:MM:SSZ' -> epoch seconds, with a per-day cache (1M readings need this to be cheap)."""
    d = _DAY.get(s[:10])
    if d is None:
        d = _DAY[s[:10]] = calendar.timegm(time.strptime(s[:10], "%Y-%m-%d"))
    return d + int(s[11:13]) * 3600 + int(s[14:16]) * 60 + int(s[17:19])


def date_epoch(s: str) -> int:
    return fast_epoch(s + "T00:00:00Z")


def iter_csv(out_dir: str, table: str):
    with open(os.path.join(out_dir, "csv", f"{table}.csv"), newline="", encoding="utf-8") as f:
        yield from csv.DictReader(f)


def load(out_dir: str, table: str) -> list:
    return list(iter_csv(out_dir, table))


def load_truth(out_dir: str) -> list:
    with open(os.path.join(out_dir, "ground_truth", "ground_truth.json"), encoding="utf-8") as f:
        return json.load(f)


def load_manifest(out_dir: str) -> dict:
    with open(os.path.join(out_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)
