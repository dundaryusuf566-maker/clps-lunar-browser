"""Forecast where and when an upcoming CLPS mission can land, and register it.

    python scripts/build_forecast.py --spice                 # Griffin-1: time + region (~25 min on 8 cores)
    python scripts/build_forecast.py --spice --skip-sweep    # re-analyse an existing sweep
    python scripts/build_forecast.py --spice --no-region     # time forecast only

Needs the LOLA terrain (scripts/download_terrain.py, scripts/build_horizons.py).

1. When: one TLI per day over the announced period, 4-7 day transits, 80-100 deg
   orbits, landing rule and loiter limit exactly as tested on IM-1 and IM-2, plus
   the operator's announced sunlight after touchdown. Resumable sweep in
   data/cache/forecast_<mission>_<ephemeris>.csv.
2. Where: a grid over the target region; for every point the terrain horizon,
   landing slots, sunlight, Earth visibility and slope (engine/forecast/region.py).
3. Registration: web/public/data/forecast.json gets the UTC time, the engine
   version, the git commit if any, and a SHA-256 of the forecast content.
   Commit and push that file before the mission flies: the commit is the public,
   dated record that the forecast came first.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_transfers import read_rows, run_sweep  # noqa: E402

from engine import __version__  # noqa: E402
from engine.core.time import tdb_to_utc, utc_to_tdb  # noqa: E402
from engine.database.webexport import dump  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.forecast import (  # noqa: E402
    REGION_RULES, RegionGrid, forecast_constraints, forecast_jobs, get_upcoming, rank, region_metrics, time_forecast,
)
from engine.forecast.timing import jobs_span  # noqa: E402
from engine.surface.terrain import PolarGrid  # noqa: E402
from engine.validation.illumination import sun_directions_fixed  # noqa: E402

CACHE = ROOT / "data" / "cache"
DEM_PATH = ROOT / "data" / "terrain" / "ldem_75s_120m.img"
DAY = 86_400.0
# Map annotations only (not scored).
LANDMARKS = [
    ("Mons Mouton (feature centre)", -84.6, 31.0, "https://en.wikipedia.org/wiki/Mons_Mouton"),
    ("Nobile crater centre", -85.28, 53.27, "https://en.wikipedia.org/wiki/Nobile_(crater)"),
]

_W: dict = {}


def _init(dem_path, ts, sun, earth, period, min_daylight, rules):
    _W.update(dem=PolarGrid.load(dem_path), ts=ts, sun=sun, earth=earth, period=period, min_daylight=min_daylight,
              rules=rules)


def _point(p):
    return region_metrics(_W["dem"], p, _W["ts"], _W["sun"], _W["earth"], _W["period"], _W["min_daylight"], _W["rules"])


def _epoch(day: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(day).replace(tzinfo=timezone.utc))


def _utc(e: float | None) -> str | None:
    return None if e is None else tdb_to_utc(e).isoformat(timespec="minutes").replace("+00:00", "Z")


def calibration() -> list[dict]:
    """How far the browser's own pick landed from the real touchdown on flown missions."""
    path = ROOT / "web" / "public" / "data" / "validation.json"
    if not path.exists():
        return []
    v = json.loads(path.read_text())
    out = []
    for x in v.get("missions", []):
        on = x["scan"].get("on_launch_day") or {}
        miss = None
        if on.get("landing_utc"):
            ours = datetime.fromisoformat(on["landing_utc"].replace("Z", "+00:00"))
            real = datetime.fromisoformat(x["mission"]["landing_utc"].replace("Z", "+00:00"))
            miss = round((ours - real).total_seconds() / 86400, 4)
        out.append({"mission": x["mission"]["name"], "site": x["mission"]["site_name"], "miss_days": miss,
                    "ephemeris": x.get("ephemeris")})
    return out


def git_commit() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=5)
        return out.stdout.strip() or None
    except Exception:
        return None


def git_code_dirty() -> bool | None:
    """True if code differs from that commit (generated data under web/ and data/ does not count):
    then git_commit would not name the code that made the forecast."""
    try:
        out = subprocess.run(["git", "status", "--porcelain", "--", ".", ":(exclude)web/public/data", ":(exclude)web/dist",
                              ":(exclude)data"], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        if out.returncode != 0:
            return None
        return bool(out.stdout.strip())
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", default="griffin-1")
    ap.add_argument("--spice", action="store_true", help="DE440 ephemeris (recommended)")
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--skip-sweep", action="store_true")
    ap.add_argument("--no-region", action="store_true")
    ap.add_argument("--dem", default=str(DEM_PATH))
    ap.add_argument("--quick", action="store_true", help="smoke test: 6 TLI days, coarse 10 km grid")
    ap.add_argument("--step-km", type=float, default=None, help="region grid spacing (default: the mission's)")
    ap.add_argument("--out", default=str(ROOT / "web" / "public" / "data" / "forecast.json"))
    args = ap.parse_args()

    tic = time.perf_counter()
    m = get_upcoming(args.mission)
    if args.quick:
        from dataclasses import replace
        from datetime import timedelta
        last = (datetime.fromisoformat(m.tli_first) + timedelta(days=5)).date().isoformat()
        m = replace(m, tli_last=last, region_step_km=10.0)
    if args.step_km:
        from dataclasses import replace
        m = replace(m, region_step_km=args.step_km)
    c = forecast_constraints(m)
    tag = "spice" if args.spice else "analytic"
    print(f"== {m.name}: forecast from {m.tli_first} to {m.tli_last} ({tag})")

    # 1. when -------------------------------------------------------------------------
    jobs = forecast_jobs(m)
    csv_path = CACHE / f"forecast_{m.id}_{tag}{'_quick' if args.quick else ''}.csv"
    if not args.skip_sweep:
        run_sweep(jobs, csv_path, args.workers, args.spice, quiet=True)
    if not csv_path.exists():
        print(f"{csv_path} missing: run without --skip-sweep")
        return 1
    cache = cached_for_window(args.spice, *jobs_span(jobs, c))
    t = time_forecast(cache, m, read_rows(csv_path), c, calibration())
    print(f"\nLaunch windows for {m.reference_name} (>= {m.min_daylight_days:g} days of sunlight after touchdown):")
    for w in t["windows"]:
        print(f"  TLI {w['first']} .. {w['last']} ({w['days']} d): touchdown {w['landing_first_utc'][:10]} .. "
              f"{w['landing_last_utc'][:10]}, sunlight {w['min_daylight_days']:.1f}-{w['max_daylight_days']:.1f} d")

    # 2. where ------------------------------------------------------------------------
    region = None
    if not args.no_region:
        dem_path = Path(args.dem)
        if not dem_path.exists():
            print(f"{dem_path} missing: run scripts/download_terrain.py first (or use --no-region)")
            return 1
        dem = PolarGrid.load(dem_path)
        grid = RegionGrid(m.region_center[0], m.region_center[1], m.region_half_km, m.region_step_km)
        pts = grid.points(dem)
        refs = [{"i": -1, "j": -1, "x_km": None, "y_km": None, "lat": m.reference_lat, "lon": m.reference_lon,
                 "label": m.reference_name}]
        lc0, sc0 = dem.pixel(*m.region_center)

        def xy(lat, lon):
            lc, sc = dem.pixel(lat, lon)
            return round(float(sc - sc0) * dem.map_scale_m / 1000, 3), round(float(lc - lc0) * dem.map_scale_m / 1000, 3)

        refs[0]["x_km"], refs[0]["y_km"] = xy(m.reference_lat, m.reference_lon)
        landmarks = [{"label": lab, "lat": la, "lon": lo, "source": src, **dict(zip(("x_km", "y_km"), xy(la, lo)))}
                     for lab, la, lo, src in LANDMARKS]
        px, py = dem.sample_offset - float(sc0), dem.line_offset - float(lc0)     # towards the pole
        pole = [round(px / np.hypot(px, py), 4), round(py / np.hypot(px, py), 4)]
        dem.close()

        p0, p1 = _epoch(m.landing_first), _epoch(m.landing_last)
        start, end = p0 - DAY, p1 + 30 * DAY
        ecache = cached_for_window(args.spice, start - DAY, end + DAY, step=3600.0)
        ts, sun = sun_directions_fixed(ecache, start, end)
        rot = ecache.rotation_many("MOON", ts)
        earth = np.einsum("nij,nj->ni", rot, ecache.position_many("EARTH", "MOON", ts))
        print(f"\nRegion scan: {len(pts)} points, {m.region_step_km:g} km apart, "
              f"{2 * m.region_half_km:g} x {2 * m.region_half_km:g} km, {args.workers} worker(s)")
        out_pts = []
        with Pool(args.workers, initializer=_init,
                  initargs=(str(dem_path), ts, sun, earth, (p0, p1), m.min_daylight_days,
                            {**REGION_RULES, "energy_window_days": m.energy_window_days})) as pool:
            for k, r in enumerate(pool.imap(_point, pts + refs, chunksize=8), 1):
                out_pts.append(r)
                if k % 200 == 0 or k == len(pts) + len(refs):
                    print(f"  {k}/{len(pts) + len(refs)}  ({time.perf_counter() - tic:.0f} s)", flush=True)
        grid_pts, ref_pts = out_pts[:len(pts)], out_pts[len(pts):]
        for p in grid_pts + ref_pts:
            for k in ("best_slot", "first_slot"):
                p[k] = _utc(p[k])
            p["runs"] = [[_utc(a), _utc(b)] for a, b in p["runs"]]
        top = rank(grid_pts)
        keep = {id(p) for p in top}
        for p in grid_pts:                      # landing-slot lists only where the page shows them
            if id(p) not in keep:
                p["runs"] = []
        region = {
            "grid": {"center_lat": m.region_center[0], "center_lon": m.region_center[1],
                     "half_km": m.region_half_km, "step_km": m.region_step_km,
                     "n": int(round(2 * m.region_half_km / m.region_step_km)) + 1,
                     "pole_direction": pole, "frame": "LOLA south polar stereographic: x to the image right, y down"},
            "landmarks": landmarks,
            "rules": {**REGION_RULES, "min_daylight_days": m.min_daylight_days, "energy_window_days": m.energy_window_days,
                      "dem": dem.name,
                      "slope_baseline_m": 2 * dem.map_scale_m},
            "period_utc": [m.landing_first, m.landing_last],
            "ranking": {"max_slope_deg": 10.0, "min_earth_after_pct": 50.0,
                        "order": "sunlight left by the best landing slot, then total slot time"},
            "points": grid_pts, "references": ref_pts, "top": top,
        }
        with_slot = sum(p["best_daylight_days"] is not None for p in grid_pts)
        print(f"  {with_slot}/{len(grid_pts)} points have a landing slot; top candidates:")
        for k, p in enumerate(top[:5], 1):
            print(f"   {k}. {abs(p['lat']):.3f} S {p['lon']:.3f} E: {p['best_daylight_days']:.1f} d of sunlight "
                  f"from {p['best_slot'][:10]}, slope {p['slope_deg']:.1f} deg, Earth {p['earth_after_best_pct']:.0f}%")
        for p in ref_pts:
            print(f"  reference {p['label']}: best slot {p['best_slot']}, {p['best_daylight_days']} d, slope {p['slope_deg']} deg")

    # 3. register -----------------------------------------------------------------------
    content = {"mission": m.to_dict(), "time": t, "region": region}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    meta = {"registered_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine_version": __version__, "ephemeris": tag, "git_commit": git_commit(),
            "git_code_dirty": git_code_dirty(), "sha256": digest,
            "how_to_verify": "sha256 of json.dumps({mission, time, region}, sort_keys=True, separators=(',', ':'))"}
    dump({"meta": meta, **content}, Path(args.out))
    print(f"\n-> {args.out}\n   registered {meta['registered_utc']}, sha256 {digest[:16]}...  "
          f"({(time.perf_counter() - tic) / 60:.1f} min)")
    if meta["git_code_dirty"]:
        print("WARNING: the code has uncommitted changes, so git_commit does not name the code that made this "
              "forecast. Commit the code, then run this again before registering (docs/KAYIT.md).")
    print("Push this file before launch and make the GitHub Release (docs/KAYIT.md): a commit's date is set by your\n"
          "own computer and proves nothing; the Release time and an archive.org copy are set by others.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
