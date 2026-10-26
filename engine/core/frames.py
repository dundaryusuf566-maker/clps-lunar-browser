"""Reference frame utilities.

All rotation matrices map vectors FROM the inertial frame TO the named frame,
i.e. v_frame = R @ v_inertial.
"""

from __future__ import annotations

import numpy as np

from .constants import OBLIQUITY_J2000_DEG


def rot_x(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[1, 0, 0], [0, c, s], [0, -s, c]])


def rot_z(angle: float) -> np.ndarray:
    c, s = np.cos(angle), np.sin(angle)
    return np.array([[c, s, 0], [-s, c, 0], [0, 0, 1]])


def unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    if n == 0:
        raise ValueError("Cannot normalize a zero vector")
    return v / n


def ecliptic_to_j2000() -> np.ndarray:
    """Rotation taking ecliptic-of-J2000 vectors into J2000 equatorial."""
    return rot_x(np.radians(OBLIQUITY_J2000_DEG)).T


def frame_from_pole(pole: np.ndarray, x_ref: np.ndarray) -> np.ndarray:
    """Build a right-handed frame with z along `pole` and x as close as possible
    to `x_ref` (projected onto the plane normal to the pole)."""
    z = unit(np.asarray(pole, float))
    x = np.asarray(x_ref, float) - np.dot(x_ref, z) * z
    x = unit(x)
    y = np.cross(z, x)
    return np.vstack([x, y, z])


def moon_sun_frame(moon_pole: np.ndarray, sun_from_moon: np.ndarray) -> np.ndarray:
    """Moon-centred frame used for RAAN(Moon-Sun): z = lunar pole, x = Sun
    direction projected onto the lunar equator. A RAAN of 0 deg in this frame
    means the ascending node points at the Sun."""
    return frame_from_pole(moon_pole, sun_from_moon)


def rtn_frame(r: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Radial / along-track (transverse) / orbit-normal frame."""
    radial = unit(r)
    normal = unit(np.cross(r, v))
    transverse = np.cross(normal, radial)
    return np.vstack([radial, transverse, normal])
