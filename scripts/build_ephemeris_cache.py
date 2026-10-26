"""Tabulate Sun/Moon ephemeris + lunar pole for a date window into a .npz file.

    python scripts/build_ephemeris_cache.py --spice --start 2025-11-01 --end 2026-12-31
    python scripts/sweep_transfers.py --ephem-cache data/cache/ephem_spice_2025-11-01_2026-12-31.npz ...

The .npz holds DE440-quality data (~1-2 MB per year at the default 1 h step) and
works on machines without spiceypy or the kernels: share it with the team.
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris import CachedEphemeris  # noqa: E402
from engine.ephemeris.factory import base_ephemeris  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", required=True, help="UTC date, YYYY-MM-DD")
    ap.add_argument("--end", required=True, help="UTC date, YYYY-MM-DD")
    ap.add_argument("--step", type=float, default=3600.0, help="sample spacing, s (default 1 h)")
    ap.add_argument("--spice", action="store_true", help="tabulate DE440 via SPICE (else the analytic model)")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    base = base_ephemeris(args.spice)
    t0 = utc_to_tdb(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc))
    t1 = utc_to_tdb(datetime.fromisoformat(args.end).replace(tzinfo=timezone.utc))
    tic = time.perf_counter()
    cache = CachedEphemeris.build(base, t0, t1, args.step)
    print(f"sampled {cache.n} epochs from {base.name} in {time.perf_counter() - tic:.1f} s")

    report = cache.validate_against(base)
    for key, vals in report.items():
        print(f"  {key:<12} " + "  ".join(f"{k}={v:.3g}" for k, v in vals.items()))

    out = Path(args.out or ROOT / "data" / "cache" / f"ephem_{base.name}_{args.start}_{args.end}.npz")
    cache.save(out)
    print(f"-> {out} ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
