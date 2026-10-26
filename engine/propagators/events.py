"""Event functions for root-finding during integration.

An event is a scalar function g(t, y) whose zero crossings are located by the
integrator. `direction=+1` triggers only on negative->positive crossings.
Terminal events stop the propagation (e.g. impact, arrival at a sphere).
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np

from ..core.constants import body as get_body
from ..dynamics.composer import DynamicsModel
from ..dynamics.srp import cylindrical_shadow


class Event(ABC):
    name: str = "event"
    terminal: bool = False
    direction: float = 0.0

    @abstractmethod
    def __call__(self, t: float, y: np.ndarray, dyn: DynamicsModel) -> float: ...

    def as_scipy(self, dyn: DynamicsModel):
        def fn(t, y):
            return self(t, y, dyn)

        fn.terminal = self.terminal
        fn.direction = self.direction
        return fn


class Periapsis(Event):
    """r · v crosses zero going up (radius at minimum)."""

    direction = 1.0

    def __init__(self, terminal: bool = False, name: str = "periapsis"):
        self.terminal, self.name = terminal, name

    def __call__(self, t, y, dyn):
        return float(np.dot(y[:3], y[3:6]))


class Apoapsis(Periapsis):
    direction = -1.0

    def __init__(self, terminal: bool = False, name: str = "apoapsis"):
        super().__init__(terminal, name)


class AltitudeCrossing(Event):
    """Altitude above the central body's mean radius crosses `altitude_km`."""

    def __init__(self, altitude_km: float, direction: float = -1.0, terminal: bool = True, name: str | None = None):
        self.altitude_km, self.direction, self.terminal = altitude_km, direction, terminal
        self.name = name or f"altitude_{altitude_km:g}km"

    def __call__(self, t, y, dyn):
        return float(np.linalg.norm(y[:3]) - get_body(dyn.central_body).radius - self.altitude_km)


class Impact(AltitudeCrossing):
    def __init__(self):
        super().__init__(0.0, direction=-1.0, terminal=True, name="impact")


class DistanceToBody(Event):
    """Distance to another body crosses a threshold (e.g. entering lunar SOI)."""

    def __init__(self, body: str, distance_km: float, direction: float = -1.0, terminal: bool = True, name: str | None = None):
        self.body, self.distance_km = body.upper(), distance_km
        self.direction, self.terminal = direction, terminal
        self.name = name or f"{self.body.lower()}_distance_{distance_km:g}km"

    def __call__(self, t, y, dyn):
        rb = dyn.ctx.body_position(self.body, t)
        return float(np.linalg.norm(y[:3] - rb) - self.distance_km)


class ClosestApproach(Event):
    """Minimum distance to another body: relative r·v crosses zero going up.

    Only minima closer than `max_distance_km` count, so that distant geometric
    minima (e.g. right after leaving Earth) do not stop the propagation. Outside
    that radius the function is held at -1, which can never produce a -/+
    crossing on its own."""

    direction = 1.0

    def __init__(self, body: str, max_distance_km: float = np.inf, terminal: bool = True, name: str | None = None):
        self.body, self.terminal, self.max_distance_km = body.upper(), terminal, max_distance_km
        self.name = name or f"{self.body.lower()}_closest_approach"

    def __call__(self, t, y, dyn):
        rel = y - dyn.ephemeris.state(self.body, dyn.central_body, t)
        if np.linalg.norm(rel[:3]) > self.max_distance_km:
            return -1.0
        return float(np.dot(rel[:3], rel[3:]))


class ShadowCrossing(Event):
    """Positive in sunlight, negative inside the central body's cylindrical shadow."""

    def __init__(self, terminal: bool = False, name: str = "shadow"):
        self.terminal, self.name = terminal, name

    def __call__(self, t, y, dyn):
        r_sun = dyn.ctx.body_position("SUN", t)
        radius = get_body(dyn.central_body).radius
        sun_dir = r_sun / np.linalg.norm(r_sun)
        along = float(np.dot(y[:3], sun_dir))
        if along > 0:
            return radius
        perp = float(np.linalg.norm(y[:3] - along * sun_dir))
        return perp - radius


__all__ = ["Event", "Periapsis", "Apoapsis", "AltitudeCrossing", "Impact", "DistanceToBody", "ClosestApproach", "ShadowCrossing", "cylindrical_shadow"]
