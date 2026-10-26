"""Where does the difference to Diviner's polar temperatures come from? (analysis after the check)

    python scripts/diviner_polar_diagnose.py --spice        (after diviner_polar_check.py; ~15-25 minutes)

The pass/fail result of scripts/diviner_polar_check.py was fixed before Diviner was
read and is not changed by anything here. This script only explains it, and writes
web/public/data/diviner_polar_diagnostics.json, shown separately on the Validation page.

1. Split the registered comparison by illumination: bins where both the model and
   Diviner are in shadow or night, both sunlit, or one sunlit and the other not.
2. Compare like with like. Diviner's value is the radiance-weighted mean of a 240 m
   bin; the registered check compared it with the model at one point. Here the model
   is run at 3 x 3 points spread over the bin itself (80 m apart, centred on the bin's
   own x/y read from the archive), each with its own LOLA horizon and slope, and the
   bin temperature is the radiance-weighted mean, T = <T^4>^(1/4), as Diviner's is.
   Nothing is fitted: the only choice is the bin, whose size is Diviner's.

What this cannot test: roughness below the 120 m LOLA map, and the albedo law at
grazing Sun. Both would raise sunlit temperatures; the output says how much of the
difference is left for them.
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
sys.path.insert(0, str(ROOT / "scripts"))

from build_thermal import forcing  # noqa: E402
from diviner_polar_check import CACHE, DAY, DEM_PATH, SPAN, _epoch  # noqa: E402

from engine import __version__  # noqa: E402
from engine.core.constants import AU_KM  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.surface.terrain import PolarGrid  # noqa: E402
from engine.surface.thermal import Column, Regolith  # noqa: E402
from engine.validation.diviner_pcp import R_KM, HttpRange, detect_layout, find_bin, latlon_from_xy, ltim_url  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
CENTRES = CACHE.with_name("diviner_pcp_bins.json")
SUB_M = (-80.0, 0.0, 80.0)                  # 3 x 3 points over the 240 m bin

# illumination classes (chosen after seeing the data; descriptive only)
DARK_K, LIT_K = 100.0, 150.0


def classify(m: float, d: float) -> str:
    if m < DARK_K and d < DARK_K:
        return "both_dark"
    if m > LIT_K and d > LIT_K:
        return "both_lit"
    if m < DARK_K and d > 120.0:
        return "model_dark"
    if m > LIT_K and d < DARK_K:
        return "diviner_dark"
    return "between"


def breakdown(rows: list[tuple[float, float]]) -> dict:
    out = {}
    for c in ("both_dark", "both_lit", "model_dark", "diviner_dark", "between"):
        dd = [m - d for m, d in rows if classify(m, d) == c]
        out[c] = {"n": len(dd), "median_k": round(float(np.median(dd)), 1) if dd else None}
    return out


def bin_centres(pts: list[dict]) -> dict:
    """The Diviner bin each point was compared with, and which local-time files used that same bin.

    In a file where the point's own bin has no data, the registered check took the nearest bin
    within 0.75 bins, so the bin can differ between files. The point's own bin is the nearest one
    over all files (smallest distance in data/cache/diviner_pcp_points.json); its x/y are read again
    from that file, and the temperature read must match the cached one, or the script stops."""
    reads = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    have = json.loads(CENTRES.read_text()) if CENTRES.exists() else {}
    have = {k: v for k, v in have.items() if isinstance(v, dict) and v.get("v") == 2}     # drop the first, flawed format
    key = lambda p: f"{p['lat']:.5f},{p['lon']:.5f}"            # noqa: E731
    out = {}
    lay = None
    for p in pts:
        hits = {u: v for u, v in reads.items() if u.startswith("http") and isinstance(v, dict) and v.get(key(p))}
        if not hits:
            print(f"  {p['label'][:40]:<40} no Diviner reads in the cache: run diviner_polar_check.py first")
            out[p["key"]] = None
            continue
        best_url = min(hits, key=lambda u: hits[u][key(p)][1])
        T_best, d_best = hits[best_url][key(p)]
        same = sorted(u for u in hits if abs(hits[u][key(p)][1] - d_best) < 1e-6)
        if key(p) not in have or have[key(p)]["url"] != best_url:
            h = HttpRange(best_url)
            try:
                if lay is None:
                    lay = detect_layout(h, h.size())
                    if not lay.name.startswith("stereographic x=+sin, y=+cos"):
                        raise ValueError(f"bin centres assume the layout seen so far, not {lay.name}")
                hit = find_bin(h, h.size() // lay.record - 1, lay, p["lat"], p["lon"], with_row=True)
            finally:
                h.close()
            if hit is None or abs(hit[0] - T_best) > 0.05 or abs(hit[1] - d_best) > 1e-6:
                raise RuntimeError(f"{p['label']}: re-reading the bin did not give the cached value ({hit} vs {T_best}, {d_best})")
            have[key(p)] = {"v": 2, "x": hit[2][0], "y": hit[2][1], "dist": d_best, "url": best_url}
            CENTRES.parent.mkdir(parents=True, exist_ok=True)
            CENTRES.write_text(json.dumps(have))
        c = have[key(p)]
        out[p["key"]] = [c["x"], c["y"], c["dist"], same]
        print(f"  {p['label'][:40]:<40} own bin {c['dist']:.2f} bins from the point, used in {len(same)} of {len(hits)} files")
    return out


def bin_model(pts: list[dict], centres: dict, spice: bool, dem_path: Path, bins: list[int]) -> dict:
    r = Regolith()
    s0, s1 = _epoch(SPAN[0]), _epoch(SPAN[1])
    spin0 = s0 - 365.0 * DAY
    cache = cached_for_window(spice, spin0 - DAY, s1 + DAY, step=3600.0)
    ts = np.arange(spin0, s1, 3600.0)
    rot = cache.rotation_many("MOON", ts)
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    au = np.linalg.norm(sun, axis=1) / AU_KM
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    dem = PolarGrid.load(dem_path)
    owner, F, info = [], [], {}
    tic = time.perf_counter()
    for k, p in enumerate(pts):
        c = centres.get(p["key"])
        if c is None:
            continue
        x0, y0 = c[0], c[1]
        slopes = []
        for dx in SUB_M:
            for dy in SUB_M:
                lat, lon = latlon_from_xy(x0 + dx / 1000.0 / R_KM, y0 + dy / 1000.0 / R_KM)
                st = forcing(dem, lat, lon, sun, au, r)
                F.append(st["F"])
                owner.append(k)
                slopes.append(st["slope"])
        info[p["key"]] = {"slope_min_deg": round(min(slopes), 1), "slope_max_deg": round(max(slopes), 1)}
        print(f"  {p['label'][:40]:<40} 9 points over the bin, slopes {min(slopes):.1f}..{max(slopes):.1f} deg "
              f"({time.perf_counter() - tic:.0f} s)", flush=True)
    dem.close()
    F = np.array(F)
    owner = np.array(owner)
    spin = ts < s0
    col = Column(len(F), r)
    col.spin_up(ts[spin], F[:, spin], cycles=4)
    keep = np.flatnonzero(~spin)
    keep = np.concatenate([[keep[0] - 1], keep])
    T4 = col.run(ts[keep], F[:, keep])["surface"][:, 1:] ** 4
    s = sun[keep[1:]]
    lon_ss = np.degrees(np.arctan2(s[:, 1], s[:, 0]))
    summer = s[:, 2] < 0
    out = {}
    for k, p in enumerate(pts):
        sel_pts = owner == k
        if not sel_pts.any():
            continue
        Tb4 = T4[sel_pts].mean(axis=0)                                  # radiance-weighted over the bin, each hour
        lt = (12.0 + (p["lon"] - lon_ss) / 15.0) % 24.0
        num = np.floor(lt / 0.25).astype(int) + 1
        for season, sel in (("sum", summer), ("win", ~summer)):
            for b in bins:
                m = sel & (num == b)
                out[(p["key"], season, b)] = float(np.mean(Tb4[m]) ** 0.25) if m.any() else None
    return out, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--dem", default=str(DEM_PATH))
    ap.add_argument("--check", default=str(DATA / "diviner_polar.json"), help="output of diviner_polar_check.py")
    ap.add_argument("--out", default=str(DATA / "diviner_polar_diagnostics.json"))
    args = ap.parse_args()
    tic = time.perf_counter()
    reg = json.loads(Path(args.check).read_text())
    pts = [{k: p[k] for k in ("key", "label", "lat", "lon")} for p in reg["points"]]
    bins = reg["meta"]["bins"]

    point_rows = [(m, d) for p in reg["points"] for s in ("sum", "win") for _, d, m in p["seasons"][s]
                  if d is not None and m is not None]
    print("1. The registered comparison, split by illumination (model - Diviner):")
    b0 = breakdown(point_rows)
    for c, v in b0.items():
        print(f"   {c:<13} n {v['n']:3d}  median {v['median_k']} K")

    print("2. Diviner bin centres:")
    centres = bin_centres(pts)
    print(f"3. Model over each 240 m bin (3 x 3 points), {SPAN[0]} .. {SPAN[1]} hourly:")
    mod, info = bin_model(pts, centres, args.spice, Path(args.dem), bins)

    out_pts, bin_rows, same_point_rows = [], [], []
    for p in reg["points"]:
        series = {}
        c = centres.get(p["key"])
        same = set(c[3]) if c else set()
        for s in ("sum", "win"):
            ser = []
            for (lt, d, m), b in zip(p["seasons"][s], bins):
                mb = mod.get((p["key"], s, b)) if ltim_url(s, b) in same else None    # only where the own bin was used
                ser.append([lt, d, m, None if mb is None else round(mb, 1)])
                if d is not None and mb is not None:
                    bin_rows.append((mb, d))
                    same_point_rows.append((m, d))
            series[s] = ser
        dd = [r[3] - r[1] for s in ("sum", "win") for r in series[s] if r[1] is not None and r[3] is not None]
        out_pts.append({"key": p["key"], "label": p["label"], "seasons": series, **info.get(p["key"], {}),
                        "bin_dist": None if c is None else round(c[2], 2), "own_bin_files": len(same),
                        "median_abs_k": round(float(np.median(np.abs(dd))), 1) if dd else None,
                        "bias_k": round(float(np.mean(dd)), 1) if dd else None})
    b1 = breakdown(bin_rows)
    b0s = breakdown(same_point_rows)
    med1 = float(np.median([abs(m - d) for m, d in bin_rows])) if bin_rows else None
    med0s = float(np.median([abs(m - d) for m, d in same_point_rows])) if same_point_rows else None
    print("\n   point model on the same bins (for a fair comparison):")
    for c, v in b0s.items():
        print(f"   {c:<13} n {v['n']:3d}  median {v['median_k']} K")
    print("\n   bin model, split the same way:")
    for c, v in b1.items():
        print(f"   {c:<13} n {v['n']:3d}  median {v['median_k']} K")
    print(f"\nRegistered check: median |d| {reg['summary']['median_abs_k']} K over {reg['summary']['n']} bins, "
          f"{reg['summary']['pass'] and 'PASS' or 'FAIL'}.")
    print(f"After the check, on the {len(bin_rows)} bins where each point's own Diviner bin was used: "
          f"point model {med0s and round(med0s, 1)} K, model over the bin {med1 and round(med1, 1)} K (median |d|).")
    doc = {"meta": {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
                    "ephemeris": "spice" if args.spice else "analytic", "dem": Path(args.dem).stem.upper(),
                    "registered_generated_utc": reg["meta"]["generated_utc"], "sub_points_m": list(SUB_M),
                    "classes_k": {"dark_below": DARK_K, "lit_above": LIT_K}},
           "point_breakdown": b0, "bin_breakdown": b1, "same_bins_point_breakdown": b0s,
           "bin_median_abs_k": None if med1 is None else round(med1, 1), "bin_n": len(bin_rows),
           "same_bins_point_median_abs_k": None if med0s is None else round(med0s, 1),
           "points": out_pts}
    Path(args.out).write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
    print(f"-> {args.out} ({time.perf_counter() - tic:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
