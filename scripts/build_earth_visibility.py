"""Communication maps of a polar cap: where the Earth is above the LOLA terrain, and how often
together with the Sun, for the website's Anywhere page.

    python scripts/build_earth_visibility.py --spice                  (south, ~2-5 min)
    python scripts/build_earth_visibility.py --spice --pole north

Reads the horizon grid that build_horizon_grid.py wrote (web/public/data/horizon_grid_s.json and
its tiles) and, for every grid point and every hour of twelve months from 1 November 2026 (JPL
DE440 with --spice), applies the rules of engine/surface/earth_visibility.py. Writes

    web/public/data/earth_vis_s.json    layout, period, rules, checks A and B
    web/public/data/earth_vis_s.bin     uint8, [layer][row][col]: 0.5 percentage points per step,
                                        255 = no grid point; layers: earth, sun_earth, dsn

Pre-registered checks (criteria in engine/surface/earth_visibility.py, written before any map was
computed): A on a level sphere, and B, the grid against each point's own LOLA horizon at 300
random points, which needs the LOLA map (data/terrain, as build_horizon_grid.py). C, added after B
failed and written before it was evaluated: the uncertainty flag (the four grid points around a
point disagree), judged on the same points. All results go into the JSON and onto the page, pass or
fail; the map is written either way. Exit code 2 if a check fails, so that it is not missed.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402
from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface import earth_visibility as ev  # noqa: E402
from engine.surface.ground import DSN_MIN_ELEV_DEG  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
DEMS = {"south": ROOT / "data" / "terrain" / "ldem_75s_120m.img", "north": ROOT / "data" / "terrain" / "ldem_75n_120m.img"}
LAYERS = [("earth", "Earth above the terrain"), ("sun_earth", "Sun and Earth above the terrain together"),
          ("dsn", "Earth above the terrain and a DSN complex in view")]
STEP_PP = 0.5
MISSING = 255


def utc(s: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(s).replace(tzinfo=timezone.utc))


def plane_latlon(meta: dict, X, Y):
    """Inverse polar stereographic projection in the grid's own convention (horizonGrid.ts latLonOfPlane)."""
    sign = 1.0 if meta["pole"] == "north" else -1.0
    rho = np.hypot(X, Y)
    lat = sign * (90.0 - np.degrees(2 * np.arctan(rho / (2 * meta["radius_km"]))))
    return lat, np.degrees(np.arctan2(meta["x_sign"] * X, meta["y_sign"] * Y))


def check_b(meta: dict, H: np.ndarray, sky: ev.Sky, dem_path: Path, E: np.ndarray) -> tuple[dict, dict]:
    from engine.surface.horizon_grid import Pyramid, fast_horizon
    from engine.surface.terrain import PolarGrid
    dem = PolarGrid.load(dem_path)
    if dem.name != meta["dem"]:
        raise SystemExit(f"{dem_path} is {dem.name}, but the horizon grid was built from {meta['dem']}")
    pyr = Pyramid(dem)
    rng = np.random.default_rng(ev.CHECK_SEED)
    rho_max = 2 * meta["radius_km"] * np.tan(np.radians(90.0 - meta["min_abs_lat"]) / 2)
    d_grid, d_flat, d_se, pts, spread, tries = [], [], [], [], [], 0
    print(f"Check B at {ev.CHECK_POINTS} random points of the cap (seed {ev.CHECK_SEED}):")
    tic = time.perf_counter()
    while len(pts) < ev.CHECK_POINTS and tries < 20 * ev.CHECK_POINTS:
        tries += 1
        rr, th = rho_max * np.sqrt(rng.uniform()), rng.uniform(0, 2 * np.pi)
        x, y = rr * np.cos(th), rr * np.sin(th)
        la, lo = (float(v) for v in plane_latlon(meta, x, y))
        if abs(la) < meta["min_abs_lat"]:
            continue
        hg = ev.interp_grid(H, meta["x0_km"], meta["spacing_km"], x, y)
        if hg is None:
            continue
        try:
            own, _, _ = fast_horizon(pyr, la, lo, observer_m=meta["observer_m"], az_step_deg=meta["az_step_deg"])
        except ValueError:
            continue
        g = ev.shares(np.array([la]), np.array([lo]), hg[None, :], sky)
        o = ev.shares(np.array([la]), np.array([lo]), np.asarray(own, float)[None, :], sky)
        f = ev.shares(np.array([la]), np.array([lo]), None, sky)
        d_grid.append(float(g["earth"][0] - o["earth"][0]))
        d_flat.append(float(f["earth"][0] - o["earth"][0]))
        d_se.append(float(g["sun_earth"][0] - o["sun_earth"][0]))
        spread.append(ev.neighbour_spread(E, meta["x0_km"], meta["spacing_km"], x, y))
        pts.append([round(la, 8), round(lo, 8), round(float(o["earth"][0]), 2), round(float(g["earth"][0]), 2), round(float(f["earth"][0]), 2),
                    round(spread[-1], 2)])
        if len(pts) % 50 == 0:
            print(f"  {len(pts)}/{ev.CHECK_POINTS} ({time.perf_counter() - tic:.0f} s)", flush=True)
    dem.close()
    out = ev.judge_b(np.array(d_grid), np.array(d_flat))
    a = np.abs(np.array(d_se))
    out.update({"points": len(pts), "seed": ev.CHECK_SEED,
                "sun_earth_reported_not_judged": {"median_pp": round(float(np.median(a)), 2), "p90_pp": round(float(np.percentile(a, 90)), 2)},
                "samples": pts, "columns": ["lat", "lon", "earth_own_pct", "earth_grid_pct", "earth_flat_pct", "neighbour_spread_pp"]})
    c = ev.judge_c(np.array(d_grid), np.array(spread) > ev.UNCERTAIN_SPREAD_PP)
    return out, c


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--pole", choices=("south", "north"), default="south")
    ap.add_argument("--dem", help="LOLA map for check B (default data/terrain/ldem_75?_120m.img)")
    ap.add_argument("--skip-check-b", action="store_true", help="development only: no LOLA map, check B not run (the page says so)")
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args()
    tic = time.perf_counter()
    tag = "n" if args.pole == "north" else "s"
    grid_path = Path(args.out) / f"horizon_grid_{tag}.json"
    if not grid_path.exists():
        print(f"No horizon grid: run  python scripts/build_horizon_grid.py --spice{' --pole north' if tag == 'n' else ''}  first")
        return 1
    meta, H = ev.load_horizon_grid(grid_path)
    dem_path = Path(args.dem) if args.dem else DEMS[args.pole]
    if not args.skip_check_b and not dem_path.exists():
        print(f"Check B needs the LOLA map {dem_path} (python scripts/download_terrain.py{' --north' if tag == 'n' else ''}).")
        return 1
    t0, t1 = utc(ev.PERIOD_UTC[0]), utc(ev.PERIOD_UTC[1])
    cache = cached_for_window(args.spice, t0 - 86400.0, t1 + 86400.0, step=3600.0)
    ts = np.arange(t0, t1, ev.STEP_S)
    sky = ev.build_sky(cache, ts, 1.0 if tag == "n" else -1.0)
    eph = "JPL DE440" if args.spice else "analytic (demo)"
    print(f"{meta['dem']} horizon grid, {meta['n']} x {meta['n']} every {meta['spacing_km']:g} km; "
          f"{len(ts)} hours from {ev.PERIOD_UTC[0][:10]} ({eph})")

    a = ev.check_a(sky)
    print(f"Check A, level sphere: Earth in view {a['earth_in_view_pct']} -> {'PASS' if a['pass'] else 'FAIL'}")

    n = meta["n"]
    X0, sp = meta["x0_km"], meta["spacing_km"]
    ax = X0 + np.arange(n) * sp
    Xg, Yg = np.meshgrid(ax, ax)                       # [row (Y)][col (X)], as the tiles
    valid = ~np.isnan(H[:, :, 0])
    lat, lon = plane_latlon(meta, Xg[valid], Yg[valid])
    res = ev.shares(lat, lon, H[valid], sky)
    out = np.full((len(LAYERS), n, n), MISSING, np.uint8)
    for k, (key, _) in enumerate(LAYERS):
        layer = np.full((n, n), MISSING, np.uint8)
        layer[valid] = np.clip(np.round(res[key] / STEP_PP), 0, 200).astype(np.uint8)
        out[k] = layer
    print(f"{int(valid.sum())} grid points ({time.perf_counter() - tic:.0f} s): Earth above the terrain "
          f"median {np.median(res['earth']):.1f}%, never at {int((res['earth'] == 0).sum())} points, always at "
          f"{int((res['earth'] == 100).sum())}; Sun and Earth together median {np.median(res['sun_earth']):.1f}%")

    E = np.where(valid, out[0].astype(float) * STEP_PP, np.nan)     # Earth in view, as stored
    # the map's hatching: a grid point is uncertain if any of the four quads touching it would be flagged,
    # i.e. its 3 x 3 neighbourhood spans more than the threshold (commsMap.ts nodeUncertain)
    Ep = np.pad(E, 1, constant_values=np.nan)
    win = np.stack([Ep[1 + dr:1 + dr + n, 1 + dc:1 + dc + n] for dr in (-1, 0, 1) for dc in (-1, 0, 1)])
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)             # all-NaN windows outside the cap
        node_spread = np.nanmax(win, axis=0) - np.nanmin(win, axis=0)
    hatched = valid & (node_spread > ev.UNCERTAIN_SPREAD_PP)
    print(f"Uncertainty flag (spread > {ev.UNCERTAIN_SPREAD_PP:g} pp): {100 * hatched.sum() / valid.sum():.1f}% of grid points hatched on the map")

    b = c = None
    if not args.skip_check_b:
        b, c = check_b(meta, H, sky, dem_path, E)
        print(f"Check B: |grid - own| median {b['median_pp']} pp, p90 {b['p90_pp']} pp (limits {ev.CHECK_B_MEDIAN_MAX_PP:g} / "
              f"{ev.CHECK_B_P90_MAX_PP:g}); flat horizon median {b['flat_median_pp']} pp -> {'PASS' if b['pass'] else 'FAIL'}")
        print(f"Check C: {100 * c['flagged_share']:.1f}% of the points flagged (limit {100 * ev.CHECK_C_FLAGGED_MAX_SHARE:g}%); unflagged "
              f"|grid - own| p90 {c['unflagged_p90_pp']} pp (limit {ev.CHECK_C_UNFLAGGED_P90_MAX_PP:g}); errors over "
              f"{ev.CHECK_B_P90_MAX_PP:g} pp flagged: {c['large_errors_flagged']} of {c['large_errors']} -> {'PASS' if c['pass'] else 'FAIL'}")

    # a few grid points for web/tests/earthvis.check.mjs: the browser must reproduce them
    rng = np.random.default_rng(7)
    idx = np.argwhere(valid)
    pick = idx[rng.choice(len(idx), size=min(6, len(idx)), replace=False)]
    samples = []
    for i, j in pick:
        la, lo = plane_latlon(meta, Xg[i, j], Yg[i, j])
        samples.append({"row": int(i), "col": int(j), "lat": float(la), "lon": float(lo),
                        **{key: int(out[k, i, j]) * STEP_PP for k, (key, _) in enumerate(LAYERS)}})
    # and the hatching at 30 grid points, half of them hatched where there are any
    hi_idx, lo_idx = np.argwhere(hatched), np.argwhere(valid & ~hatched)
    hpick = [*(hi_idx[rng.choice(len(hi_idx), size=min(15, len(hi_idx)), replace=False)] if len(hi_idx) else []),
             *lo_idx[rng.choice(len(lo_idx), size=min(15, len(lo_idx)), replace=False)]]
    hatch_samples = [[int(i), int(j), bool(hatched[i, j])] for i, j in hpick]

    doc = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
           "ephemeris": eph, "dem": meta["dem"], "horizon_grid": grid_path.name, "pole": meta["pole"],
           "period_utc": list(ev.PERIOD_UTC), "step_h": ev.STEP_S / 3600.0,
           "n": n, "x0_km": X0, "spacing_km": sp, "radius_km": meta["radius_km"], "x_sign": meta["x_sign"],
           "y_sign": meta["y_sign"], "min_abs_lat": meta["min_abs_lat"],
           "layers": [{"id": k, "label": lbl} for k, lbl in LAYERS], "step_pp": STEP_PP, "missing": MISSING,
           "bin": f"earth_vis_{tag}.bin", "dtype": "uint8, [layer][row (Y)][col (X)]",
           "rules": {"earth": "Earth's centre above the terrain horizon in its direction, seen from the point (parallax included)",
                     "sun": "Sun's centre above the terrain horizon in its direction",
                     "dsn": f"Goldstone, Madrid or Canberra sees the Moon above {DSN_MIN_ELEV_DEG:g} deg (our assumption), computed for the pole point"},
           "stats": {"points": int(valid.sum()), "earth_median_pct": round(float(np.median(res["earth"])), 1),
                     "earth_never_points": int((res["earth"] == 0).sum()), "earth_always_points": int((res["earth"] == 100).sum()),
                     "sun_earth_median_pct": round(float(np.median(res["sun_earth"])), 1)},
           "uncertain_spread_pp": ev.UNCERTAIN_SPREAD_PP, "hatched_share": round(float(hatched.sum() / valid.sum()), 3),
           "check_a": a, "check_b": b, "check_c": c,
           "check_b_note": None if b else "not run (development build without the LOLA map)",
           "samples": samples, "hatch_samples": hatch_samples}
    outdir = Path(args.out)
    (outdir / f"earth_vis_{tag}.bin").write_bytes(out.tobytes())
    (outdir / f"earth_vis_{tag}.json").write_text(json.dumps(doc, separators=(",", ":")))
    print(f"-> {outdir / f'earth_vis_{tag}.json'} + .bin ({out.nbytes // 1024} kB, {time.perf_counter() - tic:.0f} s)")
    failed = (not a["pass"]) or (b is not None and not b["pass"]) or (c is not None and not c["pass"])
    if failed:
        print("A pre-registered check FAILED. The map is written and the page shows the result; the limits stay as they are.")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
