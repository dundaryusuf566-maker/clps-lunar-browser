"""One place that turns command-line choices into an EphemerisProvider."""

from __future__ import annotations

from pathlib import Path

from .analytic import AnalyticEphemeris
from .base import EphemerisProvider
from .cached import CachedEphemeris

ROOT = Path(__file__).resolve().parents[2]
KERNEL_DIR = ROOT / "data" / "kernels"


def base_ephemeris(use_spice: bool) -> EphemerisProvider:
    if use_spice:
        from .spice_provider import SpiceEphemeris
        return SpiceEphemeris(kernel_dir=KERNEL_DIR)
    return AnalyticEphemeris()


def cached_for_window(use_spice: bool, start: float, end: float, step: float = 3600.0,
                      cache_path: str | Path | None = None) -> CachedEphemeris:
    """Load `cache_path` if given (and check it covers the window), else build a
    cache from the base provider for [start, end]."""
    if cache_path is not None:
        cache = CachedEphemeris.load(cache_path)
        if not cache.covers(start, end):
            from ..core.time import tdb_to_utc

            def fmt(t):
                return f"{tdb_to_utc(t):%Y-%m-%d %H:%M}"
            raise ValueError(
                f"{cache_path} covers {fmt(cache.t0)} .. {fmt(cache.t1)} UTC but this run needs "
                f"{fmt(start)} .. {fmt(end)} UTC; rebuild it with scripts/build_ephemeris_cache.py"
            )
        return cache
    return CachedEphemeris.build(base_ephemeris(use_spice), start, end, step)
