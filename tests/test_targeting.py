import numpy as np

from engine.core.constants import BODIES
from engine.core.state import State
from engine.dynamics import DynamicsModel, PointMassGravity
from engine.ephemeris import AnalyticEphemeris
from engine.orbits import Elements, elements_to_cartesian
from engine.propagators import propagate
from engine.targeting import (
    Bound, CallableResidual, Control, ControlVector, DataResidual, Evaluation, FinalElement, TargetingProblem,
    final_position_residuals, solve, wrap_angle,
)

EPH = AnalyticEphemeris()
EARTH = BODIES["EARTH"]
DYN = DynamicsModel("EARTH", EPH, [PointMassGravity("EARTH")])
TOF = 3000.0


def _truth():
    el = Elements(8000.0, 0.1, np.radians(30), 0.4, 0.2, 0.1)
    y0 = elements_to_cartesian(el, EARTH.gm)
    target = propagate(DYN, State(0.0, y0, "EARTH"), TOF).final.r
    return y0, target


def _simulator(r0):
    def simulate(c):
        s0 = State(0.0, np.concatenate([r0, [c["vx"], c["vy"], c["vz"]]]), "EARTH")
        traj = propagate(DYN, s0, TOF, dense=False)
        return Evaluation(final=traj.final, segments={"coast": traj})
    return simulate


def _controls(v_guess):
    return ControlVector([Control(n, float(v), scale=1.0, fd_step=1e-7, unit="km/s") for n, v in zip(("vx", "vy", "vz"), v_guess)])


def test_newton_recovers_shooting_solution():
    y0, target = _truth()
    guess = y0[3:] + np.array([0.05, -0.03, 0.02])
    prob = TargetingProblem("lambert-shoot", _controls(guess), final_position_residuals(target, 1e-6), _simulator(y0[:3]))
    res = solve(prob, method="newton")
    assert res.converged, res.summary()
    np.testing.assert_allclose([res.controls[k] for k in ("vx", "vy", "vz")], y0[3:], atol=1e-8)
    assert res.iterations <= 8


def test_lm_recovers_shooting_solution():
    y0, target = _truth()
    guess = y0[3:] + np.array([0.05, -0.03, 0.02])
    prob = TargetingProblem("lambert-shoot-lm", _controls(guess), final_position_residuals(target, 1e-6), _simulator(y0[:3]))
    res = solve(prob, method="lm")
    assert res.converged, res.summary()


def test_underdetermined_min_norm():
    # 3 controls, 1 residual (final radius): many solutions; the min-norm Newton
    # step should find one close to the starting guess.
    y0, target = _truth()
    goal = np.linalg.norm(target) + 300.0
    radius = CallableResidual("final_radius", lambda ev: np.linalg.norm(ev.final.r), goal, 1e-6, unit="km")
    prob = TargetingProblem("radius-only", _controls(y0[3:]), [radius], _simulator(y0[:3]))
    res = solve(prob, method="newton")
    assert res.converged, res.summary()
    dv = np.linalg.norm([res.controls[k] for k in ("vx", "vy", "vz")] - y0[3:])
    assert dv < 0.2  # km/s: stayed near the guess


def test_final_element_periapsis_altitude():
    y0, _ = _truth()
    ev = Evaluation(final=State(0.0, y0, "EARTH"))
    alt = FinalElement("periapsis_alt", 0.0, 1.0, EARTH.gm, body_radius=EARTH.radius)
    assert abs(alt.measure(ev) - (8000.0 * 0.9 - EARTH.radius)) < 1e-6


def test_angular_residual_wraps():
    class Fake(DataResidual):
        pass
    r = Fake("raan", target=np.radians(359), tolerance=np.radians(0.01), angular=True)
    ev = Evaluation(data={"raan": np.radians(1)})
    assert abs(np.degrees(r.error(ev)) - 2.0) < 1e-9
    assert abs(wrap_angle(3 * np.pi) + np.pi) < 1e-12


def test_bound_residual():
    inner = DataResidual("dv", 0.0, 1.0, unit="m/s")
    b = Bound(inner, lower=0.0, upper=900.0)
    assert b.error(Evaluation(data={"dv": 850.0})) == 0.0
    assert b.error(Evaluation(data={"dv": 950.0})) == 50.0
