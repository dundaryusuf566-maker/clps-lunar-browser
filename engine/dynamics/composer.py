"""DynamicsModel: composes ForceModels into an equation of motion."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..ephemeris.base import EphemerisProvider
from .base import DynamicsContext, ForceModel, SpacecraftProperties


@dataclass
class DynamicsModel:
    central_body: str
    ephemeris: EphemerisProvider
    forces: list[ForceModel] = field(default_factory=list)
    spacecraft: SpacecraftProperties = field(default_factory=SpacecraftProperties)

    def __post_init__(self) -> None:
        self.central_body = self.central_body.upper()
        self.ctx = DynamicsContext(self.central_body, self.ephemeris, self.spacecraft)
        names = [f.name for f in self.forces]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate force model names: {names}")

    # --- configuration ---------------------------------------------------------
    def add(self, force: ForceModel) -> "DynamicsModel":
        if any(f.name == force.name for f in self.forces):
            raise ValueError(f"Force '{force.name}' already present")
        self.forces.append(force)
        return self

    def get(self, name: str) -> ForceModel:
        for f in self.forces:
            if f.name == name:
                return f
        raise KeyError(name)

    def set_enabled(self, name: str, enabled: bool) -> None:
        self.get(name).enabled = enabled

    @property
    def active_forces(self) -> list[ForceModel]:
        return [f for f in self.forces if f.enabled]

    # --- evaluation ------------------------------------------------------------
    def acceleration(self, t: float, y: np.ndarray) -> np.ndarray:
        r, v = y[:3], y[3:6]
        a = np.zeros(3)
        for f in self.active_forces:
            a += f.acceleration(t, r, v, self.ctx)
        return a

    def rhs(self, t: float, y: np.ndarray) -> np.ndarray:
        """dy/dt for the integrator."""
        return np.concatenate([y[3:6], self.acceleration(t, y)])

    def breakdown(self, t: float, y: np.ndarray) -> dict[str, np.ndarray]:
        """Per-force acceleration vectors at one instant (force budget)."""
        r, v = y[:3], y[3:6]
        return {f.name: f.acceleration(t, r, v, self.ctx) for f in self.active_forces}

    def specific_energy(self, t: float, y: np.ndarray) -> float | None:
        """v^2/2 + sum(U) if every active force is conservative, else None."""
        total = 0.5 * float(np.dot(y[3:6], y[3:6]))
        for f in self.active_forces:
            u = f.potential(t, y[:3], self.ctx)
            if u is None:
                return None
            total += u
        return total

    def describe(self) -> dict:
        return {
            "central_body": self.central_body,
            "ephemeris": self.ephemeris.name,
            "forces": [f.describe() for f in self.forces],
        }
