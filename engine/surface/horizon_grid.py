"""Terrain horizons for the whole polar cap, on a grid, for the website.

compute_horizon() marches every map pixel out to 250 km: right for a handful of
sites, far too slow for tens of thousands of points. Here the same horizon
geometry is evaluated with the step schedule and the block-mean map levels that
the 3D view's shadows already use (scene3d.MARCH, scene3d.RINGS), which were
tested against compute_horizon (tests/test_scene3d.py): the 120 m map near the
point, 360 m block means out to 100 km, 1.2 km beyond. tests/test_horizon_grid.py
compares this fast horizon with compute_horizon again, directly.

The grid: points every `spacing_km` on the polar stereographic plane, inside the
cap the map covers. For any other point the browser interpolates between the four
grid points around it; scripts/build_horizon_grid.py measures, at random points,
how far that interpolated horizon is from the point's own one, and writes the
numbers next to the grid.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .scene3d import MARCH, march_steps
from .terrain import PolarGrid

INVALID_DN = -32768
LEVELS = ((1, 15.0), (3, 100.0), (10, MARCH["max_km"]))     # (block, used out to km)


@dataclass
class Level:
    block: int
    dn: np.ndarray            # int16, block means of the full map (INVALID_DN where any pixel is missing)

    def heights_m(self, li: np.ndarray, si: np.ndarray, dem: PolarGrid) -> np.ndarray:
        """Bilinear height (m above the reference sphere) at full-map pixel coordinates."""
        b = self.block
        c = (si - (b - 1) / 2.0) / b
        r = (li - (b - 1) / 2.0) / b
        ny, nx = self.dn.shape
        ok = (c >= 0) & (r >= 0) & (c <= nx - 1) & (r <= ny - 1)
        c0 = np.clip(np.floor(c).astype(np.int64), 0, nx - 2)
        r0 = np.clip(np.floor(r).astype(np.int64), 0, ny - 2)
        fc, fr = np.clip(c - c0, 0, 1), np.clip(r - r0, 0, 1)
        d = self.dn
        q = [d[r0, c0], d[r0, c0 + 1], d[r0 + 1, c0], d[r0 + 1, c0 + 1]]
        bad = np.zeros(np.shape(c), bool)
        for v in q:
            bad |= v == INVALID_DN
        q = [v.astype(float) for v in q]
        v = q[0] * (1 - fc) * (1 - fr) + q[1] * fc * (1 - fr) + q[2] * (1 - fc) * fr + q[3] * fc * fr
        h = v * dem.scale + dem.offset - dem.radius_m
        return np.where(ok & ~bad, h, np.nan)


def block_means(dem: PolarGrid, block: int, rows_per_chunk: int = 600) -> np.ndarray:
    """Block means of the whole map, computed in strips (the 120 m map is 462 MB)."""
    if block == 1:
        return np.asarray(dem.data)
    ny, nx = dem.lines // block, dem.samples // block
    out = np.empty((ny, nx), np.int16)
    step = max(1, rows_per_chunk // block)
    for j0 in range(0, ny, step):
        j1 = min(ny, j0 + step)
        raw = np.asarray(dem.data[j0 * block:j1 * block, :nx * block], dtype=np.int16)
        k = raw.reshape(j1 - j0, block, nx, block)
        bad = (k == INVALID_DN).any(axis=(1, 3))
        mean = np.where(k == INVALID_DN, 0, k).astype(np.float64).mean(axis=(1, 3))
        out[j0:j1] = np.where(bad, INVALID_DN, np.round(mean)).astype(np.int16)
    return out


class Pyramid:
    """The map at the three resolutions the fast horizon samples."""

    def __init__(self, dem: PolarGrid, levels=LEVELS, means: dict[int, np.ndarray] | None = None):
        """`means`: block-mean arrays already computed (e.g. loaded from a cache), by block size."""
        self.dem = dem
        means = means or {}
        self.levels = [(Level(b, means[b] if b in means else block_means(dem, b)), km) for b, km in levels]


def fast_horizon(pyr: Pyramid, lat_deg: float, lon_deg: float, observer_m: float = 2.0,
                 az_step_deg: float = 1.0, march: dict = MARCH) -> tuple[np.ndarray, np.ndarray, float]:
    """(elevation deg per azimuth, distance km of the horizon-forming terrain, how far the map
    reaches in the worst direction, km). Same geometry as compute_horizon: great circles from the
    point, terrain rise r_t cos(d) - r_obs over run r_t sin(d)."""
    dem = pyr.dem
    r_ref = dem.radius_m
    li0, si0 = (np.atleast_1d(v).astype(float) for v in dem.pixel(lat_deg, lon_deg))
    h0 = pyr.levels[0][0].heights_m(li0, si0, dem)[0]
    if not np.isfinite(h0):
        raise ValueError(f"({lat_deg}, {lon_deg}) is outside {dem.name}")
    r_obs = r_ref + h0 + observer_m
    d = march_steps(march) * 1000.0
    az = np.arange(0.0, 360.0, az_step_deg)
    phi, lam = np.radians(lat_deg), np.radians(lon_deg)
    delta = d / r_ref
    a = np.radians(az)[:, None]
    sin_lat2 = np.sin(phi) * np.cos(delta) + np.cos(phi) * np.sin(delta) * np.cos(a)
    lat2 = np.arcsin(np.clip(sin_lat2, -1, 1))
    lon2 = lam + np.arctan2(np.sin(a) * np.sin(delta) * np.cos(phi), np.cos(delta) - np.sin(phi) * sin_lat2)
    li, si = dem.pixel(np.degrees(lat2), np.degrees(lon2))
    h = np.full(li.shape, np.nan)
    lo_km = 0.0
    for level, hi_km in pyr.levels:
        cols = (d / 1000.0 >= lo_km) & (d / 1000.0 < hi_km) if hi_km < march["max_km"] else (d / 1000.0 >= lo_km)
        if cols.any():
            h[:, cols] = level.heights_m(li[:, cols], si[:, cols], dem)
        lo_km = hi_km
    r_t = r_ref + h
    elev = np.degrees(np.arctan2(r_t * np.cos(delta) - r_obs, r_t * np.sin(delta)))
    valid = np.isfinite(elev)
    e = np.where(valid, elev, -np.inf)
    k = np.argmax(e, axis=1)
    best = e[np.arange(len(az)), k]
    reach = np.where(valid.any(axis=1), d[np.where(valid, np.arange(len(d)), -1).max(axis=1)], 0.0)
    return np.where(np.isfinite(best), best, 0.0), d[k] / 1000.0, float(reach.min() / 1000.0)


def grid_nodes(dem: PolarGrid, spacing_km: float, min_abs_lat: float = 75.0) -> tuple[np.ndarray, np.ndarray, int, float]:
    """Plane coordinates (km, PolarGrid convention X along samples, Y along lines) of the grid
    points inside the cap |lat| >= min_abs_lat and inside the map; returns (X, Y, n per side, X0)."""
    rho_max = 2 * dem.radius_m / 1000.0 * np.tan(np.radians(90.0 - min_abs_lat) / 2)
    n = int(np.floor(rho_max / spacing_km))
    ax = np.arange(-n, n + 1) * spacing_km
    X, Y = np.meshgrid(ax, ax)
    return X, Y, 2 * n + 1, float(ax[0])


def latlon_of_plane(dem: PolarGrid, X, Y) -> tuple[np.ndarray, np.ndarray]:
    """Inverse projection for PolarGrid plane coordinates (km)."""
    rho = np.hypot(X, Y) * 1000.0
    lat = dem.pole * (90.0 - np.degrees(2 * np.arctan(rho / (2 * dem.radius_m))))
    return lat, np.degrees(np.arctan2(dem.x_sign * X, dem.y_sign * Y))
