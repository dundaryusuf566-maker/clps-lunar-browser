"""The Residual contract.

A residual measures one quantity from a simulated mission segment and compares it
with a target:

    error      = measure(evaluation) - target      (wrapped to [-pi, pi) if angular)
    normalized = error / tolerance

So |normalized| <= 1 means "satisfied". The solver drives the vector of
normalized residuals to zero; the tolerance also acts as the natural weight when
there are more residuals than controls.

To add a new residual: subclass Residual and implement measure(), or wrap a
lambda in CallableResidual.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from ..core.state import State
from ..orbits.elements import cartesian_to_elements


@dataclass
class Evaluation:
    """What a mission simulation returns to the targeting layer."""

    final: State | None = None
    segments: dict[str, Any] = field(default_factory=dict)   # name -> Trajectory
    data: dict[str, float] = field(default_factory=dict)     # derived scalars (dv, times, ...)


def wrap_angle(a: float) -> float:
    return (a + np.pi) % (2 * np.pi) - np.pi


class Residual(ABC):
    name: str
    target: float
    tolerance: float
    unit: str = ""
    angular: bool = False

    def __init__(self, name: str, target: float, tolerance: float, unit: str = "", angular: bool = False):
        if tolerance <= 0:
            raise ValueError(f"Residual '{name}': tolerance must be > 0")
        self.name, self.target, self.tolerance = name, float(target), float(tolerance)
        self.unit, self.angular = unit, angular

    @abstractmethod
    def measure(self, ev: Evaluation) -> float: ...

    def error(self, ev: Evaluation) -> float:
        e = self.measure(ev) - self.target
        return wrap_angle(e) if self.angular else e

    def normalized(self, ev: Evaluation) -> float:
        return self.error(ev) / self.tolerance

    def row(self, ev: Evaluation) -> dict:
        m = self.measure(ev)
        e = self.error(ev)
        conv = np.degrees if self.angular else (lambda x: x)
        return {
            "name": self.name,
            "measured": float(conv(m)),
            "target": float(conv(self.target)),
            "error": float(conv(e)),
            "tolerance": float(conv(self.tolerance)),
            "unit": "deg" if self.angular else self.unit,
            "ok": abs(e) <= self.tolerance,
        }


class CallableResidual(Residual):
    def __init__(self, name: str, fn: Callable[[Evaluation], float], target: float, tolerance: float, unit: str = "", angular: bool = False):
        super().__init__(name, target, tolerance, unit, angular)
        self.fn = fn

    def measure(self, ev):
        return float(self.fn(ev))


class DataResidual(Residual):
    """Reads a scalar the simulation put in Evaluation.data[key]."""

    def __init__(self, key: str, target: float, tolerance: float, unit: str = "", angular: bool = False, name: str | None = None):
        super().__init__(name or key, target, tolerance, unit, angular)
        self.key = key

    def measure(self, ev):
        return float(ev.data[self.key])


class FinalStateComponent(Residual):
    _LABELS = ["x", "y", "z", "vx", "vy", "vz"]

    def __init__(self, index: int, target: float, tolerance: float, name: str | None = None):
        unit = "km" if index < 3 else "km/s"
        super().__init__(name or f"final_{self._LABELS[index]}", target, tolerance, unit)
        self.index = index

    def measure(self, ev):
        return float(ev.final.vector[self.index])


def final_position_residuals(target: np.ndarray, tolerance_km: float) -> list[Residual]:
    return [FinalStateComponent(i, target[i], tolerance_km) for i in range(3)]


class FinalElement(Residual):
    """An orbital element of the final state.

    element: sma | ecc | inc | raan | argp | nu | rp | ra | periapsis_alt | apoapsis_alt
    frame:   rotation matrix (inertial -> reference) or a callable(ev) returning
             one, e.g. the lunar equator or the Moon-Sun frame.
    """

    _ANGLES = {"inc", "raan", "argp", "nu"}

    def __init__(self, element: str, target: float, tolerance: float, gm: float,
                 frame: np.ndarray | Callable[[Evaluation], np.ndarray] | None = None,
                 body_radius: float = 0.0, name: str | None = None):
        angular = element in self._ANGLES
        unit = "" if element == "ecc" else ("rad" if angular else "km")
        super().__init__(name or f"final_{element}", target, tolerance, unit, angular)
        self.element, self.gm, self.frame, self.body_radius = element, gm, frame, body_radius

    def measure(self, ev):
        frame = self.frame(ev) if callable(self.frame) else self.frame
        el = cartesian_to_elements(ev.final.r, ev.final.v, self.gm, frame)
        if self.element == "rp":
            return el.periapsis_radius()
        if self.element == "ra":
            return el.apoapsis_radius()
        if self.element == "periapsis_alt":
            return el.periapsis_radius() - self.body_radius
        if self.element == "apoapsis_alt":
            return el.apoapsis_radius() - self.body_radius
        return float(getattr(el, self.element))


class Bound(Residual):
    """Inequality constraint lower <= measure <= upper as a hinge residual:
    zero inside the interval, distance to the violated bound outside."""

    def __init__(self, inner: Residual, lower: float = -np.inf, upper: float = np.inf, name: str | None = None):
        super().__init__(name or f"{inner.name}_bound", 0.0, inner.tolerance, inner.unit, False)
        self.inner, self.lower, self.upper = inner, lower, upper

    def measure(self, ev):
        m = self.inner.measure(ev)
        if m < self.lower:
            return m - self.lower
        if m > self.upper:
            return m - self.upper
        return 0.0
