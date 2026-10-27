"""Deterministic helpers: seeded RNG streams, timestamps, ID formatting, Poisson sampling."""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .config import Config, INTERVAL_S


def rng_for(cfg: Config, *parts: object) -> random.Random:
    """Independent, order-insensitive RNG stream per (seed, stage, key).
    String seeding in CPython uses SHA-512, so it is stable across processes and platforms."""
    return random.Random(f"{cfg.seed}/" + "/".join(str(p) for p in parts))


def iso(epoch: int) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(epoch))


def compact(epoch: int) -> str:
    return time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(epoch))


def iso_date(epoch: int) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(epoch))


def parse_iso(s: str) -> int:
    import calendar
    return calendar.timegm(time.strptime(s, "%Y-%m-%dT%H:%M:%SZ"))


def poisson(rng: random.Random, lam: float) -> int:
    if lam <= 0:
        return 0
    if lam > 30:  # normal approximation, never needed at our rates but keeps it safe
        return max(0, int(round(rng.gauss(lam, math.sqrt(lam)))))
    limit, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def weighted_choice(rng: random.Random, pairs):
    total = sum(w for _, w in pairs)
    x = rng.random() * total
    acc = 0.0
    for item, w in pairs:
        acc += w
        if x < acc:
            return item
    return pairs[-1][0]


class Clock:
    """Maps reading-step index <-> epoch with cached string forms."""

    def __init__(self, cfg: Config):
        self.start = cfg.start_epoch
        self.n = cfg.n_steps
        self._iso = [iso(self.start + i * INTERVAL_S) for i in range(self.n + 1)]
        self._cmp = [compact(self.start + i * INTERVAL_S) for i in range(self.n + 1)]

    def epoch(self, i: int) -> int:
        return self.start + i * INTERVAL_S

    def iso(self, i: int) -> str:
        return self._iso[i]

    def compact(self, i: int) -> str:
        return self._cmp[i]


def wh_id(n: int) -> str:
    return f"WH-{n:03d}"


def zone_id(wh: str, n: int) -> str:
    return f"ZONE-{wh}-{n:03d}"


def sensor_id(zone: str, stype: str, n: int = 1) -> str:
    return f"SNS-{zone}-{stype}-{n:02d}"


def reading_id(sensor: str, compact_ts: str) -> str:
    return f"RDG-{sensor}-{compact_ts}"


def lot_id(year: int, n: int) -> str:
    return f"LOT-{year}-{n:06d}"


@dataclass
class World:
    """Mutable container passed through the pipeline stages."""
    cfg: Config
    clock: Clock
    tables: dict = field(default_factory=dict)       # table name -> list[dict]
    readings: dict = field(default_factory=dict)     # sensor_id -> list[float|int|None] (length n_steps)
    truth: list = field(default_factory=list)        # ground-truth rows (kept apart from input tables)
    plans: dict = field(default_factory=dict)        # side-channel info for later stages (never exported as input)

    def add_truth(self, issue_type: str, entity_type: str, entity_id: str, *, zone_id="", sensor_id="",
                  window_start="", window_end="", expected_decision="", expected_alarm_types="",
                  linked_entities="", details=None):
        import json
        self.truth.append({
            "issue_type": issue_type, "entity_type": entity_type, "entity_id": entity_id,
            "zone_id": zone_id, "sensor_id": sensor_id, "window_start": window_start,
            "window_end": window_end, "expected_decision": expected_decision,
            "expected_alarm_types": expected_alarm_types, "linked_entities": linked_entities,
            "details": json.dumps(details or {}, sort_keys=True, separators=(",", ":")),
        })
