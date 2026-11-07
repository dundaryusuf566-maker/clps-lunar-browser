"""Dense communication maps of a polar cap: every point of a 1 km grid with its own LOLA horizon.

    python scripts/build_comms_dense.py --spice                    (south; ~10-20 min with 15 workers)
    python scripts/build_comms_dense.py --spice --pole north

The 5 km maps (build_earth_visibility.py) blend each place's horizon from four grid points, and
their pre-registered check B failed in its tail: near crater rims the blend is wrong. Here nothing is
blended: each point of a DENSE_SPACING_KM grid computes its own horizon from the LOLA map
(fast_horizon, as the horizon grid's points do) and applies the same rules hour by hour over the same
twelve months (engine/surface/earth_visibility.py). The map's value at a place is that of the
nearest such point.

Pre-registered check D (criteria in earth_visibility.py, written before any dense map was computed):
at 300 new random points, |nearest dense point - the point's own horizon| for the Earth share:
median <= 2 and 90th percentile <= 10 percentage points, and better than a flat horizon. The 5 km
grid is evaluated at the same points too, reported but not judged. Exit code 2 if D fails; the map
is written either way and the page shows the result.

Writes web/public/data/earth_vis_dense_s.json + .bin (uint8, [layer][row][col], 0.5 percentage
points per step, 255 = no point; layers earth, sun_earth, dsn), the format of earth_vis_s.json.
Needs the LOLA map (data/terrain) and, without --dem, the orientation check, as build_horizon_grid.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from multiprocessing import Pool, cpu_count
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402
from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface import earth_visibility as ev  # noqa: E402
from engine.surface.horizon_grid import Pyramid, fast_horizon, grid_nodes, latlon_of_plane  # noqa: E402
from engine.surface.terrain import PolarGrid  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
DEMS = {"south": ROOT / "data" / "terrain" / "ldem_75s_120m.img", "north": ROOT / "data" / "terrain" / "ldem_75n_120m.img"}
LAYERS = [("earth", "Earth above the terrain"), ("sun_earth", "Sun and Earth above the terrain together"),
          ("dsn", "Earth above the terrain and a DSN complex in view")]
OBSERVER_M = 2.0            # as the horizon grid (build_horizon_grid.py)
STEP_PP, MISSING = 0.5, 255

_W: dict = {}


def utc(s: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(s).replace(tzinfo=timezone.utc))


def own_horizons(pyr: Pyramid, lat: np.ndarray, lon: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Each point's own horizon (n, 360) and which points the map covers."""
    H = np.zeros((len(lat), 360))
    ok = np.zeros(len(lat), bool)
    for k, (la, lo) in enumerate(zip(lat, lon)):
        try:
            H[k], _, _ = fast_horizon(pyr, float(la), float(lo), observer_m=OBSERVER_M, az_step_deg=1.0)
            ok[k] = True
        except ValueError:
            pass                                                     # outside the map
    return H, ok


def _init(dem_path: str, earth: np.ndarray, sun: np.ndarray, dsn: np.ndarray) -> None:
    dem = PolarGrid.load(dem_path)
    _W.update(pyr=Pyramid(dem), sky=ev.Sky(earth_fixed_km=earth, sun_fixed=sun, dsn=dsn))


def _row(task: tuple[int, np.ndarray, np.ndarray, np.ndarray]) -> tuple[int, np.ndarray, np.ndarray]:
    """One grid row: (row, columns, uint8 values (3, k)) for the points the map covers."""
    i, cols, lat, lon = task
    H, ok = own_horizons(_W["pyr"], lat, lon)
    out = np.full((3, len(cols)), MISSING, np.uint8)
    if ok.any():
        s = ev.shares(lat[ok], lon[ok], H[ok], _W["sky"], chunk=64)
        for k, (key, _) in enumerate(LAYERS):
            out[k, ok] = np.clip(np.round(s[key] / STEP_PP), 0, 200).astype(np.uint8)
    return i, cols, out


def check_d(pyr: Pyramid, dem: PolarGrid, sky: ev.Sky, vals: np.ndarray, X0: float, sp: float, n: int,
            min_lat: float, grid5: tuple[dict, np.ndarray] | None) -> dict:
    rng = np.random.default_rng(ev.CHECK_D_SEED)
    rho_max = 2 * dem.radius_m / 1000.0 * np.tan(np.radians(90.0 - min_lat) / 2)
    rows, d_dense, d_flat, d_grid5, d_se = [], [], [], [], []
    tries = 0
    while len(rows) < ev.CHECK_D_POINTS and tries < 20 * ev.CHECK_D_POINTS:
        tries += 1
        r, th = rho_max * np.sqrt(rng.uniform()), rng.uniform(0, 2 * np.pi)
        x, y = r * np.cos(th), r * np.sin(th)
        la, lo = (float(v) for v in latlon_of_plane(dem, x, y))
        if abs(la) < min_lat:
            continue
        i, j = int(round((y - X0) / sp)), int(round((x - X0) / sp))
        if not (0 <= i < n and 0 <= j < n) or vals[0, i, j] == MISSING:
            continue
        H, ok = own_horizons(pyr, np.array([la]), np.array([lo]))
        if not ok[0]:
            continue
        o = ev.shares(np.array([la]), np.array([lo]), H, sky)
        f = ev.shares(np.array([la]), np.array([lo]), None, sky)
        dense = vals[0, i, j] * STEP_PP
        d_dense.append(dense - float(o["earth"][0]))
        d_flat.append(float(f["earth"][0] - o["earth"][0]))
        d_se.append(vals[1, i, j] * STEP_PP - float(o["sun_earth"][0]))
        g5 = None
        if grid5 is not None:
            m5, H5 = grid5
            hg = ev.interp_grid(H5, m5["x0_km"], m5["spacing_km"], x, y)
            if hg is not None:
                g5 = float(ev.shares(np.array([la]), np.array([lo]), hg[None, :], sky)["earth"][0])
                d_grid5.append(g5 - float(o["earth"][0]))
        rows.append([round(la, 8), round(lo, 8), round(float(o["earth"][0]), 2), dense, round(float(f["earth"][0]), 2),
                     None if g5 is None else round(g5, 2)])
        if len(rows) % 50 == 0:
            print(f"  {len(rows)}/{ev.CHECK_D_POINTS}", flush=True)
    out = ev.judge_d(np.array(d_dense), np.array(d_flat))
    a = np.abs(np.array(d_se))
    out.update({"points": len(rows), "seed": ev.CHECK_D_SEED,
                "sun_earth_reported_not_judged": {"median_pp": round(float(np.median(a)), 2), "p90_pp": round(float(np.percentile(a, 90)), 2)},
                "samples": rows, "columns": ["lat", "lon", "earth_own_pct", "earth_dense_pct", "earth_flat_pct", "earth_grid5_pct"]})
    if d_grid5:
        g = np.abs(np.array(d_grid5))
        out["grid5_same_points_reported_not_judged"] = {"points": len(g), "median_pp": round(float(np.median(g)), 2),
                                                        "p90_pp": round(float(np.percentile(g, 90)), 2)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--pole", choices=("south", "north"), default="south")
    ap.add_argument("--dem", help="LOLA map (default data/terrain/ldem_75?_120m.img)")
    ap.add_argument("--spacing", type=float, default=ev.DENSE_SPACING_KM, help="km (check D is registered for 1 km)")
    ap.add_argument("--min-lat", type=float, default=75.0)
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args()
    tic = time.perf_counter()
    dem_path = Path(args.dem) if args.dem else DEMS[args.pole]
    if not dem_path.exists():
        print(f"Needs the LOLA map {dem_path} (python scripts/download_terrain.py{' --north' if args.pole == 'north' else ''}).")
        return 1
    dem = PolarGrid.load(dem_path)
    if (args.pole == "north") != (dem.pole > 0):
        print(f"{dem.name} is a {'north' if dem.pole > 0 else 'south'} polar map, not {args.pole}")
        return 1
    ok_file = ROOT / "data" / "terrain" / f"_orientation_{args.pole}.json"
    verdict = json.loads(ok_file.read_text()) if ok_file.exists() else None
    if args.dem is None and (not verdict or verdict.get("code") != 0 or verdict.get("dem") != dem.name):
        print(f"Run  python scripts/check_polar_orientation.py --pole {args.pole}  first.")
        return 1
    tag = "n" if dem.pole > 0 else "s"
    t0, t1 = utc(ev.PERIOD_UTC[0]), utc(ev.PERIOD_UTC[1])
    cache = cached_for_window(args.spice, t0 - 86400.0, t1 + 86400.0, step=3600.0)
    sky = ev.build_sky(cache, np.arange(t0, t1, ev.STEP_S), float(dem.pole))
    eph = "JPL DE440" if args.spice else "analytic (demo)"

    X, Y, n, X0 = grid_nodes(dem, args.spacing, args.min_lat)
    lat, lon = latlon_of_plane(dem, X, Y)
    inside = np.abs(lat) >= args.min_lat
    tasks = [(i, np.flatnonzero(inside[i]), lat[i, inside[i]], lon[i, inside[i]]) for i in range(n) if inside[i].any()]
    total = int(inside.sum())
    print(f"{dem.name}: {total} points every {args.spacing:g} km to {args.min_lat:g} deg ({n} x {n}), own LOLA horizon each; "
          f"{len(sky.dsn)} hours from {ev.PERIOD_UTC[0][:10]} ({eph}); {args.workers} worker(s)")
    vals = np.full((3, n, n), MISSING, np.uint8)
    done = 0
    with Pool(args.workers, initializer=_init, initargs=(str(dem_path), sky.earth_fixed_km, sky.sun_fixed, sky.dsn)) as pool:
        for k, (i, cols, out) in enumerate(pool.imap_unordered(_row, tasks), 1):
            vals[:, i, cols] = out
            done += len(cols)
            if k % 50 == 0 or k == len(tasks):
                el = time.perf_counter() - tic
                print(f"  {done}/{total} points ({el:.0f} s, ~{el / done * (total - done) / 60:.0f} min left)", flush=True)
    covered = vals[0] != MISSING
    E = vals[0][covered] * STEP_PP
    print(f"{int(covered.sum())} points with a horizon: Earth above the terrain median {np.median(E):.1f}%, "
          f"never at {int((E == 0).sum())}, always at {int((E == 100).sum())}")

    a = ev.check_a(sky)
    grid5_path = Path(args.out) / f"horizon_grid_{tag}.json"
    grid5 = ev.load_horizon_grid(grid5_path) if grid5_path.exists() else None
    print(f"Check D at {ev.CHECK_D_POINTS} new random points (seed {ev.CHECK_D_SEED}):")
    pyr = Pyramid(dem)
    d = check_d(pyr, dem, sky, vals, X0, args.spacing, n, args.min_lat, grid5)
    print(f"Check D: |dense - own| median {d['median_pp']} pp, p90 {d['p90_pp']} pp (limits {ev.CHECK_D_MEDIAN_MAX_PP:g} / "
          f"{ev.CHECK_D_P90_MAX_PP:g}); flat horizon median {d['flat_median_pp']} pp -> {'PASS' if d['pass'] else 'FAIL'}")
    if "grid5_same_points_reported_not_judged" in d:
        g = d["grid5_same_points_reported_not_judged"]
        print(f"  (the 5 km grid at the same points, reported: median {g['median_pp']} pp, p90 {g['p90_pp']} pp)")

    rng = np.random.default_rng(7)
    idx = np.argwhere(covered)
    samples = []
    for i, j in idx[rng.choice(len(idx), size=min(6, len(idx)), replace=False)]:
        la, lo = latlon_of_plane(dem, X[i, j], Y[i, j])
        samples.append({"row": int(i), "col": int(j), "lat": float(la), "lon": float(lo),
                        **{key: int(vals[k, i, j]) * STEP_PP for k, (key, _) in enumerate(LAYERS)}})
    doc = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
           "ephemeris": eph, "dem": dem.name, "pole": "north" if dem.pole > 0 else "south", "dense": True,
           "period_utc": list(ev.PERIOD_UTC), "step_h": ev.STEP_S / 3600.0,
           "n": n, "x0_km": X0, "spacing_km": args.spacing, "radius_km": dem.radius_m / 1000.0, "x_sign": dem.x_sign,
           "y_sign": dem.y_sign, "min_abs_lat": args.min_lat, "observer_m": OBSERVER_M,
           "layers": [{"id": k, "label": lbl} for k, lbl in LAYERS], "step_pp": STEP_PP, "missing": MISSING,
           "bin": f"earth_vis_dense_{tag}.bin", "dtype": "uint8, [layer][row (Y)][col (X)]",
           "rules": "as earth_vis_s.json: each point's own LOLA horizon, no blending; value at a place = nearest point",
           "stats": {"points": int(covered.sum()), "earth_median_pct": round(float(np.median(E)), 1),
                     "earth_never_points": int((E == 0).sum()), "earth_always_points": int((E == 100).sum())},
           "check_a": a, "check_b": None, "check_b_note": "the dense map is judged by check D", "check_d": d,
           "samples": samples}
    outdir = Path(args.out)
    (outdir / doc["bin"]).write_bytes(vals.tobytes())
    (outdir / f"earth_vis_dense_{tag}.json").write_text(json.dumps(doc, separators=(",", ":")))
    print(f"-> {outdir / f'earth_vis_dense_{tag}.json'} + .bin ({vals.nbytes / 1e6:.1f} MB, {time.perf_counter() - tic:.0f} s)")
    dem.close()
    failed = not a["pass"] or not d["pass"]
    if failed:
        print("A pre-registered check FAILED. The map is written and the page shows the result; the limits stay as they are.")
    return 2 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
