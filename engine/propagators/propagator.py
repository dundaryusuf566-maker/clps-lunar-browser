"""Numerical propagation of a State under a DynamicsModel."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.integrate import solve_ivp

from ..core.state import State
from ..dynamics.composer import DynamicsModel
from .events import Event


@dataclass
class EventHit:
    name: str
    epoch: float
    vector: np.ndarray


@dataclass
class Trajectory:
    """Result of a propagation: samples, dense interpolant and event hits."""

    epochs: np.ndarray            # (N,)
    states: np.ndarray            # (N, 6)
    center: str
    frame: str
    dynamics: DynamicsModel
    events: list[EventHit] = field(default_factory=list)
    terminated_by: str | None = None
    _dense: object = None
    n_rhs_evals: int = 0

    @property
    def initial(self) -> State:
        return State(self.epochs[0], self.states[0], self.center, self.frame)

    @property
    def final(self) -> State:
        return State(self.epochs[-1], self.states[-1], self.center, self.frame)

    def state_at(self, epoch: float) -> State:
        lo, hi = sorted((self.epochs[0], self.epochs[-1]))
        if not lo - 1e-6 <= epoch <= hi + 1e-6:
            raise ValueError(f"epoch {epoch} outside trajectory span [{lo}, {hi}]")
        if self._dense is None:
            raise RuntimeError("Trajectory was propagated without dense output")
        return State(epoch, self._dense(epoch), self.center, self.frame)

    def hits(self, name: str) -> list[EventHit]:
        return [e for e in self.events if e.name == name]

    def sample(self, n: int) -> tuple[np.ndarray, np.ndarray]:
        ts = np.linspace(self.epochs[0], self.epochs[-1], n)
        return ts, np.array([self._dense(t) for t in ts])


def propagate(
    dynamics: DynamicsModel,
    initial: State,
    duration: float,
    events: list[Event] | None = None,
    rtol: float = 1e-11,
    atol: float = 1e-10,
    method: str = "DOP853",
    max_step: float = np.inf,
    dense: bool = True,
) -> Trajectory:
    """Propagate `initial` for `duration` seconds (negative = backwards)."""
    if initial.center != dynamics.central_body:
        raise ValueError(
            f"State centred on {initial.center} but dynamics on {dynamics.central_body}; "
            "use engine.ephemeris.change_center first"
        )
    events = events or []
    t0 = float(initial.epoch)
    sol = solve_ivp(
        dynamics.rhs,
        (t0, t0 + duration),
        initial.vector,
        method=method,
        rtol=rtol,
        atol=atol,
        max_step=max_step,
        events=[e.as_scipy(dynamics) for e in events] or None,
        dense_output=dense,
    )
    if sol.status < 0:
        raise RuntimeError(f"Integration failed: {sol.message}")

    hits: list[EventHit] = []
    terminated_by = None
    if events:
        for ev, t_ev, y_ev in zip(events, sol.t_events, sol.y_events):
            hits += [EventHit(ev.name, float(t), np.asarray(y)) for t, y in zip(t_ev, y_ev)]
            if sol.status == 1 and ev.terminal and len(t_ev):
                terminated_by = ev.name
        hits.sort(key=lambda h: h.epoch, reverse=duration < 0)

    return Trajectory(
        epochs=sol.t,
        states=sol.y.T,
        center=initial.center,
        frame=initial.frame,
        dynamics=dynamics,
        events=hits,
        terminated_by=terminated_by,
        _dense=sol.sol,
        n_rhs_evals=sol.nfev,
    )
