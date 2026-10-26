"""TargetingProblem: controls -> simulation -> residual vector."""

from __future__ import annotations

from typing import Callable

import numpy as np

from .residuals import Evaluation, Residual
from .variables import ControlVector

Simulator = Callable[[dict[str, float]], Evaluation]


class TargetingProblem:
    """Couples a set of controls, a simulator and the residuals to drive to zero.

    The simulator receives a dict {control name: value} and returns an
    Evaluation. It can be anything: a single propagation, a multi-segment
    TLI -> LOI -> phasing chain, or an analytic approximation.
    """

    def __init__(self, name: str, controls: ControlVector, residuals: list[Residual], simulate: Simulator):
        if len(controls) == 0:
            raise ValueError("Problem has no free controls")
        if not residuals:
            raise ValueError("Problem has no residuals")
        self.name, self.controls, self.residuals, self.simulate = name, controls, residuals, simulate
        self.n_evaluations = 0

    def run(self, x: np.ndarray) -> Evaluation:
        self.n_evaluations += 1
        return self.simulate(self.controls.values_from_scaled(x))

    def residual_vector(self, ev: Evaluation) -> np.ndarray:
        return np.array([r.normalized(ev) for r in self.residuals])

    def evaluate(self, x: np.ndarray) -> tuple[np.ndarray, Evaluation]:
        ev = self.run(x)
        return self.residual_vector(ev), ev

    def jacobian(self, x: np.ndarray, f0: np.ndarray | None = None, central: bool = True) -> np.ndarray:
        """d(normalized residuals)/d(scaled controls) by finite differences."""
        if f0 is None and not central:
            f0, _ = self.evaluate(x)
        jac = np.zeros((len(self.residuals), len(x)))
        for j, ctrl in enumerate(self.controls.free):
            h = ctrl.fd_step
            xp = x.copy()
            xp[j] += h
            fp, _ = self.evaluate(xp)
            if central:
                xm = x.copy()
                xm[j] -= h
                fm, _ = self.evaluate(xm)
                jac[:, j] = (fp - fm) / (2 * h)
            else:
                jac[:, j] = (fp - f0) / h
        return jac

    def report(self, ev: Evaluation) -> list[dict]:
        return [r.row(ev) for r in self.residuals]
