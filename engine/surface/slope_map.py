"""The tilt of the ground over a polar cap, for the browser: one surface normal per 240 m block.

scripts/thermal_attribution.py found that the browser's polar temperatures improve from a
median error of 32.2 K to 14.8 K when each point takes the normal of the 240 m block it falls
in (its rule, written before the run, asked for at most half and at most 15 K). This module
defines that block normal so that the map, its check and the browser all mean the same thing:

  block      the 120 m map's pixels in 2 x 2 blocks: block (bi, bj) = (floor(line / 2), floor(sample / 2))
  centre     line 2 bi + 0.5, sample 2 bj + 0.5 (the convention thermal_attribution.py used)
  normal     scripts/build_thermal.py local_normal at the centre: the cross product of the
             surface's slopes over two map pixels either side, turned outward
  stored     its east and north components in the centre's local frame, int16 x 32767
             (resolution 0.002 deg); -32768 where the map has no block
"""

from __future__ import annotations

import numpy as np

from engine.surface.terrain import PolarGrid

SCALE = 32767.0
MISSING = -32768


def block_of(dem: PolarGrid, lat, lon) -> tuple[np.ndarray, np.ndarray]:
    li, si = dem.pixel(np.asarray(lat, float), np.asarray(lon, float))
    return np.floor(np.asarray(li) / 2).astype(np.int64), np.floor(np.asarray(si) / 2).astype(np.int64)


def block_centre(bi, bj) -> tuple[np.ndarray, np.ndarray]:
    return np.asarray(bi) * 2 + 0.5, np.asarray(bj) * 2 + 0.5


def frame(lat, lon) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Up, north, east (Moon-fixed unit vectors, shape (..., 3)), as engine/validation/illumination.az_el_fixed."""
    p, l = np.radians(np.asarray(lat, float)), np.radians(np.asarray(lon, float))
    up = np.stack([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)], -1)
    north = np.stack([-np.sin(p) * np.cos(l), -np.sin(p) * np.sin(l), np.cos(p)], -1)
    east = np.stack([-np.sin(l), np.cos(l), np.zeros_like(p)], -1)
    return up, north, east


def normals_at(dem: PolarGrid, line, sample) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """build_thermal.local_normal for many map positions at once: (normals, lat, lon) of the positions."""
    line, sample = np.asarray(line, float).ravel(), np.asarray(sample, float).ravel()
    lat, lon = dem.latlon(line, sample)

    def xyz(li, si):
        la, lo = dem.latlon(li, si)
        rr = dem.value(la, lo) / 1000.0
        p, q = np.radians(la), np.radians(lo)
        return rr[:, None] * np.stack([np.cos(p) * np.cos(q), np.cos(p) * np.sin(q), np.sin(p)], -1)

    dx = xyz(line, sample + 1) - xyz(line, sample - 1)
    dy = xyz(line + 1, sample) - xyz(line - 1, sample)
    n = np.cross(dx, dy)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    up, _, _ = frame(lat, lon)
    n *= np.where(np.sum(n * up, axis=1) > 0, 1.0, -1.0)[:, None]
    return n, lat, lon


def encode(n: np.ndarray, lat, lon) -> np.ndarray:
    """(..., 2) int16: east and north components of the normal in the local frame at (lat, lon)."""
    _, north, east = frame(lat, lon)
    e, nn = np.sum(n * east, -1), np.sum(n * north, -1)
    out = np.stack([e, nn], -1) * SCALE
    bad = ~np.isfinite(out).all(-1)
    out = np.round(np.nan_to_num(out)).astype(np.int16)
    out[bad] = MISSING
    return out


def decode(code: np.ndarray, lat, lon) -> np.ndarray:
    """Inverse of encode (NaN where missing)."""
    up, north, east = frame(lat, lon)
    c = np.asarray(code, float)
    e, nn = c[..., 0] / SCALE, c[..., 1] / SCALE
    u = np.sqrt(np.clip(1 - e * e - nn * nn, 0, 1))
    n = e[..., None] * east + nn[..., None] * north + u[..., None] * up
    n[np.asarray(code)[..., 0] == MISSING] = np.nan
    return n


def slope_deg(n: np.ndarray, lat, lon) -> np.ndarray:
    up, _, _ = frame(lat, lon)
    return np.degrees(np.arccos(np.clip(np.sum(n * up, -1), -1, 1)))
