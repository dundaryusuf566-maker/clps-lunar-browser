"""Solar radiation pressure, cannonball model with optional shadowing."""

from __future__ import annotations

import numpy as np

from ..core.constants import AU_KM, SOLAR_PRESSURE_1AU
from ..core.constants import body as get_body
from .base import DynamicsContext, ForceModel


def cylindrical_shadow(r_sc: np.ndarray, r_sun: np.ndarray, r_occ: np.ndarray, radius: float) -> float:
    """1.0 = full sun, 0.0 = in the occulting body's cylindrical shadow.
    All vectors share the same origin."""
    sun_dir = (r_sun - r_occ) / np.linalg.norm(r_sun - r_occ)
    rel = r_sc - r_occ
    along = np.dot(rel, sun_dir)
    if along > 0:  # on the sunlit side of the occulter
        return 1.0
    perp = np.linalg.norm(rel - along * sun_dir)
    return 0.0 if perp < radius else 1.0


class SolarRadiationPressure(ForceModel):
    name = "solar_radiation_pressure"

    def __init__(self, shadow_bodies: list[str] | None = None):
        # Bodies that can eclipse the spacecraft; default: central body only.
        self.shadow_bodies = [b.upper() for b in shadow_bodies] if shadow_bodies is not None else None

    def illumination(self, t, r, ctx: DynamicsContext) -> float:
        r_sun = ctx.body_position("SUN", t)
        bodies = self.shadow_bodies if self.shadow_bodies is not None else [ctx.central_body]
        nu = 1.0
        for b in bodies:
            r_occ = np.zeros(3) if b == ctx.central_body else ctx.body_position(b, t)
            nu = min(nu, cylindrical_shadow(r, r_sun, r_occ, get_body(b).radius))
        return nu

    def acceleration(self, t, r, v, ctx: DynamicsContext) -> np.ndarray:
        sc = ctx.spacecraft
        r_sun = ctx.body_position("SUN", t)
        s = r - r_sun  # Sun -> spacecraft
        dist = np.linalg.norm(s)
        nu = self.illumination(t, r, ctx)
        if nu == 0.0:
            return np.zeros(3)
        # N/m^2 * m^2 / kg = m/s^2  ->  /1000 for km/s^2
        mag = nu * SOLAR_PRESSURE_1AU * sc.reflectivity_cr * sc.srp_area_m2 / sc.mass_kg * (AU_KM / dist) ** 2 / 1000.0
        return mag * s / dist
