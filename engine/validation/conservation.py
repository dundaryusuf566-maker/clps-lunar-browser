"""Physics-validation residuals: does the integrator + force model behave?"""

from __future__ import annotations

import numpy as np

from ..core.state import State
from ..dynamics.composer import DynamicsModel
from ..propagators.propagator import Trajectory, propagate


def energy_drift(traj: Trajectory, n_samples: int | None = None) -> np.ndarray:
    """Relative specific-energy drift (E(t) - E0) / |E0| along a trajectory.

    By default evaluated at the integrator's own steps (pure integration error).
    Pass n_samples to evaluate on the dense interpolant instead, which also
    includes interpolation error (~1e-11 relative for DOP853).

    Only meaningful when every active force is conservative AND time-independent
    (point mass, zonals with a fixed pole). Raises otherwise."""
    dyn = traj.dynamics
    ts, ys = (traj.epochs, traj.states) if n_samples is None else traj.sample(n_samples)
    energies = [dyn.specific_energy(t, y) for t, y in zip(ts, ys)]
    if any(e is None for e in energies):
        raise ValueError("Energy undefined: a non-conservative force is active")
    e = np.asarray(energies)
    return (e - e[0]) / abs(e[0])


def round_trip_error(dynamics: DynamicsModel, initial: State, duration: float, **kwargs) -> tuple[float, float]:
    """Propagate forward then backward; returns (position error km, velocity error km/s)."""
    fwd = propagate(dynamics, initial, duration, dense=False, **kwargs)
    back = propagate(dynamics, fwd.final, -duration, dense=False, **kwargs)
    d = back.final.vector - initial.vector
    return float(np.linalg.norm(d[:3])), float(np.linalg.norm(d[3:]))


def jacobi_constant(state_rot: np.ndarray, mu: float) -> float:
    """CR3BP Jacobi constant for a nondimensional rotating-frame state
    (primaries at -mu and 1-mu on the x axis)."""
    x, y, z, vx, vy, vz = state_rot
    r1 = np.sqrt((x + mu) ** 2 + y**2 + z**2)
    r2 = np.sqrt((x - 1 + mu) ** 2 + y**2 + z**2)
    return float(x**2 + y**2 + 2 * (1 - mu) / r1 + 2 * mu / r2 - (vx**2 + vy**2 + vz**2))
