"""The tilt of the ground over a polar cap, for the browser's temperatures (Anywhere page).

    python scripts/build_slope_map.py                 (south, ~1-3 minutes)
    python scripts/build_slope_map.py --pole north    (after check_polar_orientation.py --pole north)

Why: scripts/thermal_attribution.py measured where the browser's polar temperature error comes
from; its rule, written before the run, said to add a 240 m slope map if that at least halves
the median error and brings it to 15 K or less. It did (32.2 K -> 14.8 K, DE440). The map is
defined in engine/surface/slope_map.py: one normal per 2 x 2 block of the 120 m map, the normal
build_thermal.py's local_normal gives at the block's centre.

Written as tiles the browser fetches only for the clicked point:

    web/public/data/slope_map_s.json            layout and the checks below
    web/public/data/slope_map_s/t_<i>_<j>.bin   int16 little-endian, [block row][block col][east, north]

Checks (the script stops with exit code 2 if one fails):
  * the stored normals, decoded, against local_normal computed afresh at the block centre, at
    `--check` random blocks and at thermal.json's points: within 0.01 deg (int16 resolution
    is ~0.002 deg);
  * samples for the browser's decoder (web/tests/slope.check.mjs) are written into the JSON (check_samples).
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402
from engine.surface.slope_map import MISSING, block_centre, block_of, decode, encode, normals_at, slope_deg  # noqa: E402
from engine.surface.terrain import PolarGrid  # noqa: E402

DEMS = {"south": ROOT / "data" / "terrain" / "ldem_75s_120m.img", "north": ROOT / "data" / "terrain" / "ldem_75n_120m.img"}
DATA = ROOT / "web" / "public" / "data"
TOL_DEG = 0.01


def local_normal():
    spec = importlib.util.spec_from_file_location("build_thermal", ROOT / "scripts" / "build_thermal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.local_normal


def angle_deg(a, b):
    return float(np.degrees(np.arccos(np.clip(np.dot(a, b) / np.linalg.norm(a) / np.linalg.norm(b), -1, 1))))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pole", choices=("south", "north"), default="south")
    ap.add_argument("--dem")
    ap.add_argument("--min-lat", type=float, default=80.0, help="cap edge, deg (absolute); 75 doubles the size")
    ap.add_argument("--tile", type=int, default=256, help="blocks per tile side")
    ap.add_argument("--check", type=int, default=300)
    ap.add_argument("--out", default=str(DATA))
    args = ap.parse_args()
    tic = time.perf_counter()
    dem = PolarGrid.load(args.dem or DEMS[args.pole])
    if (args.pole == "north") != (dem.pole > 0):
        print(f"{dem.name} is a {'north' if dem.pole > 0 else 'south'} polar map, not {args.pole}")
        return 1
    ok_file = ROOT / "data" / "terrain" / f"_orientation_{args.pole}.json"
    verdict = json.loads(ok_file.read_text()) if ok_file.exists() else None
    if args.dem is None and (not verdict or verdict.get("code") != 0 or verdict.get("dem") != dem.name):
        print(f"Run  python scripts/check_polar_orientation.py --pole {args.pole}  first.")
        return 1
    tag = "n" if dem.pole > 0 else "s"
    out_dir = Path(args.out) / f"slope_map_{tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    nbl, nbs = (dem.lines - 1) // 2, (dem.samples - 1) // 2        # blocks whose centre's neighbours are on the map
    T = args.tile
    tiles, written = [], 0
    hist = np.zeros(91, np.int64)
    for tr in range((nbl + T - 1) // T):
        for tc in range((nbs + T - 1) // T):
            bi, bj = np.mgrid[tr * T:(tr + 1) * T, tc * T:(tc + 1) * T]
            lc, sc = block_centre(bi, bj)
            lat, lon = dem.latlon(lc, sc)
            inside = (np.abs(lat) >= args.min_lat) & (bi < nbl) & (bj < nbs) & (lc >= 1) & (sc >= 1) \
                & (lc <= dem.lines - 2) & (sc <= dem.samples - 2)
            if not inside.any():
                continue
            code = np.full((T, T, 2), MISSING, np.int16)
            n, la, lo = normals_at(dem, lc[inside], sc[inside])
            code[inside] = encode(n, la, lo)
            ok = np.isfinite(n).all(1)
            hist += np.bincount(np.clip(slope_deg(n[ok], la[ok], lo[ok]), 0, 90).astype(int), minlength=91)[:91]
            code.astype("<i2").tofile(out_dir / f"t_{tr}_{tc}.bin")
            tiles.append([tr, tc])
            written += code.nbytes
        print(f"  tile row {tr + 1}/{(nbl + T - 1) // T} ({time.perf_counter() - tic:.0f} s)", flush=True)
    print(f"{len(tiles)} tiles, {written / 1e6:.1f} MB -> {out_dir}")

    # check: decode the stored tiles at random blocks and at thermal.json's points against local_normal afresh
    ln = local_normal()
    rng = np.random.default_rng(7)
    pts = []
    while len(pts) < args.check:
        r = dem.radius_m * 2 * np.tan(np.radians(90 - args.min_lat) / 2) * np.sqrt(rng.random())
        a = rng.random() * 2 * np.pi
        la, lo = dem.latlon(r * np.cos(a) / dem.map_scale_m + dem.line_offset, r * np.sin(a) / dem.map_scale_m + dem.sample_offset)
        pts.append((float(la), float(lo), "random"))
    th_path = DATA / "thermal.json"
    if th_path.exists() and dem.pole < 0:
        pts += [(p["lat"], p["lon"], p["label"]) for p in json.loads(th_path.read_text())["points"] if p.get("terrain")]
    worst, samples, named = 0.0, [], []
    for la, lo, what in pts:
        bi, bj = (int(v) for v in block_of(dem, la, lo))
        tr, tc = bi // T, bj // T
        f = out_dir / f"t_{tr}_{tc}.bin"
        if not f.exists():
            continue
        code = np.fromfile(f, "<i2").reshape(T, T, 2)[bi % T, bj % T]
        if code[0] == MISSING:
            continue
        lc, sc = block_centre(bi, bj)
        cla, clo = (float(v) for v in dem.latlon(lc, sc))
        got = decode(code, cla, clo)
        want = ln(dem, cla, clo)
        d = angle_deg(got, want)
        worst = max(worst, d)
        if len(samples) < 40:
            samples.append({"lat": la, "lon": lo, "normal": [float(v) for v in got]})
        if what != "random":
            named.append({"label": what, "slope_deg": round(float(slope_deg(got, cla, clo)), 3), "err_deg": round(d, 5)})
            print(f"  {what:<36} slope {named[-1]['slope_deg']:6.2f} deg, stored vs afresh {d:.4f} deg")
    passed = worst <= TOL_DEG
    print(f"stored normals vs local_normal afresh at {len(pts)} points: worst {worst:.4f} deg "
          f"({'PASS' if passed else 'FAIL'}, limit {TOL_DEG} deg)")
    cdf = np.cumsum(hist) / max(1, hist.sum())
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
        "dem": dem.name, "pole": args.pole, "tiles_dir": out_dir.name, "map_scale_m": dem.map_scale_m,
        "block_m": 2 * dem.map_scale_m, "lines": dem.lines, "samples": dem.samples, "line_offset": dem.line_offset,
        "sample_offset": dem.sample_offset, "radius_m": dem.radius_m, "x_sign": dem.x_sign, "y_sign": dem.y_sign,
        "min_abs_lat": args.min_lat, "tile": T, "tiles": tiles, "scale": 32767.0, "missing": MISSING,
        "dtype": "int16 little-endian, [block row][block col][east, north component of the normal at the block centre]",
        "definition": "engine/surface/slope_map.py: block = 2 x 2 map pixels, centre line 2 bi + 0.5, sample 2 bj + 0.5; "
                      "normal = build_thermal.local_normal there",
        "why": "scripts/thermal_attribution.py: median browser temperature error 32.2 K -> 14.8 K with this map "
               "(rule fixed before the run: at most half and at most 15 K)",
        "slope_share_below_deg": {str(d): round(float(cdf[d - 1]), 4) for d in (2, 5, 10, 15, 20, 30)},
        "check": {"points": len(pts), "worst_deg": round(worst, 5), "limit_deg": TOL_DEG, "pass": passed, "named": named},
        "check_samples": samples,
    }
    (Path(args.out) / f"slope_map_{tag}.json").write_text(json.dumps(meta, indent=1))
    print(f"-> {Path(args.out) / f'slope_map_{tag}.json'} ({time.perf_counter() - tic:.0f} s)")
    dem.close()
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
