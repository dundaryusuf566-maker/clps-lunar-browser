"""Control (design) variables of a targeting problem."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Control:
    """A free parameter the solver may adjust.

    scale:   typical magnitude; the solver works on value/scale so km, km/s and
             radians can live in one problem without conditioning trouble.
    fd_step: finite-difference step in *scaled* units.
    """

    name: str
    value: float
    scale: float = 1.0
    lower: float = -np.inf
    upper: float = np.inf
    fd_step: float = 1e-6
    fixed: bool = False
    unit: str = ""

    def clip(self, value: float) -> float:
        return float(np.clip(value, self.lower, self.upper))


class ControlVector:
    def __init__(self, controls: list[Control]):
        names = [c.name for c in controls]
        if len(names) != len(set(names)):
            raise ValueError(f"Duplicate control names: {names}")
        self.controls = list(controls)

    @property
    def free(self) -> list[Control]:
        return [c for c in self.controls if not c.fixed]

    def __len__(self) -> int:
        return len(self.free)

    def __getitem__(self, name: str) -> Control:
        for c in self.controls:
            if c.name == name:
                return c
        raise KeyError(name)

    def to_scaled(self) -> np.ndarray:
        return np.array([c.value / c.scale for c in self.free])

    def values_from_scaled(self, x: np.ndarray) -> dict[str, float]:
        """All control values (fixed + free) for scaled free vector x, clipped to bounds."""
        values = {c.name: c.value for c in self.controls}
        for c, xi in zip(self.free, x):
            values[c.name] = c.clip(xi * c.scale)
        return values

    def set_scaled(self, x: np.ndarray) -> None:
        for name, value in self.values_from_scaled(x).items():
            self[name].value = value

    def scaled_bounds(self) -> tuple[np.ndarray, np.ndarray]:
        lo = np.array([c.lower / c.scale for c in self.free])
        hi = np.array([c.upper / c.scale for c in self.free])
        return lo, hi

    def as_dict(self) -> dict[str, float]:
        return {c.name: c.value for c in self.controls}
