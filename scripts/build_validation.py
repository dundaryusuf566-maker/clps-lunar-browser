"""Build the validation page data: flown-mission retrodiction, NASA comparison, tests.

    python scripts/build_validation.py --spice                 # recommended (DE440)
    python scripts/build_validation.py --spice --tests         # also run the test suite
    python scripts/build_validation.py --skip-sweep            # re-analyse existing sweeps only

What it does
    1. IM-1 (Feb 2024, Malapert A) and IM-2 (Mar 2025, Mons Mouton):
       - designs the transfer with the real TLI epoch and transit time,
       - scans TLI dates around each launch (one per day, 4-7 day transits),
       - checks the real touchdown and the real launch windows against the
         browser's landing analysis (engine/validation/retrodiction.py).
       About 400 transfers; resumable, rows land in data/cache/retro_*.csv.
    2. Compares the Genova-window sweep (data/cache/genova.csv) with the NASA
       Ames reference figure, plus the dense January sweep (data/cache/jan_minimum.csv)
       if present. Make both once with
         python scripts/sweep_transfers.py --start 2025-12-07 --end 2026-03-31 --step 3 \
             --tofs 4 6 8 10 12 --families 1 --spice --out data/cache/genova.csv
         python scripts/sweep_transfers.py --start 2026-01-05 --end 2026-01-13 --step 1 \
             --tofs 4 4.5 5 5.5 6 6.5 7 --families 1 --spice --out data/cache/jan_minimum.csv
       Skipped if that file is missing; --nasa-csv points elsewhere.
    3. --tests runs tests/run_all.py and records the result.

Output: web/public/data/validation.json (the UI's Validation tab).
"""

from __future__ import annotations

import argparse
import csv
import json
import platform
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from multiprocessing import cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_transfers import read_rows, run_sweep  # noqa: E402

from engine import __version__  # noqa: E402
from engine.database.webexport import dump  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface.terrain import HORIZON_DIR, available_horizons  # noqa: E402
from engine.validation.missions import MISSIONS  # noqa: E402
from engine.validation.nasa_reference import compare  # noqa: E402
from engine.validation.retrodiction import (  # noqa: E402
    MISSION_CONSTRAINTS, mission_constraints, reconstruction_jobs, retrodict, scan_jobs, window_span,
)

# Days scanned around each launch: IM-1 covers its January and February windows; Blue Ghost 1 a week either side
# of its TLI (for reference: its launch was not tied to the Moon).
SCAN_SPAN = {"im-1": (45, 14), "im-2": (20, 15), "blue-ghost-1": (7, 7)}
CACHE = ROOT / "data" / "cache"


def run_tests() -> dict:
    tic = time.perf_counter()
    proc = subprocess.run([sys.executable, str(ROOT / "tests" / "run_all.py")], cwd=ROOT,
                          capture_output=True, text=True)
    text = proc.stdout + proc.stderr
    m = re.search(r"(\d+) passed, (\d+) failed", text)
    names = re.findall(r"^\s*(PASS|FAIL|SKIP)\s+(\S+)", text, re.M)
    groups: dict[str, dict] = {}
    for status, name in names:
        g = groups.setdefault(name.split("::")[0], {"pass": 0, "fail": 0, "skip": 0})
        g[status.lower()] += 1
    return {
        "passed": int(m.group(1)) if m else 0, "failed": int(m.group(2)) if m else -1,
        "skipped": sum(g["skip"] for g in groups.values()),
        "groups": groups, "seconds": round(time.perf_counter() - tic, 1),
        "python": platform.python_version(), "run_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true", help="DE440 ephemeris (recommended)")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--missions", nargs="+", default=[m.id for m in MISSIONS])
    ap.add_argument("--skip-sweep", action="store_true", help="only re-analyse the existing retro_*.csv files")
    ap.add_argument("--nasa-csv", default=str(CACHE / "genova.csv"))
    ap.add_argument("--nasa-dense-csv", default=str(CACHE / "jan_minimum.csv"),
                    help="dense sweep around the January minimum (used if the file exists)")
    ap.add_argument("--tests", action="store_true", help="run the test suite and include the result")
    ap.add_argument("--out", default=str(ROOT / "web" / "public" / "data" / "validation.json"))
    args = ap.parse_args()

    tic = time.perf_counter()
    out_path = Path(args.out)
    previous = json.loads(out_path.read_text()) if out_path.exists() else {}
    c = MISSION_CONSTRAINTS
    tag = "spice" if args.spice else "analytic"
    missions = []
    for m in MISSIONS:
        if m.id not in args.missions:
            continue
        print(f"\n== {m.name}")
        point_csv = CACHE / f"retro_{m.id}_{tag}_point.csv"
        scan_csv = CACHE / f"retro_{m.id}_{tag}_scan.csv"
        p_jobs = reconstruction_jobs(m)
        s_jobs = scan_jobs(m, *SCAN_SPAN[m.id])
        if not args.skip_sweep:
            run_sweep(p_jobs, point_csv, args.workers, args.spice, quiet=True)
            run_sweep(s_jobs, scan_csv, args.workers, args.spice, quiet=True)
        if not point_csv.exists() or not scan_csv.exists():
            print(f"  missing {point_csv.name} / {scan_csv.name}; run without --skip-sweep")
            return 1
        start, end = window_span(p_jobs + s_jobs, mission_constraints(m, c))
        cache = cached_for_window(args.spice, start, end)
        r = retrodict(cache, m, read_rows(point_csv), read_rows(scan_csv), c)
        for ch in r["checks"]:
            print(f"  {'PASS' if ch['pass'] else 'FAIL'}  {ch['label']}")
        missions.append(r)

    nasa = previous.get("nasa")
    nasa_csv = Path(args.nasa_csv)
    if nasa_csv.exists():
        dense_csv = Path(args.nasa_dense_csv) if args.nasa_dense_csv else None
        dense = read_rows(dense_csv) if dense_csv and dense_csv.exists() else None
        nasa = compare(read_rows(nasa_csv), dense)
        print(f"\n== NASA Ames comparison ({nasa_csv.name}, {nasa['count']} transfers, {nasa['ephemeris']})")
        print(f"  band {nasa['band_ms'][0]}-{nasa['band_ms'][1]} m/s vs NASA "
              f"{nasa['reference']['loi_min_ms']:.0f}-{nasa['reference']['loi_max_ms']:.0f}")
        for mm in nasa["minima"]:
            print(f"  {mm['month']}: ours {mm['our_date']} {mm['our_loi_dv_ms']} m/s, "
                  f"NASA {mm['nasa_date']} ~{mm['nasa_loi_dv_ms']:.0f} m/s ({mm['days_apart']:+d} d)")
    else:
        print(f"\n{nasa_csv} not found: NASA comparison kept from the previous file"
              if nasa else f"\n{nasa_csv} not found: no NASA comparison (see the sweep command in this script's help)")

    terrain = None
    check_file = HORIZON_DIR / "_illumination_check.json"
    if check_file.exists():
        terrain = json.loads(check_file.read_text())
        terrain["masks"] = available_horizons()
        print(f"\n== Terrain: LOLA {terrain['dem']} horizons for {', '.join(terrain['masks']) or 'no site'}")
        for r in terrain.get("sites", []):
            print(f"  {'PASS' if r['pass'] else 'FAIL'}  illumination vs NASA map at {r['site']}: "
                  f"median |diff| {r['median_abs_diff']:.3f}, max {r['max_abs_diff']:.3f}")
    else:
        print("\nNo terrain horizons yet (scripts/build_horizons.py): flat horizon everywhere")

    tests = run_tests() if args.tests else previous.get("tests")
    if args.tests:
        print(f"\n== Tests: {tests['passed']} passed, {tests['failed']} failed, {tests['skipped']} skipped")

    if not args.missions or len(missions) < len(MISSIONS):
        keep = {x["mission"]["id"]: x for x in previous.get("missions", [])}
        keep.update({x["mission"]["id"]: x for x in missions})
        missions = [keep[m.id] for m in MISSIONS if m.id in keep]
    dump({
        "meta": {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "engine_version": __version__, "ephemeris": tag},
        "missions": missions, "nasa": nasa, "terrain": terrain, "tests": tests,
    }, out_path)
    print(f"\n-> {out_path} ({(time.perf_counter() - tic) / 60:.1f} min)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
