"""Solvers that drive a TargetingProblem's residuals to zero.

newton: damped Newton / Gauss-Newton with backtracking line search. Uses the
        minimum-norm least-squares step, so it handles square, over- and
        under-determined problems (more controls than residuals is common in
        mission design: the min-norm step changes the controls as little as
        possible).
lm:     scipy's bounded trust-region least squares, more robust far from the
        solution.

Convergence: every residual within its own tolerance (max |normalized| <= tol).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.optimize import least_squares

from .problem import TargetingProblem
from .residuals import Evaluation


@dataclass
class IterationRecord:
    iteration: int
    norm: float          # ||normalized residuals||_2
    max_abs: float       # max |normalized residual|
    step: float          # ||dx|| in scaled controls
    controls: dict[str, float]


@dataclass
class SolverResult:
    problem: str
    method: str
    converged: bool
    message: str
    iterations: int
    evaluations: int
    controls: dict[str, float]
    residuals: list[dict]
    evaluation: Evaluation
    history: list[IterationRecord] = field(default_factory=list)

    def summary(self) -> str:
        lines = [
            f"[{self.problem}] {self.method}: {'CONVERGED' if self.converged else 'NOT CONVERGED'} "
            f"after {self.iterations} it / {self.evaluations} evals - {self.message}",
            f"  {'residual':<24}{'measured':>16}{'target':>16}{'error':>14}{'tol':>11}  unit",
        ]
        for r in self.residuals:
            flag = "ok" if r["ok"] else "!!"
            lines.append(
                f"  {r['name']:<24}{r['measured']:>16.6g}{r['target']:>16.6g}{r['error']:>14.3e}"
                f"{r['tolerance']:>11.2g}  {r['unit']:<5} {flag}"
            )
        return "\n".join(lines)


def solve(problem: TargetingProblem, method: str = "newton", tol: float = 1.0, max_iter: int = 30,
          max_step: float | None = None, central_diff: bool = True, verbose: bool = False) -> SolverResult:
    problem.n_evaluations = 0
    if method == "newton":
        return _newton(problem, tol, max_iter, max_step, central_diff, verbose)
    if method == "lm":
        return _least_squares(problem, tol, max_iter)
    raise ValueError(f"Unknown method '{method}'")


def _finish(problem, method, converged, message, it, x, ev, history) -> SolverResult:
    problem.controls.set_scaled(x)
    return SolverResult(
        problem=problem.name, method=method, converged=converged, message=message,
        iterations=it, evaluations=problem.n_evaluations, controls=problem.controls.as_dict(),
        residuals=problem.report(ev), evaluation=ev, history=history,
    )


def _bounded_step(jac: np.ndarray, f: np.ndarray, x: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> np.ndarray:
    """Min-norm least-squares step with a simple active set: a control sitting
    on a bound whose step would push it further out is frozen and the step is
    recomputed with the remaining controls (otherwise clipping would stall)."""
    free = np.ones(len(x), dtype=bool)
    dx = np.zeros(len(x))
    for _ in range(len(x)):
        dx[:] = 0.0
        if not free.any():
            break
        dx[free], *_ = np.linalg.lstsq(jac[:, free], -f, rcond=None)
        eps = 1e-12 * np.maximum(1.0, np.abs(x))
        blocked = free & (((x <= lo + eps) & (dx < 0)) | ((x >= hi - eps) & (dx > 0)))
        if not blocked.any():
            break
        free &= ~blocked
    return dx


def _newton(problem, tol, max_iter, max_step, central, verbose) -> SolverResult:
    x = problem.controls.to_scaled()
    lo, hi = problem.controls.scaled_bounds()
    f, ev = problem.evaluate(x)
    history = [IterationRecord(0, float(np.linalg.norm(f)), float(np.max(np.abs(f))), 0.0, problem.controls.values_from_scaled(x))]

    for it in range(1, max_iter + 1):
        if np.max(np.abs(f)) <= tol:
            return _finish(problem, "newton", True, "all residuals within tolerance", it - 1, x, ev, history)
        jac = problem.jacobian(x, f0=f, central=central)
        dx = _bounded_step(jac, f, x, lo, hi)
        if max_step is not None and np.linalg.norm(dx) > max_step:
            dx *= max_step / np.linalg.norm(dx)

        # backtracking line search on ||f||
        norm0, alpha = np.linalg.norm(f), 1.0
        while True:
            x_new = np.clip(x + alpha * dx, lo, hi)
            f_new, ev_new = problem.evaluate(x_new)
            if np.linalg.norm(f_new) < norm0 or alpha < 1e-4:
                break
            alpha *= 0.5
        step = float(np.linalg.norm(x_new - x))
        x, f, ev = x_new, f_new, ev_new
        rec = IterationRecord(it, float(np.linalg.norm(f)), float(np.max(np.abs(f))), step, problem.controls.values_from_scaled(x))
        history.append(rec)
        if verbose:
            print(f"  it {it:2d}  |F|={rec.norm:.3e}  max={rec.max_abs:.3e}  step={step:.3e}  alpha={alpha:g}")
        if step < 1e-14:
            break

    ok = bool(np.max(np.abs(f)) <= tol)
    return _finish(problem, "newton", ok, "converged" if ok else "max iterations / stalled", len(history) - 1, x, ev, history)


def _least_squares(problem, tol, max_iter) -> SolverResult:
    x0 = problem.controls.to_scaled()
    lo, hi = problem.controls.scaled_bounds()
    cache: dict[bytes, Evaluation] = {}

    def fun(x):
        f, ev = problem.evaluate(x)
        cache[x.tobytes()] = ev
        return f

    steps = np.array([c.fd_step for c in problem.controls.free])
    sol = least_squares(fun, x0, bounds=(lo, hi), method="trf", diff_step=steps,
                        max_nfev=max_iter * (len(x0) + 1), xtol=1e-14, ftol=1e-14, gtol=1e-14)
    ev = cache.get(sol.x.tobytes()) or problem.run(sol.x)
    ok = bool(np.max(np.abs(sol.fun)) <= tol)
    return _finish(problem, "lm", ok, sol.message, int(sol.nfev), sol.x, ev, [])
