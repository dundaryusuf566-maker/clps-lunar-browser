"""IAU/WGCCRE 2009 lunar orientation model (Archinal et al. 2011).

Gives the lunar north pole (alpha0, delta0) and prime meridian angle W with the
13 periodic nutation/libration terms. This is the IAU_MOON frame (close to the
Mean Earth frame, within ~0.01-0.03 deg of DE440's MOON_PA). The periodic terms
matter: the constant-only pole is off by up to ~1.5 deg because the lunar pole
precesses around the ecliptic pole with the 18.6-year nodal cycle.
"""

from __future__ import annotations

import numpy as np

from ..core.constants import SECONDS_PER_DAY
from ..core.frames import rot_x, rot_z

_D2R = np.pi / 180.0


def _args(d: float) -> np.ndarray:
    return _D2R * np.array([
        125.045 - 0.0529921 * d,
        250.089 - 0.1059842 * d,
        260.008 + 13.0120009 * d,
        176.625 + 13.3407154 * d,
        357.529 + 0.9856003 * d,
        311.589 + 26.4057084 * d,
        134.963 + 13.0649930 * d,
        276.617 + 0.3287146 * d,
        34.226 + 1.7484877 * d,
        15.134 - 0.1589763 * d,
        119.743 + 0.0036096 * d,
        239.961 + 0.1643573 * d,
        25.053 + 12.9590088 * d,
    ])


_A_SIN = np.array([-3.8787, -0.1204, 0.0700, -0.0172, 0.0, 0.0072, 0.0, 0.0, 0.0, -0.0052, 0.0, 0.0, 0.0043])
_D_COS = np.array([1.5419, 0.0239, -0.0278, 0.0068, 0.0, -0.0029, 0.0009, 0.0, 0.0, 0.0008, 0.0, 0.0, -0.0009])
_W_SIN = np.array([3.5610, 0.1208, -0.0642, 0.0158, 0.0252, -0.0066, -0.0047, -0.0046, 0.0028, 0.0052, 0.0040, 0.0019, -0.0044])


def orientation(epoch: float) -> tuple[float, float, float]:
    """(alpha0, delta0, W) in radians for a TDB epoch (s past J2000)."""
    d = epoch / SECONDS_PER_DAY
    t = d / 36525.0
    e = _args(d)
    alpha = 269.9949 + 0.0031 * t + float(_A_SIN @ np.sin(e))
    delta = 66.5392 + 0.0130 * t + float(_D_COS @ np.cos(e))
    w = 38.3213 + 13.17635815 * d - 1.4e-12 * d * d + float(_W_SIN @ np.sin(e))
    return alpha * _D2R, delta * _D2R, (w % 360.0) * _D2R


def pole(epoch: float) -> np.ndarray:
    a, dlt, _ = orientation(epoch)
    return np.array([np.cos(dlt) * np.cos(a), np.cos(dlt) * np.sin(a), np.sin(dlt)])


def rotation(epoch: float) -> np.ndarray:
    """J2000 -> IAU_MOON body-fixed rotation matrix (rows: x, y, z axes)."""
    a, dlt, w = orientation(epoch)
    return rot_z(w) @ rot_x(np.pi / 2 - dlt) @ rot_z(np.pi / 2 + a)
