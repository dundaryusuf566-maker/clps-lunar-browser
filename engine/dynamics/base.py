"""The ForceModel contract.

Every physical effect (central gravity, harmonics, third bodies, SRP, thrust...)
is a ForceModel. The DynamicsModel sums the enabled ones. Because each model
reports its own acceleration, we get a per-effect "force budget" for free, which
feeds both validation and the UI.

To add a new effect:
    1. Subclass ForceModel, set a unique `name`.
    2. Implement acceleration(t, r, v, ctx) -> np.ndarray(3) in km/s^2.
    3. Optionally implement potential() if the force is conservative; the
       validation layer then uses it for energy-conservation residuals.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np

from ..ephemeris.base import EphemerisProvider


@dataclass
class SpacecraftProperties:
    mass_kg: float = 1_000.0
    srp_area_m2: float = 5.0
    reflectivity_cr: float = 1.3


@dataclass
class DynamicsContext:
    """Everything a force model may need besides the spacecraft state."""

    central_body: str
    ephemeris: EphemerisProvider
    spacecraft: SpacecraftProperties = field(default_factory=SpacecraftProperties)
    _cache: dict[tuple[str, float], np.ndarray] = field(default_factory=dict, repr=False)

    def body_position(self, body: str, t: float) -> np.ndarray:
        """Position of `body` relative to the central body (cached per epoch)."""
        key = (body.upper(), t)
        hit = self._cache.get(key)
        if hit is None:
            if len(self._cache) > 256:
                self._cache.clear()
            hit = self.ephemeris.position(body, self.central_body, t)
            self._cache[key] = hit
        return hit


class ForceModel(ABC):
    name: str = "force"
    enabled: bool = True

    @abstractmethod
    def acceleration(self, t: float, r: np.ndarray, v: np.ndarray, ctx: DynamicsContext) -> np.ndarray:
        """Acceleration in km/s^2 (inertial frame, central-body origin)."""

    def potential(self, t: float, r: np.ndarray, ctx: DynamicsContext) -> float | None:
        """Specific potential energy (km^2/s^2) if conservative, else None.
        Convention: U is such that a = -grad U."""
        return None

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "type": type(self).__name__, "enabled": self.enabled}
