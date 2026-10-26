"""Spacecraft state container."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class State:
    """Cartesian state at an epoch.

    epoch:  TDB seconds past J2000
    vector: [x, y, z, vx, vy, vz] in km, km/s
    center: name of the origin body (e.g. "EARTH", "MOON")
    frame:  inertial frame name (default ICRF/J2000)
    """

    epoch: float
    vector: np.ndarray
    center: str = "EARTH"
    frame: str = "J2000"

    def __post_init__(self) -> None:
        self.vector = np.asarray(self.vector, dtype=float).reshape(6)
        self.center = self.center.upper()

    @property
    def r(self) -> np.ndarray:
        return self.vector[:3]

    @property
    def v(self) -> np.ndarray:
        return self.vector[3:]

    def copy(self) -> "State":
        return State(self.epoch, self.vector.copy(), self.center, self.frame)

    def with_delta_v(self, dv: np.ndarray) -> "State":
        """Impulsive maneuver: returns a new state with velocity += dv."""
        new = self.copy()
        new.vector[3:] += np.asarray(dv, dtype=float)
        return new
