"""Demo: design one Earth -> Moon transfer (TLI -> LOI) and print the details.

    python examples/02_tli_to_loi.py
    python examples/02_tli_to_loi.py --date 2026-02-10 --tof 6 --lunar-inc 60 --family -1
    python examples/02_tli_to_loi.py --spice          # DE440 ephemeris (after download_kernels.py)
    python examples/02_tli_to_loi.py --ephem-cache data/cache/ephem_....npz
"""

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import base_ephemeris, cached_for_window  # noqa: E402
from engine.mission import TransferSpec, design_transfer  # noqa: E402
from engine.propagators import propagate  # noqa: E402
from engine.validation import force_budget, format_budget  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default="2026-01-11", help="TLI date (UTC, YYYY-MM-DD[THH:MM])")
    ap.add_argument("--tof", type=float, default=5.0, help="TLI -> periselene, days")
    ap.add_argument("--lunar-inc", type=float, default=90.0, help="target inclination w.r.t. lunar equator, deg")
    ap.add_argument("--periselene", type=float, default=100.0, help="periselene altitude, km")
    ap.add_argument("--family", type=int, default=1, choices=[1, -1])
    ap.add_argument("--spice", action="store_true", help="use SPICE/DE440 instead of the analytic ephemeris")
    ap.add_argument("--ephem-cache", default=None, help="saved CachedEphemeris .npz")
    ap.add_argument("--no-cache", action="store_true", help="query the base ephemeris directly (slow)")
    args = ap.parse_args()

    date = datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc)
    t_tli = utc_to_tdb(date)
    if args.no_cache:
        eph = base_ephemeris(args.spice)
    else:
        eph = cached_for_window(args.spice, t_tli - 86_400, t_tli + (args.tof + 5) * 86_400,
                                cache_path=args.ephem_cache)
    spec = TransferSpec(t_tli, args.tof, periselene_alt_km=args.periselene,
                        lunar_inc_deg=args.lunar_inc, family=args.family)
    print(f"Ephemeris: {eph.name}\n")
    t0 = time.perf_counter()
    sol = design_transfer(eph, spec, verbose=True)
    print(f"\nsolved in {time.perf_counter() - t0:.1f} s\n")
    print(sol.stage_a.summary())
    if sol.stage_b:
        print(sol.stage_b.summary())
    print("\n" + sol.summary())
    print(f"  parking orbit: {spec.parking_alt_km:.0f} km, inc {sol.metrics['parking_inc_deg']:.2f}°, "
          f"RAAN {sol.metrics['parking_raan_deg']:.2f}°")

    for name, traj in sol.segments.items():
        # segments are stored without dense output; re-propagate to sample them
        print(f"\nForce budget, {name}-centred segment ({(traj.epochs[-1] - traj.epochs[0]) / 86400:.2f} d):")
        tr = propagate(traj.dynamics, traj.initial, traj.epochs[-1] - traj.epochs[0])
        print(format_budget(force_budget(tr)))


if __name__ == "__main__":
    main()
