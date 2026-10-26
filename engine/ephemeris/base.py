"""Ephemeris provider interface.

Every module that needs to know where the Sun, Earth or Moon is talks to an
`EphemerisProvider`. Swapping the low-fidelity analytic model for SPICE (DE440)
is then a one-line change in the mission setup.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import numpy as np


class EphemerisProvider(ABC):
    """Positions/velocities of solar-system bodies in the J2000 frame."""

    name: str = "abstract"

    @abstractmethod
    def state(self, target: str, observer: str, epoch: float) -> np.ndarray:
        """6-vector of `target` relative to `observer` at TDB epoch (km, km/s)."""

    def position(self, target: str, observer: str, epoch: float) -> np.ndarray:
        return self.state(target, observer, epoch)[:3]

    @abstractmethod
    def pole(self, body: str, epoch: float) -> np.ndarray:
        """Unit vector of the body's spin axis (north pole) in J2000."""

    def body_fixed_rotation(self, body: str, epoch: float) -> np.ndarray | None:
        """Optional full J2000 -> body-fixed rotation matrix. Needed for
        tesseral harmonics and surface work; providers may return None."""
        return None
