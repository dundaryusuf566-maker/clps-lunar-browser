"""Sanity-check the SPICE setup and show how far the analytic model is from DE440.

    python scripts/check_spice.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris import AnalyticEphemeris  # noqa: E402


def main() -> int:
    try:
        from engine.ephemeris.spice_provider import SpiceEphemeris
        spice = SpiceEphemeris(kernel_dir=ROOT / "data" / "kernels")
    except ImportError:
        print("spiceypy is not installed:  pip install -e \".[spice]\"")
        return 1
    except FileNotFoundError as exc:
        print(f"{exc}\nRun:  python scripts/download_kernels.py")
        return 1

    analytic = AnalyticEphemeris()
    print("Moon relative to Earth, DE440 vs analytic model (2026)")
    print(f"  {'date (UTC)':<12}{'DE440 dist km':>15}{'analytic km':>14}{'angle diff':>12}")
    for month in range(1, 13, 2):
        t = utc_to_tdb(datetime(2026, month, 1, tzinfo=timezone.utc))
        rs = spice.position("MOON", "EARTH", t)
        ra = analytic.position("MOON", "EARTH", t)
        ang = np.degrees(np.arccos(np.clip(np.dot(rs, ra) / np.linalg.norm(rs) / np.linalg.norm(ra), -1, 1)))
        print(f"  2026-{month:02d}-01 {np.linalg.norm(rs):>15,.0f}{np.linalg.norm(ra):>14,.0f}{ang:>11.2f}°")

    t = utc_to_tdb(datetime(2026, 11, 14, tzinfo=timezone.utc))
    pole_s, pole_a = spice.pole("MOON", t), analytic.pole("MOON", t)
    print(f"\nLunar pole difference (MOON_PA vs IAU constant): "
          f"{np.degrees(np.arccos(np.clip(np.dot(pole_s, pole_a), -1, 1))):.3f}°")
    sun = spice.position("SUN", "EARTH", t)
    print(f"Earth-Sun distance on 2026-11-14: {np.linalg.norm(sun) / 149_597_870.7:.5f} AU")
    print("\nSPICE is working. Pass SpiceEphemeris() wherever AnalyticEphemeris() is used.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
