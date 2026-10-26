"""Export a sweep CSV for the web UI (transfers, landing analysis, 3D paths).

    python scripts/export_web_data.py data/cache/transfers.csv --spice
    python scripts/export_web_data.py data/cache/transfers.csv --ephem-cache data/cache/ephem_....npz
    python scripts/export_web_data.py data/cache/year2026.csv --spice --trajectories best

Writes into web/public/data/:
    transfers.json            one row per converged transfer + dataset metadata
    landings.json             landing opportunities per site and transfer, Sun elevation series
    trajectories/<id>.json    Earth- and Moon-centred paths for the 3D view

--trajectories: all (default), best (cheapest per TLI date and family) or none.
Paths that are not exported are computed on demand by the API server.

Trajectories are re-propagated from the solved controls stored in the CSV, so
use the same ephemeris the sweep used (the CSV's `ephemeris` column says which).
Most people run scripts/build_database.py, which calls this after the sweep.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.database import export_dataset, export_window  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface import LandingConstraints  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("csv", help="sweep output from scripts/sweep_transfers.py")
    ap.add_argument("--spice", action="store_true", help="re-propagate with DE440 (match the sweep)")
    ap.add_argument("--ephem-cache", default=None)
    ap.add_argument("--trajectories", choices=["all", "best", "none"], default="all")
    ap.add_argument("--max-wait", type=float, default=30.0, help="days in lunar orbit before landing, at most")
    ap.add_argument("--plane-budget", type=float, default=150.0, help="plane-change budget for landing, m/s")
    ap.add_argument("--out", default=str(ROOT / "web" / "public" / "data"))
    args = ap.parse_args()

    if not Path(args.csv).exists():
        print(f"{args.csv} not found. Run scripts/build_database.py (or scripts/sweep_transfers.py) first.")
        return 1
    with open(args.csv, newline="") as fh:
        sweep_eph = next(csv.DictReader(fh), {}).get("ephemeris", "")
    if "spice" in sweep_eph and not (args.spice or args.ephem_cache):
        print(f"warning: the sweep used '{sweep_eph}'; add --spice so paths and landings use the same ephemeris")

    c = LandingConstraints(max_wait_days=args.max_wait, max_plane_change_ms=args.plane_budget)
    start, end = export_window(args.csv, c)
    cache = cached_for_window(args.spice, start, end, cache_path=args.ephem_cache)
    print(f"ephemeris: {cache.name}")
    export_dataset(args.csv, args.out, cache, args.trajectories, c)
    return 0


if __name__ == "__main__":
    sys.exit(main())
