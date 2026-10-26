"""Site geometry on whole time grids: where a site points, and where the Sun
and the Earth stand in its local sky (elevation above the local horizontal
plane, azimuth from north clockwise). The terrain horizon is applied on top of
these by the landing analysis (see terrain.py).

All functions take a CachedEphemeris with a lunar rotation table (format v2)
and arrays of TDB epochs, and return arrays.
"""

from __future__ import annotations

import numpy as np

from ..ephemeris.cached import CachedEphemeris
from .sites import MOON_MEAN_RADIUS_KM, LandingSite


def _require_rotation(cache: CachedEphemeris) -> None:
    if not cache.has_rotation:
        raise ValueError("This ephemeris cache has no lunar rotation table; rebuild it (format v2)")


def site_inertial(cache: CachedEphemeris, site: LandingSite, ts) -> np.ndarray:
    """(N, 3) unit vectors from the Moon's centre to the site, J2000."""
    _require_rotation(cache)
    rot = cache.rotation_many("MOON", ts)              # J2000 -> fixed
    return np.einsum("nji,j->ni", rot, site.unit_fixed())  # R^T u


def sun_elevation_deg(cache: CachedEphemeris, site: LandingSite, ts, up: np.ndarray | None = None) -> np.ndarray:
    up = site_inertial(cache, site, ts) if up is None else up
    sun = cache.position_many("SUN", "MOON", ts)
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)  # parallax of the site is negligible at 1 AU
    return np.degrees(np.arcsin(np.clip(np.sum(up * sun, axis=1), -1, 1)))


def earth_elevation_deg(cache: CachedEphemeris, site: LandingSite, ts, up: np.ndarray | None = None) -> np.ndarray:
    up = site_inertial(cache, site, ts) if up is None else up
    earth = cache.position_many("EARTH", "MOON", ts) - MOON_MEAN_RADIUS_KM * up  # from the site itself
    earth /= np.linalg.norm(earth, axis=1, keepdims=True)
    return np.degrees(np.arcsin(np.clip(np.sum(up * earth, axis=1), -1, 1)))


def local_frame(cache: CachedEphemeris, site: LandingSite, ts, up: np.ndarray | None = None):
    """(up, north, east) unit vectors of the site's local horizon frame, J2000, each (N, 3)."""
    up = site_inertial(cache, site, ts) if up is None else up
    pole = cache.pole_many("MOON", ts)
    north = pole - np.sum(pole * up, axis=1, keepdims=True) * up
    north /= np.linalg.norm(north, axis=1, keepdims=True)
    east = np.cross(north, up)
    return up, north, east


def az_el_deg(vec: np.ndarray, up: np.ndarray, north: np.ndarray, east: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth (from north, clockwise) and elevation of directions `vec` (N, 3)."""
    v = vec / np.linalg.norm(vec, axis=1, keepdims=True)
    el = np.degrees(np.arcsin(np.clip(np.sum(v * up, axis=1), -1, 1)))
    az = np.degrees(np.arctan2(np.sum(v * east, axis=1), np.sum(v * north, axis=1))) % 360.0
    return az, el


def sun_az_el_deg(cache: CachedEphemeris, site: LandingSite, ts, frame=None):
    up, north, east = frame if frame is not None else local_frame(cache, site, ts)
    return az_el_deg(cache.position_many("SUN", "MOON", ts), up, north, east)


def earth_az_el_deg(cache: CachedEphemeris, site: LandingSite, ts, frame=None):
    up, north, east = frame if frame is not None else local_frame(cache, site, ts)
    return az_el_deg(cache.position_many("EARTH", "MOON", ts) - MOON_MEAN_RADIUS_KM * up, up, north, east)


def selenographic(cache: CachedEphemeris, vec_j2000: np.ndarray, epoch: float) -> tuple[float, float]:
    """(lat, lon) in degrees of an inertial direction as seen in the lunar fixed frame."""
    v = cache.body_fixed_rotation("MOON", epoch) @ np.asarray(vec_j2000, float)
    v = v / np.linalg.norm(v)
    return float(np.degrees(np.arcsin(v[2]))), float(np.degrees(np.arctan2(v[1], v[0])))
