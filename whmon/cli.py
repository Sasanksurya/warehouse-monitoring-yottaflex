"""Command line interface:  python -m whmon <generate|validate|evaluate|reproduce> ..."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
import time

from .config import SCALES, DEFAULT_SEED, make_config


def _cfg(a):
    over = {k: getattr(a, k) for k in ("warehouses", "zones_per_warehouse", "days", "lots") if getattr(a, k, None) is not None}
    return make_config(a.scale, a.seed, **over)


def _generate(a, out=None, quiet=False):
    from .pipeline import build_dataset
    from .export import export_all
    out = out or a.out
    cfg = _cfg(a)
    t0 = time.time()
    if a.cmd == "generate":
        command = "python -m whmon generate " + " ".join(sys.argv[2:])
    else:
        command = f"python -m whmon generate --scale {a.scale} --seed {a.seed}"
    w = build_dataset(cfg)
    t1 = time.time()
    manifest, fk_bad = export_all(w, out, tuple(x for x in a.formats.split(",") if x), command)
    if not quiet:
        c = manifest["row_counts"]
        print(f"[generate] seed={cfg.seed} scale={cfg.scale.name} build={t1 - t0:.1f}s export={time.time() - t1:.1f}s -> {out}")
        print("[generate] rows: " + ", ".join(f"{k}={v:,}" for k, v in c.items()) + f", ground_truth={manifest['ground_truth_rows']}")
        if fk_bad is not None:
            print(f"[generate] SQLite PRAGMA foreign_key_check violations: {fk_bad}")
    return manifest


def _validate(out, quiet=False):
    from .validate import validate, write_reports
    t0 = time.time()
    rep = validate(out)
    write_reports(rep, out)
    s = rep.to_dict()["summary"]
    if not quiet:
        print(f"[validate] {s['passed']} passed, {s['failed']} failed of {s['checks']} checks "
              f"({s['rows_checked']:,} assertions, {time.time() - t0:.1f}s) -> {out}/reports/validation_summary.md")
    return rep.errors


def _evaluate(out, quiet=False):
    from .evaluate import evaluate, write_reports
    t0 = time.time()
    res = evaluate(out)
    write_reports(res, out)
    if not quiet:
        e, a = res["edge_case_detection"], res["alarm_quality"]
        print(f"[evaluate] {time.time() - t0:.1f}s -> {out}/reports/evaluation_report.md")
        for k, v in e.items():
            print(f"  edge case {k:34s} precision={v['precision']} recall={v['recall']}")
        print(f"  alarms={a['alarms_total']} false_alarm_rate={a['false_alarm_rate']} categories={a['alarm_categories']}")
    return res


def _reproduce(a):
    """Regenerate twice with the same seed and compare row counts and SHA-256 checksums of every file."""
    work = a.workdir or tempfile.mkdtemp(prefix="whmon_repro_")
    runs = []
    for i in (1, 2):
        d = os.path.join(work, f"run{i}")
        shutil.rmtree(d, ignore_errors=True)
        runs.append(_generate(a, out=d, quiet=True))
        print(f"[reproduce] run {i} complete ({d})")
    m1, m2 = runs
    diffs = [f for f in sorted(set(m1["files"]) | set(m2["files"])) if m1["files"].get(f) != m2["files"].get(f)]
    report = {"seed": m1["seed"], "scale": m1["scale"], "identical_row_counts": m1["row_counts"] == m2["row_counts"],
              "identical_file_checksums": not diffs, "files_compared": len(m1["files"]), "differing_files": diffs,
              "row_counts": m1["row_counts"], "checksums_run1": {k: v["sha256"] for k, v in m1["files"].items()},
              "checksums_run2": {k: v["sha256"] for k, v in m2["files"].items()}}
    if a.check_other_seed:
        other = argparse.Namespace(**{**vars(a), "seed": a.seed + 1})
        m3 = _generate(other, out=os.path.join(work, "run_other_seed"), quiet=True)
        report["other_seed_differs"] = m3["files"]["csv/sensor_reading.csv"]["sha256"] != m1["files"]["csv/sensor_reading.csv"]["sha256"]
    with open(a.report, "w", encoding="utf-8", newline="\n") as f:
        json.dump(report, f, indent=1)
    ok = report["identical_row_counts"] and report["identical_file_checksums"]
    print(f"[reproduce] row counts identical: {report['identical_row_counts']}; all {report['files_compared']} file checksums identical: "
          f"{report['identical_file_checksums']} -> {a.report}")
    if not a.keep:
        shutil.rmtree(work, ignore_errors=True)
    return 0 if ok else 1


def main(argv=None):
    p = argparse.ArgumentParser(prog="whmon", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--scale", choices=sorted(SCALES), default="full")
        sp.add_argument("--seed", type=int, default=DEFAULT_SEED)
        sp.add_argument("--warehouses", type=int)
        sp.add_argument("--zones-per-warehouse", dest="zones_per_warehouse", type=int)
        sp.add_argument("--days", type=int)
        sp.add_argument("--lots", type=int)
        sp.add_argument("--formats", default="csv", help="comma list from: csv (always written), json, sql, sqlite")

    g = sub.add_parser("generate", help="generate dataset, then validate and evaluate it")
    common(g)
    g.add_argument("--out", default="data/full")
    g.add_argument("--no-checks", action="store_true", help="skip validation and evaluation")
    v = sub.add_parser("validate", help="integrity validation of an existing dataset directory")
    v.add_argument("--data", required=True)
    e = sub.add_parser("evaluate", help="score detectors and alarms against ground truth")
    e.add_argument("--data", required=True)
    r = sub.add_parser("reproduce", help="regenerate twice with the same seed and compare checksums")
    common(r)
    r.add_argument("--workdir")
    r.add_argument("--keep", action="store_true")
    r.add_argument("--report", default="reproducibility_report.json")
    r.add_argument("--check-other-seed", action="store_true")
    a = p.parse_args(argv)

    if a.cmd == "generate":
        _generate(a)
        if a.no_checks:
            return 0
        errors = _validate(a.out)
        _evaluate(a.out)
        return 1 if errors else 0
    if a.cmd == "validate":
        return 1 if _validate(a.data) else 0
    if a.cmd == "evaluate":
        _evaluate(a.data)
        return 0
    return _reproduce(a)


if __name__ == "__main__":
    sys.exit(main())
