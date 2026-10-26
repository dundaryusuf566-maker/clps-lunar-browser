"""Low-fidelity analytic ephemeris (no external files).

Use for unit tests, fast prototyping and offline demos. Errors: Sun direction
~0.01 deg, Moon position up to ~5 % in distance and a few degrees in
longitude (circular inclined orbit with regressing node). Lunar orientation
follows the full IAU 2009 model (~0.03 deg from DE440's MOON_PA). Use the
SPICE provider for any result that is shown to the jury.
"""

from __future__ import annotations

import numpy as np

from ..core.constants import AU_KM, SECONDS_PER_DAY
from ..core.frames import ecliptic_to_j2000
from . import iau_moon
from .base import EphemerisProvider

_MOON_SMA_KM = 384_400.0
_MOON_INC = np.radians(5.145)
_MOON_L0_DEG, _MOON_RATE_DEG_DAY = 218.316, 13.176396
_NODE_L0_DEG, _NODE_RATE_DEG_DAY = 125.045, -0.0529539


class AnalyticEphemeris(EphemerisProvider):
    name = "analytic-lowfi"
    _FD_STEP = 10.0  # s, for velocities by central difference

    def __init__(self) -> None:
        self._ecl2eq = ecliptic_to_j2000()

    # --- geocentric positions -------------------------------------------------
    def _moon_geo(self, t: float) -> np.ndarray:
        d = t / SECONDS_PER_DAY
        lon = np.radians(_MOON_L0_DEG + _MOON_RATE_DEG_DAY * d)
        node = np.radians(_NODE_L0_DEG + _NODE_RATE_DEG_DAY * d)
        u = lon - node
        ci, si = np.cos(_MOON_INC), np.sin(_MOON_INC)
        r_ecl = _MOON_SMA_KM * np.array([
            np.cos(node) * np.cos(u) - np.sin(node) * np.sin(u) * ci,
            np.sin(node) * np.cos(u) + np.cos(node) * np.sin(u) * ci,
            np.sin(u) * si,
        ])
        return self._ecl2eq @ r_ecl

    def _sun_geo(self, t: float) -> np.ndarray:
        d = t / SECONDS_PER_DAY
        g = np.radians(357.529 + 0.98560028 * d)
        lam = np.radians(280.459 + 0.98564736 * d + 1.915 * np.sin(g) + 0.020 * np.sin(2 * g))
        dist = AU_KM * (1.00014 - 0.01671 * np.cos(g) - 0.00014 * np.cos(2 * g))
        return self._ecl2eq @ (dist * np.array([np.cos(lam), np.sin(lam), 0.0]))

    def _geo_position(self, body: str, t: float) -> np.ndarray:
        body = body.upper()
        if body == "EARTH":
            return np.zeros(3)
        if body == "MOON":
            return self._moon_geo(t)
        if body == "SUN":
            return self._sun_geo(t)
        raise KeyError(f"AnalyticEphemeris has no model for '{body}'")

    def _geo_state(self, body: str, t: float) -> np.ndarray:
        h = self._FD_STEP
        r = self._geo_position(body, t)
        v = (self._geo_position(body, t + h) - self._geo_position(body, t - h)) / (2 * h)
        return np.concatenate([r, v])

    # --- interface ------------------------------------------------------------
    def state(self, target: str, observer: str, epoch: float) -> np.ndarray:
        if target.upper() == observer.upper():
            return np.zeros(6)
        return self._geo_state(target, epoch) - self._geo_state(observer, epoch)

    def pole(self, body: str, epoch: float) -> np.ndarray:
        body = body.upper()
        if body == "EARTH":
            return np.array([0.0, 0.0, 1.0])  # precession ignored
        if body == "MOON":
            return iau_moon.pole(epoch)
        if body == "SUN":
            ra, dec = np.radians(286.13), np.radians(63.87)
            return np.array([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)])
        raise KeyError(body)

    def body_fixed_rotation(self, body: str, epoch: float) -> np.ndarray | None:
        if body.upper() == "MOON":
            return iau_moon.rotation(epoch)
        return None
