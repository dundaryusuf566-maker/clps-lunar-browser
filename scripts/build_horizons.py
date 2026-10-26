"""Compute the LOLA terrain horizon of every polar site and check it against NASA.

    python scripts/download_terrain.py              # once, ~233 MB
    python scripts/build_horizons.py --spice        # masks + NASA illumination check (~2-5 min)
    python scripts/build_horizons.py --spice --fine # also compare with the 60 m map (needs download --fine)

1. For each site with a `horizon` entry (engine/surface/sites.py) the terrain
   horizon is computed from LDEM_75S_120M: every 0.5 deg of azimuth, out to
   250 km, with the Moon's curvature, for an observer 2 m above the surface
   (a lander's camera / solar panel). Saved to engine/surface/horizons/<name>.json;
   these small files are what the landing analysis uses, so the 116 MB map is
   not needed afterwards.
2. Independent check: the average solar illumination over an 18.6-year cycle,
   computed from our horizons and ephemeris, against NASA's map of the same
   quantity on the same grid (AVGVISIB_75S_120M, Mazarico et al. 2011), at a
   5 x 5 grid of pixels around each site (observer on the surface, as in NASA's
   map). Pass criteria are fixed in engine/validation/illumination.py.
3. --fine: the same horizons from the 60 m map, to show they do not hinge on
   the map resolution.

After this, re-run the landing analysis and the validation page:
    python scripts/build_database.py --preset year2026 --spice --skip-sweep
    python scripts/build_validation.py --spice --skip-sweep --tests
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.time import tdb_to_utc, utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface import SITES  # noqa: E402
from engine.surface.terrain import HORIZON_DIR, PolarGrid, compute_horizon  # noqa: E402
from engine.validation import illumination as ill  # noqa: E402

TERRAIN = ROOT / "data" / "terrain"
OBSERVER_M = 2.0
AZ_STEP = 0.5
MAX_DIST_KM = 250.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true", help="DE440 for the illumination check (recommended)")
    ap.add_argument("--dem", default=str(TERRAIN / "ldem_75s_120m.img"))
    ap.add_argument("--avg", default=str(TERRAIN / "avgvisib_75s_120m_201608.img"))
    ap.add_argument("--fine", action="store_true", help="compare with data/terrain/ldem_75s_60m.img")
    ap.add_argument("--no-check", action="store_true", help="masks only, skip the NASA comparison")
    ap.add_argument("--start", default="2005-01-01", help="start of the 18.6-year illumination average")
    args = ap.parse_args()

    tic = time.perf_counter()
    try:
        dem = PolarGrid.load(args.dem)
    except FileNotFoundError as exc:
        print(f"{exc}\nDownload the terrain first:  python scripts/download_terrain.py")
        return 1
    print(f"DEM {dem.name}: {dem.lines} x {dem.samples}, {dem.map_scale_m:.0f} m/pixel")

    # 1. horizon masks ------------------------------------------------------------------
    sites = [s for s in SITES if s.horizon]
    masks = {}
    for s in sites:
        if not dem.covers(s.lat_deg, s.lon_deg):
            print(f"  {s.id}: outside {dem.name}, skipped")
            continue
        m = compute_horizon(dem, s.lat_deg, s.lon_deg, site=s.horizon, observer_m=OBSERVER_M,
                            az_step_deg=AZ_STEP, max_dist_km=MAX_DIST_KM)
        path = m.save()
        masks[s.id] = m
        print(f"  {m.summary()}\n    -> {path.relative_to(ROOT)}")

    check = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "dem": dem.name,
             "observer_m": OBSERVER_M, "az_step_deg": AZ_STEP, "max_dist_km": MAX_DIST_KM,
             "tolerance": {"median_abs": ill.TOL_MEDIAN, "max_abs": ill.TOL_MAX},
             "sites": [], "resolution": None, "orientation_diagnostic": None, "pass": None}

    # 3. resolution sensitivity -----------------------------------------------------------
    if args.fine:
        fine_path = TERRAIN / "ldem_75s_60m.img"
        try:
            fine = PolarGrid.load(fine_path)
        except FileNotFoundError:
            print(f"{fine_path.name} not found: run  python scripts/download_terrain.py --fine")
            return 1
        check["resolution"] = {}
        print(f"\nResolution check: {dem.name} vs {fine.name}")
        for sid, m in masks.items():
            f = compute_horizon(fine, m.lat_deg, m.lon_deg, site=m.site, observer_m=OBSERVER_M,
                                az_step_deg=AZ_STEP, max_dist_km=MAX_DIST_KM)
            d = f.elev_deg - m.elev_deg
            check["resolution"][sid] = {"fine": fine.name, "rms_deg": round(float(np.sqrt(np.mean(d**2))), 3),
                                        "max_abs_deg": round(float(np.abs(d).max()), 3),
                                        "mean_deg": round(float(d.mean()), 3)}
            r = check["resolution"][sid]
            print(f"  {sid}: horizon differs by {r['rms_deg']:.3f} deg rms, {r['max_abs_deg']:.3f} deg max, "
                  f"{r['mean_deg']:+.3f} deg mean")

    # 2. NASA illumination check ------------------------------------------------------------
    if not args.no_check:
        try:
            avg = PolarGrid.load(args.avg)
        except FileNotFoundError as exc:
            print(f"{exc}\nDownload it with  python scripts/download_terrain.py  (or use --no-check)")
            return 1
        if (avg.lines, avg.samples, avg.map_scale_m) != (dem.lines, dem.samples, dem.map_scale_m):
            print(f"{avg.name} is not on the {dem.name} grid")
            return 1
        start = utc_to_tdb(datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc))
        end = start + ill.CYCLE_DAYS * ill.DAY
        print(f"\nIllumination check against {avg.name} (18.6 years from {args.start}, hourly)")
        cache = cached_for_window(args.spice, start - ill.DAY, end + ill.DAY, step=3600.0)
        _, dirs = ill.sun_directions_fixed(cache, start, end)
        check.update(ephemeris=cache.source, avg_map=avg.name, samples=int(len(dirs)),
                     span_utc=[f"{tdb_to_utc(start):%Y-%m-%d}", f"{tdb_to_utc(end):%Y-%m-%d}"])
        for s in sites:
            if s.id in masks:
                check["sites"].append(ill.compare_site(dem, avg, dirs, s.id, s.lat_deg, s.lon_deg))
        check["pass"] = bool(check["sites"]) and all(r["pass"] for r in check["sites"])

        if not check["pass"]:
            # Diagnose: would a mirrored / rotated grid fit better? (Reported, never applied.)
            print("\nCheck failed. Orientation diagnostic (median |diff| at the 9 central pixels):")
            diag = []
            for xs, ys in ((1.0, -1.0), (-1.0, -1.0), (1.0, 1.0), (-1.0, 1.0)):
                dem.x_sign, dem.y_sign = xs, ys
                meds = [ill.compare_site(dem, avg, dirs, r["site"], r["lat_deg"], r["lon_deg"], half=1,
                                         log=lambda *_: None)["median_abs_diff"] for r in check["sites"]]
                diag.append({"x_sign": xs, "y_sign": ys, "median_abs_diff": meds})
                tag = " (LOLA convention, used)" if (xs, ys) == (1.0, -1.0) else ""
                print(f"  x {xs:+.0f}, y {ys:+.0f}: {', '.join(f'{v:.3f}' for v in meds)}{tag}")
            dem.x_sign, dem.y_sign = 1.0, -1.0
            check["orientation_diagnostic"] = diag

    out = HORIZON_DIR / "_illumination_check.json"
    out.write_text(json.dumps(check, indent=1))
    print(f"\n-> {out.relative_to(ROOT)}  ({time.perf_counter() - tic:.0f} s)")
    if check["pass"] is False:
        print("The terrain does not reproduce NASA's illumination map: send this output before using the masks.")
        return 2
    print("Next:  python scripts/build_database.py --preset year2026 --spice --skip-sweep")
    print("       python scripts/build_validation.py --spice --skip-sweep --tests")
    return 0


if __name__ == "__main__":
    sys.exit(main())
