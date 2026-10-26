"""LOLA terrain horizons over a polar cap (south or north), for the website's Anywhere page.

    python scripts/build_horizon_grid.py --spice                  (south, ~10-25 minutes)
    python scripts/build_horizon_grid.py --spice --pole north     (after check_polar_orientation.py --pole north)

Every `--spacing` km (default 5) on the polar stereographic plane, from the pole to
75 S, the terrain horizon (1 deg azimuth steps, 2 m observer) with the fast horizon
of engine/surface/horizon_grid.py. Written as tiles the browser fetches only when a
point falls in them:

    web/public/data/horizon_grid_s.json          layout, tiles, and the checks below
    web/public/data/horizon_grid_s/t_<i>_<j>.bin int16 little-endian, 0.01 deg, [row][col][azimuth]

For a point between grid points the browser interpolates the four around it. How
good is that? At `--check` random points of the cap this script compares, each
against the point's own horizon:

  * the horizon itself (deg, all azimuths),
  * what matters for a lander: the share of 2026 with the Sun above the terrain
    (JPL DE440 with --spice), interpolated against own, and flat ground against own;
  * and, at `--full-check` of them, the fast horizon against the engine's full
    compute_horizon on this map.

The numbers go into the JSON and onto the page. Nothing is fitted to them.
"""

from __future__ import annotations

import argparse
import json
import struct
import sys
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402
from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface.horizon_grid import Pyramid, fast_horizon, grid_nodes, latlon_of_plane  # noqa: E402
from engine.surface.scene3d import disc_fraction  # noqa: E402
from engine.surface.terrain import PolarGrid, compute_horizon  # noqa: E402
from engine.validation.illumination import az_el_fixed  # noqa: E402

DEMS = {"south": ROOT / "data" / "terrain" / "ldem_75s_120m.img", "north": ROOT / "data" / "terrain" / "ldem_75n_120m.img"}
DATA = ROOT / "web" / "public" / "data"
MISSING = -32768
OBSERVER_M = 2.0


def write_png_gray(path: Path, img: np.ndarray) -> None:
    """8-bit greyscale PNG without extra dependencies."""
    h, w = img.shape
    raw = b"".join(b"\x00" + img[r].astype(np.uint8).tobytes() for r in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 0, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def shaded_relief(pyr: Pyramid, rho_max_km: float) -> tuple[np.ndarray, list[float]]:
    """Hillshade of the cap from the 1.2 km level (light from the upper left), and its extent
    [x_min, x_max, y_min, y_max] in plane km; image rows follow Y (map lines), columns X."""
    dem = pyr.dem
    level = pyr.levels[-1][0]
    b = level.block
    s_km = dem.map_scale_m / 1000.0 * b
    h = np.where(level.dn == -32768, np.nan, level.dn.astype(float) * dem.scale)
    # plane coordinates of block centres
    xs = ((np.arange(h.shape[1]) * b + (b - 1) / 2.0) - dem.sample_offset) * dem.map_scale_m / 1000.0
    ys = ((np.arange(h.shape[0]) * b + (b - 1) / 2.0) - dem.line_offset) * dem.map_scale_m / 1000.0
    cx = (np.abs(xs) <= rho_max_km)
    cy = (np.abs(ys) <= rho_max_km)
    h = h[np.ix_(cy, cx)]
    gy, gx = np.gradient(h, s_km * 1000.0)
    az, alt = np.radians(315.0), np.radians(35.0)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gx, gy)
    shade = np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)
    img = np.clip(40 + 200 * np.nan_to_num(shade, nan=0.0), 0, 255)
    xsel, ysel = xs[cx], ys[cy]
    return img, [float(xsel[0] - s_km / 2), float(xsel[-1] + s_km / 2), float(ysel[0] - s_km / 2), float(ysel[-1] + s_km / 2)]


def interp_nodes(H: np.ndarray, X0: float, sp: float, X: float, Y: float) -> np.ndarray | None:
    """Bilinear horizon (deg per azimuth) from the four grid points around plane point (X, Y), as the
    browser does it (web/src/lib/horizonGrid.ts): missing neighbours are left out and the rest reweighted."""
    c, r = (X - X0) / sp, (Y - X0) / sp
    c0, r0 = int(np.floor(c)), int(np.floor(r))
    fc, fr = c - c0, r - r0
    acc, wsum = np.zeros(H.shape[2]), 0.0
    for dr, dc, w in ((0, 0, (1 - fc) * (1 - fr)), (0, 1, fc * (1 - fr)), (1, 0, (1 - fc) * fr), (1, 1, fc * fr)):
        rr, cc = r0 + dr, c0 + dc
        if 0 <= rr < H.shape[0] and 0 <= cc < H.shape[1] and H[rr, cc, 0] != MISSING and w > 0:
            acc += w * H[rr, cc].astype(float) / 100.0
            wsum += w
    return acc / wsum if wsum > 0 else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--pole", choices=("south", "north"), default="south")
    ap.add_argument("--dem")
    ap.add_argument("--spacing", type=float, default=5.0, help="km between grid points")
    ap.add_argument("--min-lat", type=float, default=75.0, help="cap edge, deg (absolute)")
    ap.add_argument("--tile", type=int, default=20, help="grid points per tile side")
    ap.add_argument("--check", type=int, default=300, help="random points for the interpolation check")
    ap.add_argument("--full-check", type=int, default=20, help="of those, compared with compute_horizon too")
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args()
    tic = time.perf_counter()
    dem = PolarGrid.load(args.dem or DEMS[args.pole])
    tag = "n" if dem.pole > 0 else "s"
    if (args.pole == "north") != (dem.pole > 0):
        print(f"{dem.name} is a {'north' if dem.pole > 0 else 'south'} polar map, not {args.pole}")
        return 1
    ok_file = ROOT / "data" / "terrain" / f"_orientation_{args.pole}.json"
    verdict = json.loads(ok_file.read_text()) if ok_file.exists() else None
    if args.dem is None and (not verdict or verdict.get("code") != 0 or verdict.get("dem") != dem.name):
        print(f"Run  python scripts/check_polar_orientation.py --pole {args.pole}  first: the map's orientation "
              "must be confirmed against named craters before its horizons are used.")
        return 1
    print(f"{dem.name}: {dem.lines} x {dem.samples} at {dem.map_scale_m:g} m; building the 360 m and 1.2 km levels")
    pyr = Pyramid(dem)
    X, Y, n, X0 = grid_nodes(dem, args.spacing, args.min_lat)
    lat, lon = latlon_of_plane(dem, X, Y)
    n_az = 360
    H = np.full((n, n, n_az), MISSING, np.int16)
    reach = np.full((n, n), np.nan)
    inside = np.abs(lat) >= args.min_lat
    todo = np.argwhere(inside)
    print(f"{len(todo)} grid points every {args.spacing:g} km to {args.min_lat:g} {'N' if dem.pole > 0 else 'S'} ({n} x {n})")
    for k, (i, j) in enumerate(todo):
        try:
            el, _, rch = fast_horizon(pyr, float(lat[i, j]), float(lon[i, j]), observer_m=OBSERVER_M, az_step_deg=1.0)
        except ValueError:
            continue                                            # outside the map
        H[i, j] = np.clip(np.round(el * 100.0), -32767, 32767).astype(np.int16)
        reach[i, j] = rch
        if (k + 1) % 2000 == 0 or k + 1 == len(todo):
            el_t = time.perf_counter() - tic
            print(f"  {k + 1}/{len(todo)} ({el_t:.0f} s, ~{el_t / (k + 1) * (len(todo) - k - 1) / 60:.0f} min left)", flush=True)

    out = Path(args.out)
    tdir = out / f"horizon_grid_{tag}"
    tdir.mkdir(parents=True, exist_ok=True)
    for old in tdir.glob("t_*.bin"):
        old.unlink()
    T = args.tile
    tiles = []
    for ti in range(0, n, T):
        for tj in range(0, n, T):
            block = np.full((T, T, n_az), MISSING, np.int16)
            part = H[ti:ti + T, tj:tj + T]
            block[:part.shape[0], :part.shape[1]] = part
            if (block[:, :, 0] != MISSING).any():
                (tdir / f"t_{ti // T}_{tj // T}.bin").write_bytes(block.astype("<i2").tobytes())
                tiles.append([ti // T, tj // T])
    size_mb = sum(p.stat().st_size for p in tdir.glob("t_*.bin")) / 1e6
    print(f"{len(tiles)} tiles, {size_mb:.1f} MB -> {tdir}")
    rho_cap = 2 * dem.radius_m / 1000.0 * np.tan(np.radians(90.0 - args.min_lat) / 2)
    relief, extent = shaded_relief(pyr, rho_cap)
    write_png_gray(out / f"horizon_grid_{tag}.png", relief)
    print(f"shaded relief {relief.shape[1]} x {relief.shape[0]} px -> {out / f'horizon_grid_{tag}.png'}")

    # --- how good is the interpolated horizon? ------------------------------------------
    print(f"Checking at {args.check} random points of the cap:")
    rng = np.random.default_rng(2026)
    rho_max = 2 * dem.radius_m / 1000.0 * np.tan(np.radians(90.0 - args.min_lat) / 2)
    cache = cached_for_window(args.spice, utc_to_tdb(datetime(2025, 12, 31, tzinfo=timezone.utc)),
                              utc_to_tdb(datetime(2027, 1, 2, tzinfo=timezone.utc)), step=3600.0)
    ts = np.arange(utc_to_tdb(datetime(2026, 1, 1, tzinfo=timezone.utc)), utc_to_tdb(datetime(2027, 1, 1, tzinfo=timezone.utc)), 3600.0)
    rot = cache.rotation_many("MOON", ts)
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    az_grid = np.arange(n_az, dtype=float)
    d_el, d_sun, d_flat, d_full, pts, interp_samples = [], [], [], [], [], []
    tries = 0
    while len(pts) < args.check and tries < 20 * args.check:
        tries += 1
        rr, th = rho_max * np.sqrt(rng.uniform()), rng.uniform(0, 2 * np.pi)
        x, y = rr * np.cos(th), rr * np.sin(th)
        la, lo = (float(v) for v in latlon_of_plane(dem, x, y))
        if abs(la) < args.min_lat:
            continue
        hi = interp_nodes(H, X0, args.spacing, x, y)
        if hi is None:
            continue
        try:
            own, _, _ = fast_horizon(pyr, la, lo, observer_m=OBSERVER_M, az_step_deg=1.0)
        except ValueError:
            continue
        az, el = az_el_fixed(la, lo, sun)
        sun_own = disc_fraction(el - np.interp(az, az_grid, own, period=360.0)).mean()
        sun_int = disc_fraction(el - np.interp(az, az_grid, hi, period=360.0)).mean()
        sun_flat = disc_fraction(el).mean()
        d_el.append(hi - own)
        d_sun.append(100 * (sun_int - sun_own))
        d_flat.append(100 * (sun_flat - sun_own))
        if len(d_full) < args.full_check:
            ref = compute_horizon(dem, la, lo, observer_m=OBSERVER_M, az_step_deg=1.0, max_dist_km=250.0)
            d_full.append(own - ref.elev_deg)
        pts.append((round(la, 4), round(lo, 4), round(float(sun_own) * 100, 1), round(float(sun_int) * 100, 1), round(float(sun_flat) * 100, 1)))
        if len(interp_samples) < 6:                          # for web/tests/horizon.check.mjs: the browser must match
            interp_samples.append({"lat": la, "lon": lo, "elev_deg": [round(float(v), 6) for v in hi]})
    d_el = np.abs(np.concatenate(d_el))
    d_sun, d_flat = np.abs(np.array(d_sun)), np.abs(np.array(d_flat))
    d_full = np.abs(np.concatenate(d_full)) if d_full else np.array([np.nan])
    stats = lambda a, k=3: {"median": round(float(np.median(a)), k), "p90": round(float(np.percentile(a, 90)), k),  # noqa: E731
                            "p99": round(float(np.percentile(a, 99)), k), "max": round(float(np.max(a)), k)}
    check = {"points": len(pts), "seed": 2026, "year": 2026,
             "horizon_interp_minus_own_deg": stats(d_el),
             "sunlit_pct_interp_minus_own": stats(d_sun, 2), "sunlit_pct_flat_minus_own": stats(d_flat, 2),
             "fast_minus_full_horizon_deg": stats(d_full), "full_points": min(args.full_check, len(pts)),
             "samples": pts[:40], "interp_samples": interp_samples}
    print(f"  horizon, interpolated vs own: median {check['horizon_interp_minus_own_deg']['median']} deg, "
          f"p90 {check['horizon_interp_minus_own_deg']['p90']} deg")
    print(f"  Sun above the terrain in 2026 (% of the year), |interpolated - own|: median "
          f"{check['sunlit_pct_interp_minus_own']['median']}, p90 {check['sunlit_pct_interp_minus_own']['p90']}; "
          f"flat ground instead: median {check['sunlit_pct_flat_minus_own']['median']}, p90 {check['sunlit_pct_flat_minus_own']['p90']}")
    print(f"  fast vs full compute_horizon ({check['full_points']} points): median {check['fast_minus_full_horizon_deg']['median']} deg, "
          f"p99 {check['fast_minus_full_horizon_deg']['p99']} deg")

    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
            "ephemeris": "JPL DE440" if args.spice else "analytic (demo)", "dem": dem.name, "map_scale_m": dem.map_scale_m,
            "orientation_check": None if not verdict else verdict.get("verdict"),
            "pole": "north" if dem.pole > 0 else "south", "tiles_dir": f"horizon_grid_{tag}", "min_abs_lat": args.min_lat, "spacing_km": args.spacing, "n": n, "x0_km": X0,
            "radius_km": dem.radius_m / 1000.0, "x_sign": dem.x_sign, "y_sign": dem.y_sign,
            "az_step_deg": 1.0, "n_az": n_az, "scale_deg": 0.01, "missing": MISSING, "tile": T, "tiles": tiles,
            "dtype": "int16 little-endian, [row (Y)][col (X)][azimuth from north, clockwise]",
            "observer_m": OBSERVER_M, "max_dist_km": 250.0, "relief_png": f"horizon_grid_{tag}.png", "relief_extent_km": extent,
            "reach_km_min": round(float(np.nanmin(reach)), 1), "reach_km_median": round(float(np.nanmedian(reach)), 1),
            "method": "engine/surface/horizon_grid.py fast_horizon: 120 m map to 15 km, 360 m block means to 100 km, "
                      "1.2 km beyond, scene3d.MARCH steps; the browser interpolates bilinearly between the four grid points.",
            "check": check}
    (out / f"horizon_grid_{tag}.json").write_text(json.dumps(meta, separators=(",", ":")))
    print(f"-> {out / f'horizon_grid_{tag}.json'} ({time.perf_counter() - tic:.0f} s)")
    dem.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
