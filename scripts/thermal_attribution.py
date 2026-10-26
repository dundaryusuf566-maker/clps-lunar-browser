"""Where does the browser's polar temperature error come from: the ground's tilt or the horizon?

    python scripts/thermal_attribution.py --spice          (~5-10 minutes)

Needs the LOLA map, forecast.json, thermal.json and the south horizon grid. web/tests/
regolith.check.mjs found the browser's temperatures (level ground, horizon blended from the 5 km
grid) 11-84 K off the engine's (each point's own horizon, tilted ground) at the reference point
and the forecast's top 10 candidates. This script runs the engine's regolith model at those
points with direct sunlight only, the same time grid and spin-up as build_thermal.py, in five
versions:

  A  own horizon, tilted ground          (the engine; reproduces thermal.json's "Sun only" curve)
  B  own horizon, level ground           -> what the tilt alone does
  C  grid horizon, tilted ground         -> what the horizon alone does
  D  grid horizon, level ground          (the browser today; reproduces regolith.check.mjs)
  E  grid horizon, tilt from a 240 m map (what the browser would get from a 240 m slope map)

Error of each version: mean |T - T_A| over the landing period (2 h samples), per point; the
summary is the median over the 11 points.

Decision rule, written here before the first run:
  the 240 m slope map is added to the browser if E's median error is at most half of D's AND at
  most 15 K. Otherwise it is not added (the tilt is not the main part, or a map does not capture
  it), and the page keeps its warning; the result is reported either way.
Sanity check (the run is void if it fails): A within 1 K (mean) of thermal.json's
"surface_direct_k" at every point, i.e. this script really reproduces the engine's run. D should
come out close to the browser's errors that regolith.check.mjs printed (compare by eye).

This is an analysis after the browser check; it changes no registered result.
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
from engine.core.constants import AU_KM  # noqa: E402
from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.forecast import get_upcoming  # noqa: E402
from engine.surface.scene3d import disc_fraction  # noqa: E402
from engine.surface.terrain import PolarGrid, compute_horizon  # noqa: E402
from engine.surface.thermal import Column, Regolith, absorbed_flux  # noqa: E402
from engine.validation.illumination import az_el_fixed  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
DAY = 86_400.0
VERSIONS = {"A": "own horizon, tilted", "B": "own horizon, level", "C": "grid horizon, tilted",
            "D": "grid horizon, level (browser)", "E": "grid horizon, 240 m slope map"}
RULE = {"max_ratio_to_D": 0.5, "max_median_k": 15.0}


def _bt():
    spec = importlib.util.spec_from_file_location("build_thermal", ROOT / "scripts" / "build_thermal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class GridHorizon:
    """The browser's lookup (web/src/lib/horizonGrid.ts horizonAt), in Python."""

    def __init__(self, meta_path: Path):
        self.m = json.loads(meta_path.read_text())
        self.dir = meta_path.parent / self.m.get("tiles_dir", "horizon_grid_s")
        self.tiles: dict[tuple[int, int], np.ndarray] = {}

    def plane(self, lat, lon):
        m = self.m
        s = 1 if m["pole"] == "north" else -1
        r = 2 * m["radius_km"] * np.tan(np.pi / 4 - s * np.radians(lat) / 2)
        return m["x_sign"] * r * np.sin(np.radians(lon)), m["y_sign"] * r * np.cos(np.radians(lon))

    def tile(self, tr, tc):
        if (tr, tc) not in self.tiles:
            f = self.dir / f"t_{tr}_{tc}.bin"
            t = self.m["tile"]
            self.tiles[(tr, tc)] = (np.fromfile(f, "<i2").reshape(t, t, self.m["n_az"]) if f.exists() else None)
        return self.tiles[(tr, tc)]

    def elevation_fn(self, lat, lon):
        m = self.m
        x, y = self.plane(lat, lon)
        c, r = (x - m["x0_km"]) / m["spacing_km"], (y - m["x0_km"]) / m["spacing_km"]
        c0, r0 = int(np.floor(c)), int(np.floor(r))
        fc, fr = c - c0, r - r0
        acc, wsum = np.zeros(m["n_az"]), 0.0
        for dr, dc, w in ((0, 0, (1 - fc) * (1 - fr)), (0, 1, fc * (1 - fr)), (1, 0, (1 - fc) * fr), (1, 1, fc * fr)):
            rr, cc = r0 + dr, c0 + dc
            if rr < 0 or cc < 0 or rr >= m["n"] or cc >= m["n"] or w <= 0:
                continue
            t = self.tile(rr // m["tile"], cc // m["tile"])
            if t is None or t[rr % m["tile"], cc % m["tile"], 0] == m["missing"]:
                continue
            acc += w * t[rr % m["tile"], cc % m["tile"]].astype(float) * m["scale_deg"]
            wsum += w
        if wsum == 0:
            return None
        acc /= wsum
        step, n = m["az_step_deg"], m["n_az"]

        def fn(az):
            a = (np.asarray(az, float) % 360) / step
            i = np.floor(a).astype(int) % n
            f = a - np.floor(a)
            return acc[i] * (1 - f) + acc[(i + 1) % n] * f
        return fn


def normal_240(bt, dem: PolarGrid, lat: float, lon: float) -> np.ndarray:
    """The normal a 240 m slope map would hold for the pixel the point falls in: the 120 m map's
    pixels in 2 x 2 blocks, the normal (build_thermal.local_normal) at the block's centre."""
    li, si = (float(v) for v in dem.pixel(lat, lon))
    lc, sc = np.floor(li / 2) * 2 + 0.5, np.floor(si / 2) * 2 + 0.5
    la, lo = dem.latlon(lc, sc)
    return bt.local_normal(dem, float(la), float(lo))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--dem", default=str(ROOT / "data" / "terrain" / "ldem_75s_120m.img"))
    ap.add_argument("--grid", default=str(DATA / "horizon_grid_s.json"))
    ap.add_argument("--out", default=str(DATA / "thermal_attribution.json"))
    args = ap.parse_args()
    tic = time.perf_counter()
    bt = _bt()
    r = Regolith()
    th = json.loads((DATA / "thermal.json").read_text())
    spin_days = float(th["meta"]["spin_up_days"])
    pts = [p for p in th["points"] if p["terrain"]]
    m = get_upcoming("griffin-1")
    gh = GridHorizon(Path(args.grid))
    print(f"{len(pts)} points from thermal.json ({th['meta']['ephemeris']}); grid {gh.m['dem']}, every {gh.m['spacing_km']} km")

    p0 = utc_to_tdb(datetime.fromisoformat(m.landing_first).replace(tzinfo=timezone.utc))
    p1 = utc_to_tdb(datetime.fromisoformat(m.landing_last).replace(tzinfo=timezone.utc))
    w0 = p0 - bt.WINDOW_BEFORE_D * DAY
    s0, s1 = w0 - spin_days * DAY, p1 + 16 * DAY
    cache = cached_for_window(args.spice, s0 - DAY, s1 + DAY, step=3600.0)
    ts = np.arange(s0, s1, 3600.0)
    rot = cache.rotation_many("MOON", ts)
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    au = np.linalg.norm(sun, axis=1) / AU_KM
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)

    dem = PolarGrid.load(args.dem)
    F, info = [], []
    for p in pts:
        lat, lon = p["lat"], p["lon"]
        up = bt.unit_up(lat, lon)
        own = compute_horizon(dem, lat, lon, observer_m=0.0, az_step_deg=0.5, max_dist_km=250.0)
        gfn = gh.elevation_fn(lat, lon)
        if gfn is None:
            print(f"  {p['label']}: not on the grid; skipped")
            continue
        n_t = bt.local_normal(dem, lat, lon)
        n_e = normal_240(bt, dem, lat, lon)
        az, el = az_el_fixed(lat, lon, sun)
        f_own, f_grid = disc_fraction(el - own.elevation(az)), disc_fraction(el - gfn(az))
        for f, n in ((f_own, n_t), (f_own, up), (f_grid, n_t), (f_grid, up), (f_grid, n_e)):
            F.append(absorbed_flux(sun @ n, f, au, r))
        slope = lambda n: float(np.degrees(np.arccos(np.clip(n @ up, -1, 1))))  # noqa: E731
        info.append({"key": p["key"], "label": p["label"], "lat": lat, "lon": lon, "slope_deg": round(slope(n_t), 2),
                     "slope_240_deg": round(slope(n_e), 2), "tilt_diff_deg": round(float(np.degrees(np.arccos(np.clip(n_t @ n_e, -1, 1)))), 2),
                     "sun_hours_own": int((f_own > 0.5).sum()), "sun_hours_grid": int((f_grid > 0.5).sum())})
        print(f"  {p['label']:<36} slope {info[-1]['slope_deg']:5.2f}° (240 m map {info[-1]['slope_240_deg']:5.2f}°)  "
              f"Sun up {info[-1]['sun_hours_own']} h own horizon vs {info[-1]['sun_hours_grid']} h grid ({time.perf_counter() - tic:.0f} s)")
    dem.close()
    F = np.array(F)
    spin = ts < w0
    win = np.flatnonzero(~spin)
    win = np.concatenate([[win[0] - 1], win])
    tw = ts[win]
    col = Column(len(F), r)
    col.spin_up(ts[spin], F[:, spin], cycles=6)
    T = col.run(tw, F[:, win])["surface"]
    rec = tw >= p0
    step = int(th["time"]["step_h"])
    T = T[:, rec][:, ::step]
    nv = len(VERSIONS)
    print(f"\nTemperatures done ({time.perf_counter() - tic:.0f} s). Mean |T - T_A| (K) over {T.shape[1]} samples:")
    print(f"  {'point':<36}" + "".join(f"{k:>8}" for k in VERSIONS) + "   A vs thermal.json")
    rows, sane = [], True
    for i, inf in enumerate(info):
        Ti = T[i * nv:(i + 1) * nv]
        err = {k: float(np.mean(np.abs(Ti[j] - Ti[0]))) for j, k in enumerate(VERSIONS)}
        p = next(q for q in pts if q["key"] == inf["key"])
        ref = np.array(p["surface_direct_k"][:Ti.shape[1]])
        a_vs = float(np.mean(np.abs(Ti[0][:len(ref)] - ref)))
        sane &= a_vs <= 1.0
        rows.append({**inf, "mean_abs_err_k": {k: round(v, 2) for k, v in err.items()}, "a_vs_thermal_json_k": round(a_vs, 3),
                     "min_k": {k: round(float(Ti[j].min()), 1) for j, k in enumerate(VERSIONS)},
                     "max_k": {k: round(float(Ti[j].max()), 1) for j, k in enumerate(VERSIONS)}})
        print(f"  {inf['label'][:36]:<36}" + "".join(f"{err[k]:8.1f}" for k in VERSIONS) + f"   {a_vs:.3f}")
    med = {k: float(np.median([row["mean_abs_err_k"][k] for row in rows])) for k in VERSIONS}
    print("  " + f"{'median':<36}" + "".join(f"{med[k]:8.1f}" for k in VERSIONS))
    for k, v in VERSIONS.items():
        print(f"    {k}: {v}")
    add = med["E"] <= RULE["max_ratio_to_D"] * med["D"] and med["E"] <= RULE["max_median_k"]
    if not sane:
        verdict = "VOID: version A does not reproduce thermal.json (mean difference > 1 K somewhere); send this output"
    elif add:
        verdict = (f"add the 240 m slope map: it brings the median error from {med['D']:.1f} K to {med['E']:.1f} K "
                   f"(rule: at most half and at most {RULE['max_median_k']:g} K)")
    else:
        verdict = (f"do not add the slope map: median error {med['D']:.1f} K -> {med['E']:.1f} K with it, "
                   f"the rule asks at most {RULE['max_ratio_to_D'] * med['D']:.1f} K and {RULE['max_median_k']:g} K")
    print(verdict)
    Path(args.out).write_text(json.dumps({
        "meta": {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
                 "ephemeris": "spice" if args.spice else "analytic", "thermal_json": th["meta"]["generated_utc"],
                 "grid": gh.m["dem"], "spacing_km": gh.m["spacing_km"], "versions": VERSIONS, "rule": RULE,
                 "note": "Analysis after the browser check (web/tests/regolith.check.mjs); direct sunlight only."},
        "median_err_k": {k: round(v, 2) for k, v in med.items()}, "points": rows, "sane": sane, "add_slope_map": bool(add and sane),
        "verdict": verdict}, indent=1))
    print(f"-> {args.out} ({time.perf_counter() - tic:.0f} s)")
    return 0 if sane else 2


if __name__ == "__main__":
    sys.exit(main())
