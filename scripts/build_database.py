"""Build the whole transfer database in one command: sweep -> landing analysis -> web export.

    python scripts/build_database.py --preset quick --spice        # ~90 transfers, a few minutes
    python scripts/build_database.py --preset genova --spice       # Dec 2025 - Mar 2026, NASA comparison
    python scripts/build_database.py --preset year2026 --spice     # all of 2026, both approaches (~1830)

The sweep part is resumable: run the same command again after an interruption
and it continues where it stopped. Results land in data/cache/<preset>.csv and
web/public/data/ (what the UI shows).

Presets
    quick      2026-01-01 .. 2026-01-31, every 3 days, 4/5/6/8 d transits, both approaches
    genova     2025-12-07 .. 2026-03-31, every 3 days, 4/6/8/10/12 d, south approach (as in Genova et al.)
    year2026   2026-01-01 .. 2026-12-31, every 2 days, 4/5/6/8/10 d, both approaches
"""

from __future__ import annotations

import argparse
import sys
import time
from multiprocessing import cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_transfers import build_jobs, run_sweep  # noqa: E402

from engine.database import export_dataset, export_window  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface import LandingConstraints  # noqa: E402

PRESETS = {
    "quick": dict(start="2026-01-01", end="2026-01-31", step=3, tofs=[4, 5, 6, 8], families=[1, -1], trajectories="all"),
    "genova": dict(start="2025-12-07", end="2026-03-31", step=3, tofs=[4, 6, 8, 10, 12], families=[1], trajectories="all"),
    "year2026": dict(start="2026-01-01", end="2026-12-31", step=2, tofs=[4, 5, 6, 8, 10], families=[1, -1],
                     trajectories="best"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--preset", choices=sorted(PRESETS), default="quick")
    ap.add_argument("--spice", action="store_true", help="DE440 ephemeris (recommended)")
    ap.add_argument("--ephem-cache", default=None, help="saved CachedEphemeris .npz instead of SPICE")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--trajectories", choices=["all", "best", "none"], default=None,
                    help="override the preset's choice of exported 3D paths")
    ap.add_argument("--skip-sweep", action="store_true", help="only redo landing analysis + export")
    ap.add_argument("--max-wait", type=float, default=30.0)
    ap.add_argument("--plane-budget", type=float, default=150.0)
    ap.add_argument("--csv", default=None, help="sweep CSV path (default data/cache/<preset>.csv)")
    ap.add_argument("--out", default=str(ROOT / "web" / "public" / "data"))
    args = ap.parse_args()

    p = PRESETS[args.preset]
    csv_path = Path(args.csv or ROOT / "data" / "cache" / f"{args.preset}.csv")
    tic = time.perf_counter()
    if not args.skip_sweep:
        print(f"[1/2] Sweep: preset '{args.preset}'")
        jobs = build_jobs(p["start"], p["end"], p["step"], p["tofs"], p["families"])
        run_sweep(jobs, csv_path, args.workers, args.spice, args.ephem_cache, quiet=len(jobs) > 200)
    elif not csv_path.exists():
        print(f"{csv_path} does not exist; run without --skip-sweep first")
        return 1

    print("[2/2] Landing analysis and web export")
    c = LandingConstraints(max_wait_days=args.max_wait, max_plane_change_ms=args.plane_budget)
    start, end = export_window(csv_path, c)
    cache = cached_for_window(args.spice, start, end, cache_path=args.ephem_cache)
    export_dataset(csv_path, args.out, cache, args.trajectories or p["trajectories"], c)
    print(f"\nDone in {(time.perf_counter() - tic) / 60:.1f} min. Start the UI with:  python -m api.server")
    return 0


if __name__ == "__main__":
    sys.exit(main())
