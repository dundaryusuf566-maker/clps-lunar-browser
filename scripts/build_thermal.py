"""Regolith temperatures at the forecast's candidate sites (web/public/data/thermal.json).

    python scripts/build_thermal.py --spice          (~3-6 minutes)

Needs the LOLA map and web/public/data/forecast.json. For the reference point and
the top 10 candidates: the Sun from the ephemeris, the local tilt of the surface
from the LOLA map, the share of the solar disc above the LOLA horizon, and the
Hayne et al. (2017) regolith model, spun up over the year before the landing
period. Then the light and heat from the surrounding terrain: every direction in
which a point sees terrain is followed to the terrain it hits; that terrain gets
its own sunlight (its own horizon) and temperature, and sends back reflected
sunlight and infrared (engine/surface/radiosity.py, one bounce).

Checks: the regolith model against the Diviner equatorial temperatures, and the
terrain radiation against Ingersoll et al. (1992) on a bowl-shaped crater.

This is an analysis made after the forecast was registered; it is not part of it.
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

from engine import __version__  # noqa: E402
from engine.core.constants import AU_KM  # noqa: E402
from engine.core.time import tdb_to_utc, utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.forecast import get_upcoming  # noqa: E402
from engine.surface.radiosity import (  # noqa: E402
    INGERSOLL1992, bowl_check, diffuse_albedo, first_hits, single_bounce_ratio, sky_samples, surface_normals,
)
from engine.surface.scene3d import crop_rings, disc_fraction, latlon_from_plane, plane_from_fixed  # noqa: E402
from engine.surface.terrain import PolarGrid, compute_horizon  # noqa: E402
from engine.surface.thermal import (  # noqa: E402
    HAYNE2017, LUNATION_S, SIGMA, Column, Regolith, absorbed_flux, albedo,
)
from engine.validation.illumination import az_el_fixed  # noqa: E402

DEM_PATH = ROOT / "data" / "terrain" / "ldem_75s_120m.img"
DATA = ROOT / "web" / "public" / "data"
DAY = 86_400.0
DIVINER = {"noon": 385.0, "midnight": 101.0, "predawn": 95.0}      # Vasavada et al. 2012, via Hayne et al. 2017
DIVINER_SOURCE = HAYNE2017
TOLERANCE_K = 5.0
WINDOW_BEFORE_D = 60.0          # terrain radiation starts this long before the landing period
INGERSOLL_TOL_PCT = {"facets": 1.0, "sampling": 5.0}


def _epoch(day: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(day).replace(tzinfo=timezone.utc))


def equator_check(r: Regolith) -> dict:
    """Flat equatorial soil at 1 AU, no obliquity: the Diviner 'typical' curve."""
    P = LUNATION_S
    t = np.arange(0, P + 1, P / 1440)
    h = 2 * np.pi * t / P
    F = absorbed_flux(np.cos(h), 1.0, 1.0, r)[None, :]
    col = Column(1, r)
    residual = col.spin_up(t, F, cycles=8)[-1]
    T = col.run(t, F)["surface"][0]
    lt = (h / (2 * np.pi) * 24 + 12) % 24
    at = lambda hour: float(T[np.argmin(np.abs(lt - hour))])   # noqa: E731
    model = {"noon": at(12.0), "midnight": at(0.0), "predawn": at(5.9)}
    order = np.argsort(lt)
    keep = order[:: max(1, len(order) // 240)]
    return {
        "model": {k: round(v, 2) for k, v in model.items()},
        "diviner": DIVINER, "tolerance_k": TOLERANCE_K, "source": DIVINER_SOURCE,
        "pass": all(abs(model[k] - DIVINER[k]) <= TOLERANCE_K for k in DIVINER),
        "spin_up_residual_k": round(residual, 3),
        "curve": [[round(float(lt[i]), 3), round(float(T[i]), 2)] for i in keep],
    }


def local_normal(dem: PolarGrid, lat: float, lon: float) -> np.ndarray:
    """Outward normal of the surface over two map pixels either side (Moon-fixed)."""
    li, si = (float(v) for v in dem.pixel(lat, lon))

    def xyz(line, sample):
        la, lo = dem.latlon(line, sample)
        rr = float(dem.value(float(la), float(lo))[0]) / 1000.0
        p, q = np.radians(float(la)), np.radians(float(lo))
        return rr * np.array([np.cos(p) * np.cos(q), np.cos(p) * np.sin(q), np.sin(p)])

    dx = xyz(li, si + 1) - xyz(li, si - 1)
    dy = xyz(li + 1, si) - xyz(li - 1, si)
    n = np.cross(dx, dy)
    n /= np.linalg.norm(n)
    p, q = np.radians(lat), np.radians(lon)
    up = np.array([np.cos(p) * np.cos(q), np.cos(p) * np.sin(q), np.sin(p)])
    return n if np.dot(n, up) > 0 else -n


def unit_up(lat: float, lon: float) -> np.ndarray:
    p, q = np.radians(lat), np.radians(lon)
    return np.array([np.cos(p) * np.cos(q), np.cos(p) * np.sin(q), np.sin(p)])


def forcing(dem, lat, lon, sun_dirs, sun_au, r: Regolith, terrain: bool = True) -> dict:
    """Direct sunlight absorbed at a point, with the pieces the terrain radiation needs."""
    up = unit_up(lat, lon)
    mask = None
    if terrain:
        mask = compute_horizon(dem, lat, lon, observer_m=0.0, az_step_deg=0.5, max_dist_km=250.0)
        az, el = az_el_fixed(lat, lon, sun_dirs)
        f = disc_fraction(el - mask.elevation(az))
        n = local_normal(dem, lat, lon)
    else:
        f = disc_fraction(np.degrees(np.arcsin(np.clip(sun_dirs @ up, -1, 1))))
        n = up
    slope = float(np.degrees(np.arccos(np.clip(np.dot(n, up), -1, 1))))
    radius = float(dem.value(lat, lon)[0]) / 1000.0
    sun_el = np.degrees(np.arcsin(np.clip(sun_dirs @ up, -1, 1)))
    return {"F": absorbed_flux(sun_dirs @ n, f, sun_au, r), "slope": slope, "normal": n, "mask": mask,
            "dni": f * r.S / sun_au ** 2, "sun_el": sun_el,
            "up": up, "radius_km": radius}


def terrain_hits(dem, grids, hs, site: dict, sun_dirs, az_step: float, bands: int):
    """Terrain a point sees: weights w, and for each hit the share of the solar disc
    above its own horizon and cos(incidence) on its surface, over time."""
    dirs, w = sky_samples(site["up"], site["normal"], site["mask"].elevation, az_step_deg=az_step, bands=bands)
    n_t = len(sun_dirs)
    if len(w) == 0:
        return np.zeros(0), np.zeros((0, n_t), np.float32), np.zeros((0, n_t), np.float32)
    pts, ok = first_hits(grids, hs, site["up"] * (site["radius_km"] + 0.001), dirs)
    pts, w = pts[ok], w[ok]
    nh = surface_normals(grids, hs, pts)
    lat, lon = latlon_from_plane(*plane_from_fixed(pts))
    f_all = np.empty((len(w), n_t), np.float32)
    c_all = np.empty((len(w), n_t), np.float32)
    for i, (la, lo, n) in enumerate(zip(lat, lon, nh)):
        m = compute_horizon(dem, float(la), float(lo), observer_m=0.0, az_step_deg=2.0, max_dist_km=150.0, step_m=240.0)
        az, el = az_el_fixed(float(la), float(lo), sun_dirs)
        f_all[i] = disc_fraction(el - m.elevation(az))
        c_all[i] = sun_dirs @ n
    return w, f_all, c_all


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--dem", default=str(DEM_PATH))
    ap.add_argument("--forecast", default=str(DATA / "forecast.json"))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--spinup-days", type=float, default=365.0)
    ap.add_argument("--az-step", type=float, default=4.0, help="terrain directions: azimuth step (deg)")
    ap.add_argument("--bands", type=int, default=2, help="terrain directions: elevation bands per azimuth")
    ap.add_argument("--out", default=str(DATA / "thermal.json"))
    args = ap.parse_args()
    tic = time.perf_counter()
    r = Regolith()

    eq = equator_check(r)
    print("Diviner equatorial check (Vasavada et al. 2012 via Hayne et al. 2017):")
    for k in DIVINER:
        print(f"  {k:<9} model {eq['model'][k]:6.1f} K   Diviner ~{DIVINER[k]:.0f} K")
    print(f"  {'PASS' if eq['pass'] else 'FAIL'} (tolerance {TOLERANCE_K:g} K)")
    bowl = bowl_check(alpha=r.A0, eps=r.emissivity, S=r.S)
    bowl["facets"]["pass"] = abs(bowl["facets"]["diff_pct"]) <= INGERSOLL_TOL_PCT["facets"]
    bowl["sampling"]["pass"] = abs(bowl["sampling"]["diff_pct"]) <= INGERSOLL_TOL_PCT["sampling"]
    bowl["tolerance_pct"] = INGERSOLL_TOL_PCT
    print(f"Ingersoll et al. (1992) bowl, d/D {bowl['depth_to_diameter']}, Sun {bowl['sun_el_deg']} deg:")
    print(f"  facet radiosity: shadow {bowl['facets']['shadow_t_k']} K vs {bowl['facets']['ingersoll_t_k']} K "
          f"({bowl['facets']['diff_pct']:+.2f}%) {'PASS' if bowl['facets']['pass'] else 'FAIL'}")
    print(f"  one-point sampling: {bowl['sampling']['flux_w_m2']} vs {bowl['sampling']['one_bounce_w_m2']} W/m2 "
          f"({bowl['sampling']['diff_pct']:+.2f}%) {'PASS' if bowl['sampling']['pass'] else 'FAIL'}")

    m = get_upcoming("griffin-1")
    fc = json.loads(Path(args.forecast).read_text())
    reg = fc.get("region") or {}
    ref = (reg.get("references") or [{}])[0]
    pts = [{"key": "ref", "label": m.reference_name, "lat": m.reference_lat, "lon": m.reference_lon,
            "best_slot": ref.get("best_slot")}]
    for k, p in enumerate((reg.get("top") or [])[:args.top], 1):
        pts.append({"key": str(k), "label": f"Candidate {k}", "lat": p["lat"], "lon": p["lon"], "best_slot": p.get("best_slot")})

    p0, p1 = _epoch(m.landing_first), _epoch(m.landing_last)
    w0 = p0 - WINDOW_BEFORE_D * DAY
    s0, s1 = w0 - args.spinup_days * DAY, p1 + 16 * DAY
    cache = cached_for_window(args.spice, s0 - DAY, s1 + DAY, step=3600.0)
    ts = np.arange(s0, s1, 3600.0)
    rot = cache.rotation_many("MOON", ts)
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    au = np.linalg.norm(sun, axis=1) / AU_KM
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    spin = ts < w0
    win = np.flatnonzero(~spin)
    win = np.concatenate([[win[0] - 1], win])            # continue from the end of the spin-up window
    tw = ts[win]

    dem = PolarGrid.load(args.dem)
    sites = [forcing(dem, p["lat"], p["lon"], sun, au, r) for p in pts]
    flat = forcing(dem, m.reference_lat, m.reference_lon, sun, au, r, terrain=False)
    print(f"\nDirect sunlight ready for {len(pts)} points ({time.perf_counter() - tic:.0f} s)")

    # terrain each point sees, and its own sunlight
    grids, _ = crop_rings(dem, *m.region_center, inner_half_km=m.region_half_km + 1.0)
    hs = [g.heights_km() for g in grids]
    W, Fd, Ch, owner = [], [], [], []
    for k, (p, st) in enumerate(zip(pts, sites)):
        w, fd, C = terrain_hits(dem, grids, hs, st, sun[win], args.az_step, args.bands)
        W.append(w)
        Fd.append(fd)
        Ch.append(C)
        owner += [k] * len(w)
        st["f_terrain"] = float(w.sum())
        st["hits"] = int(len(w))
        print(f"  {p['label']:<40} sees terrain over {100 * st['f_terrain']:.2f}% of its sky ({len(w)} directions)")
    dem.close()
    W, Fd, Ch, owner = np.concatenate(W), np.vstack(Fd), np.vstack(Ch), np.array(owner)
    print(f"  {len(W)} terrain points in all ({time.perf_counter() - tic:.0f} s); their temperatures:")

    # temperatures of the terrain points (direct sunlight only), over the window
    Fh = absorbed_flux(Ch, Fd, au[win], r)                             # absorbed by each terrain point
    Eh = np.clip(Ch, 0, None) * Fd * (r.S / au[win] ** 2)              # sunlight falling on it
    hcol = Column(len(W), r)
    lead = tw < p0
    hcol.spin_up(tw[lead], Fh[:, lead], cycles=3)
    Th = hcol.run(tw, Fh)["surface"]
    a_diff = diffuse_albedo(r)
    vis = albedo(np.arccos(np.clip(Ch, 0, 1)), r) * Eh                 # reflected sunlight leaving each terrain point
    ir = r.emissivity * SIGMA * Th ** 4                                  # infrared leaving it
    Qx = np.zeros((len(pts) + 1, len(tw)))
    for k in range(len(pts)):
        sel = owner == k
        Qx[k] = (1 - a_diff) * (W[sel] @ vis[sel]) + r.emissivity * (W[sel] @ ir[sel])
    print(f"  terrain done ({time.perf_counter() - tic:.0f} s); diffuse albedo {a_diff:.3f}")

    # the points themselves: spin-up on direct sunlight, then the window with and without the terrain
    F = np.array([st["F"] for st in sites] + [flat["F"]])
    col = Column(len(F), r)
    residual = col.spin_up(ts[spin], F[:, spin], cycles=6)
    twin = Column(len(F), r, col.g)
    twin.T = col.T.copy()
    res = col.run(tw, F[:, win] + Qx, depths_m=(0.1,))
    res0 = twin.run(tw, F[:, win])
    rec = tw >= p0
    Ts, Td, T0 = res["surface"][:, rec], res["depth"][0.1][:, rec], res0["surface"][:, rec]
    tk = tw[rec]
    Qk = Qx[:, rec]
    print(f"  spin-up residual (deep mean, last pass) {residual[-1]:.2f} K; {time.perf_counter() - tic:.0f} s")

    step = 2
    out_pts = []
    idx = win[rec]                                       # hourly indices of the recorded period
    hours = float(np.median(np.diff(tk))) / 3600.0

    def window_stats(T, start_iso, dni):
        if not start_iso:
            return None
        e = utc_to_tdb(datetime.fromisoformat(start_iso.replace("Z", "+00:00")))
        w = (tk >= e) & (tk <= e + 14 * DAY)
        if not w.any():
            return None
        first = int(np.flatnonzero(w)[0])
        return {"start_utc": start_iso, "min_k": round(float(T[w].min()), 1), "max_k": round(float(T[w].max()), 1),
                "mean_k": round(float(T[w].mean()), 1), "hours_below_150k": int((T[w] < 150).sum()),
                # consistency with the forecast: its landing rule wants the Sun up at the slot
                "sun_up_at_start": bool(dni[first] > 1.0), "shadow_hours": round(float((dni[w] <= 1.0).sum() * hours), 1)}

    def st_dni(k):
        return (sites[k] if k < len(sites) else flat)["dni"][idx]

    def st_el(k):
        return (sites[k] if k < len(sites) else flat)["sun_el"][idx]

    allp = pts + [{"key": "ref-flat", "label": f"{m.reference_name}, flat ground, no terrain",
                   "lat": m.reference_lat, "lon": m.reference_lon, "best_slot": ref.get("best_slot")}]
    print("\n  point                                       with terrain light & heat   (direct sunlight only)")
    for k, p in enumerate(allp):
        T = Ts[k]
        st = sites[k] if k < len(sites) else {"slope": 0.0, "f_terrain": 0.0, "hits": 0}
        f = st["f_terrain"]
        out_pts.append({
            **{kk: p[kk] for kk in ("key", "label", "lat", "lon")},
            "slope_deg": round(st["slope"], 2), "terrain": k < len(pts),
            "terrain_view_factor": round(f, 4), "terrain_directions": st["hits"],
            "missing_bounces_pct": round(100 * (1 - single_bounce_ratio(f, r.A0, r.emissivity)), 2) if f > 0 else 0.0,
            "terrain_flux_max_w_m2": round(float(Qk[k].max()), 2), "terrain_flux_mean_w_m2": round(float(Qk[k].mean()), 3),
            "min_k": round(float(T.min()), 1), "max_k": round(float(T.max()), 1), "mean_k": round(float(T.mean()), 1),
            "min_direct_k": round(float(T0[k].min()), 1), "max_direct_k": round(float(T0[k].max()), 1),
            "depth_10cm_mean_k": round(float(Td[k].mean()), 1),
            "after_best_slot": window_stats(T, p.get("best_slot"), st_dni(k)),
            "surface_k": np.round(T[::step], 1).tolist(),
            "surface_direct_k": np.round(T0[k][::step], 1).tolist(),
            # sunlight a Sun-tracking vertical panel would get (W m^-2, solar disc above the terrain) and the Sun's elevation
            "dni_w_m2": np.round(st_dni(k)[::step], 1).tolist(),
            "sun_el_deg": np.round(st_el(k)[::step], 2).tolist(),
        })
        s = out_pts[-1]
        print(f"  {p['label'][:42]:<42}  {s['min_k']:6.1f} .. {s['max_k']:6.1f} K    ({s['min_direct_k']:.1f} .. "
              f"{s['max_direct_k']:.1f} K), terrain {100 * f:.2f}% of the sky")
        a = s["after_best_slot"]
        if a:
            print(f"  {'':42}  14 days from its best slot: {a['shadow_hours']:.0f} h in shadow"
                  + ("" if a["sun_up_at_start"] else "  ** Sun below the terrain at the slot: check DEM / horizon settings **"))

    doc = {
        "meta": {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                 "engine_version": __version__, "ephemeris": "spice" if args.spice else "analytic",
                 "dem": Path(args.dem).stem.upper(), "forecast_sha256": fc.get("meta", {}).get("sha256"),
                 "regolith": r.to_dict(),
                 "grid": {"layers": len(col.g.z), "first_layer_mm": round(float(col.g.h[0]) * 1000, 2),
                          "bottom_m": round(float(col.g.z[-1]), 3)},
                 "spin_up_days": args.spinup_days, "spin_up_residual_k": round(residual[-1], 3),
                 "terrain_radiation": {"az_step_deg": args.az_step, "bands": args.bands, "diffuse_albedo": round(a_diff, 4),
                                       "terrain_points": int(len(W)), "start_days_before": WINDOW_BEFORE_D,
                                       "hit_horizons": "2 deg azimuth, 150 km, 240 m steps", "source": INGERSOLL1992},
                 "notes": [
                     "Hayne et al. (2017) regolith model, standard parameters (Table A1), not fitted to these sites.",
                     "Sunlight: ephemeris Sun distance and direction, surface tilt from LOLA (240 m baseline), "
                     "share of the solar disc above the LOLA horizon.",
                     "Terrain light and heat: every direction in which a point sees terrain is followed to the terrain "
                     "it hits; that terrain's own sunlight and temperature give the reflected sunlight and infrared it "
                     "sends back. One bounce: light the terrain receives from other terrain is left out.",
                     "Made after the forecast was registered; not part of it.",
                 ]},
        "equator_check": eq,
        "bowl_check": bowl,
        "time": {"t0_utc": tdb_to_utc(float(tk[0])).isoformat(timespec="minutes"), "step_h": step,
                 "n": len(out_pts[0]["surface_k"]), "landing_period_utc": [m.landing_first, m.landing_last]},
        "points": out_pts,
    }
    Path(args.out).write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
    print(f"-> {args.out} ({time.perf_counter() - tic:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
