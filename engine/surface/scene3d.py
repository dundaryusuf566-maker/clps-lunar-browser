"""3D scene of a landing region: terrain, Sun and Earth, for the browser's 3D view.

The browser draws the LOLA terrain on the curved Moon and lights it from the
ephemeris Sun. Its shadows are not a rendering trick: a GPU shader walks from
every map cell towards the Sun and keeps the highest terrain it passes, the same
horizon geometry as compute_horizon(), then takes the share of the solar disc
above that terrain, the same formula as the energy budget. This module

    * cuts the terrain the shader needs out of the polar map: the region at full
      resolution (120 m), then block means at 360 m out to 100 km and 1.2 km out
      to 250 km, which is how far the engine's horizon masks look;
    * samples the Sun and Earth directions on an hourly grid;
    * computes, at a set of check points, the engine's own sun clearance from
      full-resolution horizon masks, so the page can measure how well its GPU
      shadows agree with the engine;
    * implements the shader's ray march in numpy (march_sun_clear), so the same
      algorithm is tested here against compute_horizon.

Coordinates. Map plane: X, Y in km on the polar stereographic plane (X along
samples, Y along lines, as in PolarGrid). Moon-fixed vectors in km. The 3D scene
uses a local east-north-up frame at the region centre, origin on the 1737.4 km
reference sphere, so the Moon's curvature is in the geometry itself.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .terrain import SOLAR_SEMI_DIAMETER_DEG, PolarGrid, compute_horizon

MOON_R_KM = 1737.4
INVALID_DN = -32768

# Ray march schedule, shared with the GPU shader (web/src/lib/scene3d/shaders.ts):
# start 1.5 map pixels out (as compute_horizon), step 2 % of the distance,
# never finer than the 120 m map nor coarser than the 1.2 km outer grid.
MARCH = {"t0_km": 0.18, "grow": 0.02, "min_step_km": 0.12, "max_step_km": 1.2, "max_km": 250.0}


@dataclass
class SceneGrid:
    """A regular crop of the polar map: heights on X = x0 + i*step, Y = y0 + j*step."""
    x0_km: float
    y0_km: float
    step_km: float
    dn: np.ndarray            # int16 [ny, nx]; INVALID_DN where the map has no data
    scale_m: float
    offset_m: float           # height_m = dn * scale_m + offset_m (above the reference sphere)

    @property
    def shape(self) -> tuple[int, int]:
        return self.dn.shape

    def heights_km(self) -> np.ndarray:
        h = (self.dn.astype(float) * self.scale_m + self.offset_m) / 1000.0
        return np.where(self.dn == INVALID_DN, np.nan, h)

    def sample(self, X: np.ndarray, Y: np.ndarray, h: np.ndarray | None = None) -> np.ndarray:
        """Bilinear height (km) at map-plane points; NaN outside the grid or on missing data."""
        h = self.heights_km() if h is None else h
        ny, nx = h.shape
        c = (np.asarray(X, float) - self.x0_km) / self.step_km
        r = (np.asarray(Y, float) - self.y0_km) / self.step_km
        ok = (c >= 0) & (r >= 0) & (c <= nx - 1) & (r <= ny - 1)
        c0 = np.clip(np.floor(c).astype(np.int64), 0, nx - 2)
        r0 = np.clip(np.floor(r).astype(np.int64), 0, ny - 2)
        fc, fr = np.clip(c - c0, 0, 1), np.clip(r - r0, 0, 1)
        v = (h[r0, c0] * (1 - fc) * (1 - fr) + h[r0, c0 + 1] * fc * (1 - fr)
             + h[r0 + 1, c0] * (1 - fc) * fr + h[r0 + 1, c0 + 1] * fc * fr)
        return np.where(ok, v, np.nan)

    def meta(self) -> dict:
        ny, nx = self.shape
        return {"x0_km": self.x0_km, "y0_km": self.y0_km, "step_km": self.step_km, "nx": nx, "ny": ny,
                "scale_m": self.scale_m, "offset_m": self.offset_m}


# --- projection helpers ---------------------------------------------------------------
def unit(lat_deg, lon_deg) -> np.ndarray:
    p, l = np.radians(lat_deg), np.radians(lon_deg)
    return np.stack([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)], axis=-1)


def enu_basis(lat_deg: float, lon_deg: float) -> np.ndarray:
    """Rows: east, north, up (Moon-fixed unit vectors)."""
    p, l = np.radians(lat_deg), np.radians(lon_deg)
    return np.array([[-np.sin(l), np.cos(l), 0.0],
                     [-np.sin(p) * np.cos(l), -np.sin(p) * np.sin(l), np.cos(p)],
                     [np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)]])


def plane_from_fixed(v: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Map-plane X, Y (km) of the point below a Moon-fixed position (any radius).
    X = 2R tan(pi/4 + lat/2) sin(lon) written without trigonometry: 2R y / (r - z)."""
    v = np.asarray(v, float)
    r = np.linalg.norm(v, axis=-1)
    d = r - v[..., 2]
    return 2 * MOON_R_KM * v[..., 1] / d, -2 * MOON_R_KM * v[..., 0] / d


def latlon_from_plane(X, Y) -> tuple[np.ndarray, np.ndarray]:
    rho = np.hypot(X, Y)
    lat = -90.0 + np.degrees(2 * np.arctan(rho / (2 * MOON_R_KM)))
    return lat, np.degrees(np.arctan2(X, -np.asarray(Y, float)))


def _plane_xy(dem: PolarGrid, line: float, sample: float) -> tuple[float, float]:
    return ((sample - dem.sample_offset) * dem.map_scale_m / 1000.0,
            (line - dem.line_offset) * dem.map_scale_m / 1000.0)


# --- terrain crops -----------------------------------------------------------------------
# (block in map pixels, half size in km): full resolution over the region, then block
# means. The 360 m middle ring matters: at 1.2 km from 41 km out, block means flatten the
# peaks that set distant horizons enough to double the error (tests/test_scene3d.py).
RINGS = ((1, None), (3, 100.0), (10, MARCH["max_km"]))


def crop_rings(dem: PolarGrid, center_lat: float, center_lon: float, inner_half_km: float,
               rings=RINGS) -> tuple[list[SceneGrid], tuple[int, int]]:
    """Squares of the map centred on the pixel nearest the region centre, finest first:
    each ring is (block, half_km), block means of block x block pixels (1 = the map itself);
    half_km None means inner_half_km. Returns (grids, (line, sample) of the centre)."""
    if dem.x_sign != 1.0 or dem.y_sign != -1.0:
        raise ValueError("scene export expects the LOLA projection convention")
    lc, sc = (int(round(float(v))) for v in dem.pixel(center_lat, center_lon))
    s_km = dem.map_scale_m / 1000.0
    out = []
    for block, half_km in rings:
        half_km = inner_half_km if half_km is None else half_km
        m = int(np.ceil(half_km / (block * s_km)))
        half = block // 2                  # block k covers pixels c + k*block - half .. + block - half - 1
        size = (2 * m + 1) * block
        raw = _window(dem, lc - m * block - half, sc - m * block - half, size, size)
        if block == 1:
            dn = raw
        else:
            k = 2 * m + 1
            bad = (raw == INVALID_DN).reshape(k, block, k, block).any(axis=(1, 3))
            mean = np.where(raw == INVALID_DN, 0.0, raw).reshape(k, block, k, block).mean(axis=(1, 3))
            dn = np.where(bad, INVALID_DN, np.round(mean)).astype(np.int16)
        centre_off = (block - 1) / 2.0 - half      # block centre vs its nominal pixel (-0.5 for even blocks)
        x0, y0 = _plane_xy(dem, lc - m * block + centre_off, sc - m * block + centre_off)
        out.append(SceneGrid(x0, y0, block * s_km, dn, dem.scale, dem.offset - dem.radius_m))
    return out, (lc, sc)


def _window(dem: PolarGrid, l0: int, s0: int, nl: int, ns: int) -> np.ndarray:
    out = np.full((nl, ns), INVALID_DN, dtype=np.int16)
    a0, b0 = max(l0, 0), max(s0, 0)
    a1, b1 = min(l0 + nl, dem.lines), min(s0 + ns, dem.samples)
    if a1 > a0 and b1 > b0:
        out[a0 - l0:a1 - l0, b0 - s0:b1 - s0] = np.asarray(dem.data[a0:a1, b0:b1], dtype=np.int16)
    return out


# --- the shader's ray march, in numpy ----------------------------------------------------
def march_steps(march: dict = MARCH) -> np.ndarray:
    t, out = march["t0_km"], []
    while t <= march["max_km"]:
        out.append(t)
        t += min(march["max_step_km"], max(march["min_step_km"], march["grow"] * t))
    return np.array(out)


def disc_fraction(clear_deg) -> np.ndarray:
    """Share of the solar disc above the terrain for a Sun centre `clear_deg` above it."""
    x = np.clip(np.asarray(clear_deg, float) / SOLAR_SEMI_DIAMETER_DEG, -1, 1)
    th = np.arccos(-x)
    return (th - np.sin(th) * np.cos(th)) / np.pi


def sample_grids(grids: list[SceneGrid], hs: list[np.ndarray], X, Y) -> np.ndarray:
    """Height (km) from the finest grid that covers each map-plane point (NaN off all grids)."""
    h = grids[0].sample(X, Y, hs[0])
    for g, hg in zip(grids[1:], hs[1:]):
        h = np.where(np.isfinite(h), h, g.sample(X, Y, hg))
    return h


def march_sun_clear(grids: list[SceneGrid], lat: float, lon: float, sun_dirs: np.ndarray,
                    observer_m: float = 2.0, march: dict = MARCH, early_exit: bool = True,
                    heights: list[np.ndarray] | None = None) -> np.ndarray:
    """Sun elevation minus the terrain horizon towards the Sun (deg) at one point, for
    each Moon-fixed unit Sun direction: walk the ray from the observer towards the Sun
    and keep the highest elevation angle of the terrain below it. Same steps and
    formulas as the GPU shader. `grids` finest first; each point uses the finest
    grid that covers it."""
    hs = heights if heights is not None else [g.heights_km() for g in grids]
    up = unit(lat, lon)
    X0, Y0 = plane_from_fixed(up * MOON_R_KM)
    h_site = float(sample_grids(grids, hs, X0, Y0))
    if not np.isfinite(h_site):
        raise ValueError(f"({lat}, {lon}) is outside the terrain grids")
    r_obs = MOON_R_KM + h_site + observer_m / 1000.0
    O = up * r_obs
    s = np.asarray(sun_dirs, float)
    sin_s = s @ up
    cos_s = np.sqrt(np.maximum(1 - sin_s ** 2, 1e-12))
    h_top = max(float(np.nanmax(h)) for h in hs)
    best = np.full(len(s), -np.inf)
    alive = np.ones(len(s), bool)
    for t in march_steps(march):
        Q = O + t * s
        dr = (2 * t * r_obs * sin_s + t * t) / (np.linalg.norm(Q, axis=1) + r_obs)
        r = r_obs + dr
        X, Y = plane_from_fixed(Q)
        h = sample_grids(grids, hs, X, Y)
        k = (MOON_R_KM + h) / r
        km1 = (h - (h_site + observer_m / 1000.0) - dr) / r
        tan_e = (r_obs * km1 + k * t * sin_s) / (k * t * cos_s)
        ok = alive & np.isfinite(tan_e)
        best = np.where(ok, np.maximum(best, tan_e), best)
        alive &= np.isfinite(h)                              # off the map: nothing further to see
        if early_exit:
            alive &= ~((r - MOON_R_KM > h_top) & (t > -r_obs * sin_s))   # ray above all terrain and rising
        if not alive.any():
            break
    el_s = np.degrees(np.arcsin(np.clip(sin_s, -1, 1)))
    return el_s - np.degrees(np.arctan(best))


def engine_sun_clear(dem: PolarGrid, lat: float, lon: float, sun_dirs: np.ndarray, observer_m: float = 2.0,
                     az_step_deg: float = 0.5, max_dist_km: float = MARCH["max_km"]):
    """The engine's sun clearance: Sun elevation minus a full-resolution horizon mask."""
    from ..validation.illumination import az_el_fixed
    mask = compute_horizon(dem, lat, lon, observer_m=observer_m, az_step_deg=az_step_deg, max_dist_km=max_dist_km)
    az, el = az_el_fixed(lat, lon, sun_dirs)
    return el - mask.elevation(az), mask


def agreement(gpu_clear: np.ndarray, engine_clear: np.ndarray, clamp_deg: float = 1.0,
              edge_deg: float = 0.3) -> dict:
    """How well two sun-clearance series agree. Differences are measured where at least
    one of the two is within +-clamp_deg of the horizon (further out both mean fully lit
    or fully hidden, and the ray march stops early once it has cleared all terrain);
    lit/hidden is compared where the engine is more than edge_deg from the horizon,
    where a 0.5 deg mask step cannot decide."""
    a_raw, b_raw = np.asarray(gpu_clear, float), np.asarray(engine_clear, float)
    ok = np.isfinite(a_raw) & np.isfinite(b_raw)
    a_raw, b_raw = a_raw[ok], b_raw[ok]
    a, b = np.clip(a_raw, -clamp_deg, clamp_deg), np.clip(b_raw, -clamp_deg, clamp_deg)
    near = (np.abs(a_raw) < clamp_deg) | (np.abs(b_raw) < clamp_deg)
    d = np.abs(a - b)[near]
    clear_of_edge = np.abs(b) > edge_deg
    same = (a > 0) == (b > 0)
    fa, fb = disc_fraction(a), disc_fraction(b)
    return {
        "n": int(ok.sum()), "near_horizon": int(near.sum()),
        "median_abs_deg": round(float(np.median(d)), 3) if d.size else None,
        "p95_abs_deg": round(float(np.percentile(d, 95)), 3) if d.size else None,
        "lit_agree_pct": round(100 * float(same[clear_of_edge].mean()), 2) if clear_of_edge.any() else None,
        "lit_compared": int(clear_of_edge.sum()),
        "mean_abs_disc_pct": round(100 * float(np.mean(np.abs(fa - fb))), 2) if a.size else None,
        "clamp_deg": clamp_deg, "edge_deg": edge_deg,
    }
