"""Measure what the ephemeris cache buys: query latency, accuracy, transfer time.

    python scripts/benchmark_ephemeris.py            # analytic base
    python scripts/benchmark_ephemeris.py --spice    # DE440 base: the number that matters
"""

from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris import CachedEphemeris  # noqa: E402
from engine.ephemeris.factory import base_ephemeris  # noqa: E402
from engine.mission import TransferSpec, design_transfer  # noqa: E402


def _latency_us(fn, epochs) -> float:
    tic = time.perf_counter()
    for t in epochs:
        fn(t)
    return (time.perf_counter() - tic) / len(epochs) * 1e6


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--date", default="2026-01-10")
    ap.add_argument("--tof", type=float, default=5.0)
    args = ap.parse_args()

    base = base_ephemeris(args.spice)
    t_tli = utc_to_tdb(datetime.fromisoformat(args.date).replace(tzinfo=timezone.utc))
    tic = time.perf_counter()
    cache = CachedEphemeris.build(base, t_tli - 86_400, t_tli + (args.tof + 5) * 86_400)
    print(f"base: {base.name}   cache build: {time.perf_counter() - tic:.2f} s ({cache.n} samples)\n")

    epochs = np.random.default_rng(0).uniform(cache.t0, cache.t1, 5000)
    print(f"{'query':<22}{'base µs':>10}{'cached µs':>11}{'speed-up':>10}")
    for label, fb, fc in [
        ("Moon position", lambda t: base.position("MOON", "EARTH", t), lambda t: cache.position("MOON", "EARTH", t)),
        ("Sun from Moon", lambda t: base.position("SUN", "MOON", t), lambda t: cache.position("SUN", "MOON", t)),
        ("Moon state", lambda t: base.state("MOON", "EARTH", t), lambda t: cache.state("MOON", "EARTH", t)),
        ("Moon pole", lambda t: base.pole("MOON", t), lambda t: cache.pole("MOON", t)),
    ]:
        b, c = _latency_us(fb, epochs), _latency_us(fc, epochs)
        print(f"{label:<22}{b:>10.2f}{c:>11.2f}{b / c:>9.1f}x")

    print("\nInterpolation error vs base:")
    for key, vals in cache.validate_against(base).items():
        print(f"  {key:<12} " + "  ".join(f"{k}={v:.3g}" for k, v in vals.items()))

    spec = TransferSpec(t_tli, args.tof)
    print(f"\nDesigning one transfer ({args.date}, {args.tof} d) both ways...")
    results = {}
    for label, eph in [("base", base), ("cached", cache)]:
        tic = time.perf_counter()
        sol = design_transfer(eph, spec)
        results[label] = (time.perf_counter() - tic, sol.metrics["loi_dv_ms"], sol.converged)
        print(f"  {label:<7} {results[label][0]:6.1f} s   LOI {results[label][1]:.4f} m/s   converged={sol.converged}")
    (tb, lb, _), (tc, lc, _) = results["base"], results["cached"]
    print(f"\nTransfer speed-up {tb / tc:.1f}x, LOI difference {abs(lb - lc) * 1000:.2f} mm/s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
