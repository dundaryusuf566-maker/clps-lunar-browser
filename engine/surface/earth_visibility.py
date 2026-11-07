"""Where on the Moon can a lander talk to the Earth directly, and when does it also have sunlight?

For every point of a polar horizon grid (scripts/build_horizon_grid.py) and every hour of a
period, the Earth's centre is compared with the LOLA terrain horizon in its direction, seen from
the point itself (parallax included, as web/src/lib/sky.ts earthAzEl), and the Sun's centre with
the horizon in its direction. Three shares of the period per point:

  * earth: the Earth above the terrain (direct-to-Earth link possible);
  * sun_earth: the Sun and the Earth above the terrain at the same time (power and link together);
  * dsn: the Earth above the terrain and at least one Deep Space Network complex sees the Moon
    above 10 deg (our assumption, engine/surface/ground.py).

These are the same rules the browser's Anywhere page uses for one point (siteAnalysis.ts:
"Earth in view", "Sun up"), so the map and the page can be compared directly.

Pre-registered checks (written 3 November 2026, before any map was computed):

  A. Level sphere (no terrain), over the map's period: Earth in view 100% at (0 N, 0 E), 0% at
     (0 N, 180 E), and strictly between 0 and 100% at (0 N, 90 E) and (0 N, 90 W), where the
     libration carries the Earth over the horizon and back.
  B. Grid against each point's own horizon: at CHECK_POINTS random points of the cap, the share of
     the period with the Earth above the terrain from the interpolated grid horizon minus the share
     from the point's own LOLA horizon. Pass: median |difference| <= CHECK_B_MEDIAN_MAX_PP and the
     90th percentile <= CHECK_B_P90_MAX_PP percentage points, and the grid must beat a flat horizon
     (median |grid - own| < median |flat - own|). The result goes onto the page whether it passes
     or not; the limits are not changed after the data is seen.

Added after check B failed (3 November 2026), written before it was evaluated:

  C. An uncertainty flag. A point is flagged when the Earth-in-view shares of the four grid points
     around it (the ones its horizon is blended from) span more than UNCERTAIN_SPREAD_PP percentage
     points: the terrain changes between them and the blend cannot be trusted. Evaluated on the same
     random points as B. Pass: among unflagged points the 90th percentile of |grid - own| is at most
     CHECK_C_UNFLAGGED_P90_MAX_PP, and at most CHECK_C_FLAGGED_MAX_SHARE of the points are flagged
     (a flag that covers everything says nothing). Check B's result does not change.

Added after B and C (7 November 2026), written before any dense map was computed:

  D. A dense map with no blending: every point of a DENSE_SPACING_KM grid gets its own LOLA horizon
     (scripts/build_comms_dense.py), so the map's value at a place is that of the nearest such
     point. At CHECK_D_POINTS new random points of the cap (seed CHECK_D_SEED), the share of the
     period with the Earth above the terrain from the nearest dense point minus the share from the
     random point's own horizon. Pass: median |difference| <= CHECK_D_MEDIAN_MAX_PP and 90th
     percentile <= CHECK_D_P90_MAX_PP percentage points, and better than a flat horizon. Stricter
     than B on purpose. B and C keep their results.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MOON_R_KM = 1737.4

# --- pre-registered criteria (see the module docstring) -------------------------------------
CHECK_A_POINTS = {"near_centre": (0.0, 0.0), "far_centre": (0.0, 180.0), "east_limb": (0.0, 90.0), "west_limb": (0.0, -90.0)}
CHECK_B_MEDIAN_MAX_PP = 5.0
CHECK_B_P90_MAX_PP = 15.0
CHECK_POINTS = 300
UNCERTAIN_SPREAD_PP = 25.0
CHECK_C_UNFLAGGED_P90_MAX_PP = 15.0
CHECK_C_FLAGGED_MAX_SHARE = 0.30
DENSE_SPACING_KM = 1.0
CHECK_D_MEDIAN_MAX_PP = 2.0
CHECK_D_P90_MAX_PP = 10.0
CHECK_D_POINTS = 300
CHECK_D_SEED = 20261107
CHECK_SEED = 20261103
# the map's period: twelve months from the start of the Griffin-1 forecast window
PERIOD_UTC = ("2026-11-01T00:00:00", "2027-11-01T00:00:00")
STEP_S = 3600.0


def site_frames(lat_deg: np.ndarray, lon_deg: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Up, north, east unit vectors (Moon-fixed) of points, shape (n, 3) each; as sky.ts siteFrame."""
    p, l = np.radians(np.asarray(lat_deg, float)), np.radians(np.asarray(lon_deg, float))
    up = np.stack([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)], axis=-1)
    north = np.stack([-np.sin(p) * np.cos(l), -np.sin(p) * np.sin(l), np.cos(p)], axis=-1)
    east = np.stack([-np.sin(l), np.cos(l), np.zeros_like(l)], axis=-1)
    return up, north, east


def az_el(vec: np.ndarray, up: np.ndarray, north: np.ndarray, east: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth (deg from north, clockwise) and elevation (deg) of vectors vec (n, T, 3) at points (n, 3)."""
    r = np.linalg.norm(vec, axis=-1)
    el = np.degrees(np.arcsin(np.clip(np.einsum("ntk,nk->nt", vec, up) / r, -1, 1)))
    az = np.degrees(np.arctan2(np.einsum("ntk,nk->nt", vec, east), np.einsum("ntk,nk->nt", vec, north))) % 360.0
    return az, el


def horizon_at(H: np.ndarray, az: np.ndarray) -> np.ndarray:
    """Horizon elevation (deg) at azimuths az (n, T) from horizons H (n, n_az) at 360/n_az deg steps,
    linear between steps and periodic, as horizonGrid.ts."""
    n_az = H.shape[1]
    a = (az % 360.0) / (360.0 / n_az)
    i0 = np.floor(a).astype(np.int64) % n_az
    f = a - np.floor(a)
    h0 = np.take_along_axis(H, i0, axis=1)
    h1 = np.take_along_axis(H, (i0 + 1) % n_az, axis=1)
    return h0 * (1 - f) + h1 * f


@dataclass
class Sky:
    """The period's hourly geometry, shared by every point."""
    earth_fixed_km: np.ndarray      # (T, 3) Earth from the Moon's centre, Moon-fixed
    sun_fixed: np.ndarray           # (T, 3) unit
    dsn: np.ndarray                 # (T,) bitmask, the Moon seen from each complex (pole point)


def build_sky(cache, ts: np.ndarray, pole_sign: float) -> Sky:
    """Hourly Earth and Sun in the Moon-fixed frame from an ephemeris cache, and the DSN mask for
    the pole point (it changes by under 0.1 deg of station elevation across a 75-90 deg cap)."""
    from .ground import dsn_mask, site_from_earth_km
    rot = cache.rotation_many("MOON", ts)                                   # J2000 -> Moon-fixed
    earth = np.einsum("nij,nj->ni", rot, cache.position_many("EARTH", "MOON", ts))
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    up_j2000 = np.einsum("nji,j->ni", rot, np.array([0.0, 0.0, pole_sign]))   # rot^T @ up
    dsn = dsn_mask(ts, site_from_earth_km(cache, ts, up_j2000, MOON_R_KM))
    return Sky(earth_fixed_km=earth, sun_fixed=sun, dsn=np.asarray(dsn))


def shares(lat_deg: np.ndarray, lon_deg: np.ndarray, H: np.ndarray | None, sky: Sky, chunk: int = 256) -> dict[str, np.ndarray]:
    """Per point: % of the period with the Earth above the terrain, with Sun and Earth both above,
    and with the Earth above and a DSN complex in view. H (n, n_az) or None for a flat horizon."""
    lat_deg, lon_deg = np.atleast_1d(lat_deg).astype(float), np.atleast_1d(lon_deg).astype(float)
    n = len(lat_deg)
    out = {k: np.empty(n) for k in ("earth", "sun_earth", "dsn")}
    dsn_on = sky.dsn > 0
    for a in range(0, n, chunk):
        b = min(n, a + chunk)
        up, north, east = site_frames(lat_deg[a:b], lon_deg[a:b])
        e_vec = sky.earth_fixed_km[None, :, :] - MOON_R_KM * up[:, None, :]
        e_az, e_el = az_el(e_vec, up, north, east)
        s_vec = np.broadcast_to(sky.sun_fixed[None, :, :], (b - a,) + sky.sun_fixed.shape)
        s_az, s_el = az_el(s_vec, up, north, east)
        if H is None:
            e_up, s_up = e_el >= 0.0, s_el >= 0.0
        else:
            e_up = e_el >= horizon_at(H[a:b], e_az)
            s_up = s_el >= horizon_at(H[a:b], s_az)
        out["earth"][a:b] = 100.0 * e_up.mean(axis=1)
        out["sun_earth"][a:b] = 100.0 * (e_up & s_up).mean(axis=1)
        out["dsn"][a:b] = 100.0 * (e_up & dsn_on[None, :]).mean(axis=1)
    return out


def check_a(sky: Sky) -> dict:
    """Pre-registered check A on a level sphere."""
    names = list(CHECK_A_POINTS)
    lat = np.array([CHECK_A_POINTS[k][0] for k in names])
    lon = np.array([CHECK_A_POINTS[k][1] for k in names])
    pct = dict(zip(names, (float(v) for v in shares(lat, lon, None, sky)["earth"])))
    ok = (pct["near_centre"] == 100.0 and pct["far_centre"] == 0.0
          and 0.0 < pct["east_limb"] < 100.0 and 0.0 < pct["west_limb"] < 100.0)
    return {"earth_in_view_pct": {k: round(v, 2) for k, v in pct.items()}, "pass": bool(ok),
            "criterion": "level sphere: 100% at 0N 0E, 0% at 0N 180E, strictly between at 0N 90E and 0N 90W"}


def judge_b(d_grid: np.ndarray, d_flat: np.ndarray, median_max: float = CHECK_B_MEDIAN_MAX_PP,
            p90_max: float = CHECK_B_P90_MAX_PP) -> dict:
    """Pre-registered check B (or D, with its limits) from |map - own| and |flat - own| (pp)."""
    d_grid, d_flat = np.abs(np.asarray(d_grid, float)), np.abs(np.asarray(d_flat, float))
    med, p90, med_flat = float(np.median(d_grid)), float(np.percentile(d_grid, 90)), float(np.median(d_flat))
    ok = med <= median_max and p90 <= p90_max and med < med_flat
    return {"median_pp": round(med, 2), "p90_pp": round(p90, 2), "max_pp": round(float(np.max(d_grid)), 2),
            "flat_median_pp": round(med_flat, 2), "flat_p90_pp": round(float(np.percentile(d_flat, 90)), 2),
            "pass": bool(ok),
            "criterion": f"median <= {median_max:g} pp, 90th percentile <= {p90_max:g} pp, "
                         "and median below a flat horizon's"}


def judge_d(d_dense: np.ndarray, d_flat: np.ndarray) -> dict:
    """Pre-registered check D: as B, with D's stricter limits."""
    return judge_b(d_dense, d_flat, CHECK_D_MEDIAN_MAX_PP, CHECK_D_P90_MAX_PP)


def neighbour_spread(E: np.ndarray, x0: float, sp: float, X: float, Y: float) -> float:
    """Max - min of the map's values E (n, n; NaN = no grid point) at the four grid points around plane
    point (X, Y), the ones interp_grid blends; NaN if none. As commsMap.ts spreadNear."""
    c0, r0 = int(np.floor((X - x0) / sp)), int(np.floor((Y - x0) / sp))
    v = [E[r, c] for r, c in ((r0, c0), (r0, c0 + 1), (r0 + 1, c0), (r0 + 1, c0 + 1))
         if 0 <= r < E.shape[0] and 0 <= c < E.shape[1] and not np.isnan(E[r, c])]
    return float(max(v) - min(v)) if v else float("nan")


def judge_c(d_grid: np.ndarray, flagged: np.ndarray) -> dict:
    """Pre-registered check C from |grid - own| (pp) and the flag at the same points."""
    d, f = np.abs(np.asarray(d_grid, float)), np.asarray(flagged, bool)
    un = d[~f]
    p90_un = float(np.percentile(un, 90)) if len(un) else float("nan")
    share = float(f.mean())
    big = d > CHECK_B_P90_MAX_PP
    ok = bool(len(un) > 0 and p90_un <= CHECK_C_UNFLAGGED_P90_MAX_PP and share <= CHECK_C_FLAGGED_MAX_SHARE)
    return {"spread_pp": UNCERTAIN_SPREAD_PP, "flagged_share": round(share, 3),
            "unflagged_p90_pp": round(p90_un, 2), "unflagged_max_pp": round(float(un.max()), 2) if len(un) else None,
            "flagged_p90_pp": round(float(np.percentile(d[f], 90)), 2) if f.any() else None,
            "large_errors": int(big.sum()), "large_errors_flagged": int((big & f).sum()), "pass": ok,
            "criterion": f"flag when the four grid points span > {UNCERTAIN_SPREAD_PP:g} pp; unflagged 90th percentile "
                         f"<= {CHECK_C_UNFLAGGED_P90_MAX_PP:g} pp and at most {100 * CHECK_C_FLAGGED_MAX_SHARE:g}% of points flagged"}


def load_horizon_grid(meta_path: Path) -> tuple[dict, np.ndarray]:
    """The horizon grid written by build_horizon_grid.py: meta and H (n, n, n_az) in deg, NaN where missing."""
    meta = json.loads(Path(meta_path).read_text())
    n, T, n_az = meta["n"], meta["tile"], meta["n_az"]
    H = np.full((n, n, n_az), np.nan, np.float32)
    tdir = Path(meta_path).parent / meta.get("tiles_dir", "horizon_grid_s")
    for ti, tj in meta["tiles"]:
        block = np.frombuffer((tdir / f"t_{ti}_{tj}.bin").read_bytes(), "<i2").reshape(T, T, n_az)
        r0, c0 = ti * T, tj * T
        part = block[: max(0, min(T, n - r0)), : max(0, min(T, n - c0))]
        vals = part.astype(np.float32) * meta["scale_deg"]
        vals[part[:, :, 0] == meta["missing"]] = np.nan
        H[r0:r0 + part.shape[0], c0:c0 + part.shape[1]] = vals
    return meta, H


def interp_grid(H: np.ndarray, x0: float, sp: float, X: float, Y: float) -> np.ndarray | None:
    """Bilinear horizon from the four grid points around plane point (X, Y), missing ones left out
    and the rest reweighted: the browser's rule (horizonGrid.ts) and build_horizon_grid.py's."""
    c, r = (X - x0) / sp, (Y - x0) / sp
    c0, r0 = int(np.floor(c)), int(np.floor(r))
    fc, fr = c - c0, r - r0
    acc, wsum = np.zeros(H.shape[2]), 0.0
    for dr, dc, w in ((0, 0, (1 - fc) * (1 - fr)), (0, 1, fc * (1 - fr)), (1, 0, (1 - fc) * fr), (1, 1, fc * fr)):
        rr, cc = r0 + dr, c0 + dc
        if 0 <= rr < H.shape[0] and 0 <= cc < H.shape[1] and w > 0 and not np.isnan(H[rr, cc, 0]):
            acc += w * H[rr, cc]
            wsum += w
    return acc / wsum if wsum > 0 else None
