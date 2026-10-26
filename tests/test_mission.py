from datetime import datetime, timezone

import numpy as np

from engine.core.constants import BODIES
from engine.core.state import State
from engine.core.time import utc_to_tdb
from engine.dynamics import DynamicsModel, PointMassGravity
from engine.ephemeris import AnalyticEphemeris
from engine.mission import TransferSpec, conic_tli_guess, design_transfer
from engine.orbits import Elements, elements_to_cartesian
from engine.orbits.bplane import (
    bplane_angle_for_inclination, bplane_from_state, hyperbolic_time_to_periapsis,
    impact_parameter_for_periapsis,
)
from engine.propagators import propagate
from engine.targeting import CallableResidual, Control, ControlVector, Evaluation, TargetingProblem, solve

EPH = AnalyticEphemeris()
MOON, EARTH = BODIES["MOON"], BODIES["EARTH"]
Z = np.array([0.0, 0.0, 1.0])


def _hyperbola(rp=1838.0, v_inf=0.8, inc=np.radians(70), raan=0.4, argp=1.1):
    sma = -MOON.gm / v_inf**2
    ecc = 1 - rp / sma
    p = sma * (1 - ecc**2)
    nu = -np.arccos((p / 40_000.0 - 1) / ecc)  # inbound at 40 000 km
    return elements_to_cartesian(Elements(sma, ecc, inc, raan, argp, nu), MOON.gm), rp, v_inf, inc


def test_bplane_of_known_hyperbola():
    y, rp, v_inf, inc = _hyperbola()
    bp = bplane_from_state(y[:3], y[3:], MOON.gm, Z)
    assert abs(bp.rp - rp) < 1e-6
    assert abs(bp.v_inf - v_inf) < 1e-12
    assert abs(bp.inclination - inc) < 1e-10
    assert abs(bp.b - impact_parameter_for_periapsis(rp, v_inf, MOON.gm)) < 1e-6
    # cos(i) = cos(theta) cos(dec_S)
    cos_dec = np.sqrt(1 - np.dot(bp.s_hat, Z) ** 2)
    assert abs(np.cos(inc) - np.cos(bp.theta) * cos_dec) < 1e-10
    theta = bplane_angle_for_inclination(inc, bp.s_hat, Z, family=int(np.sign(bp.theta)))
    assert abs(theta - bp.theta) < 1e-9


def test_hyperbolic_time_to_periapsis():
    y, rp, *_ = _hyperbola()
    dt = hyperbolic_time_to_periapsis(y[:3], y[3:], MOON.gm)
    dyn = DynamicsModel("MOON", EPH, [PointMassGravity("MOON")])
    final = propagate(dyn, State(0.0, y, "MOON"), dt).final
    assert abs(np.linalg.norm(final.r) - rp) < 1e-4
    cos_flight_path = np.dot(final.r, final.v) / (np.linalg.norm(final.r) * np.linalg.norm(final.v))
    assert abs(cos_flight_path) < 1e-8


def test_conic_guess_reaches_aim_point_two_body():
    # 2026-02-12 arrival: aim declination ~ -29 deg, beyond a 28.5 deg parking orbit.
    t0 = utc_to_tdb(datetime(2026, 2, 7, tzinfo=timezone.utc))
    tof = 5 * 86_400.0
    dyn = DynamicsModel("EARTH", EPH, [PointMassGravity("EARTH")])
    for inc_free in (False, True):
        g = conic_tli_guess(EPH, t0, tof, 185.0, np.radians(28.5), MOON.radius + 100, np.radians(90), inc_free=inc_free)
        el = Elements(EARTH.radius + 185.0, 0.0, g.inc, g.raan, 0.0, g.arg_lat)
        s0 = State(t0, elements_to_cartesian(el, EARTH.gm), "EARTH")
        s0 = s0.with_delta_v(g.dv * s0.v / np.linalg.norm(s0.v))
        final = propagate(dyn, s0, tof).final
        miss = np.linalg.norm(final.r - g.aim)
        if inc_free:
            assert g.inc > np.radians(28.5) and miss < 0.01, miss  # km
        else:
            # Unreachable plane: arrival is at the aim radius, in the direction of
            # the aim point projected into the parking plane.
            n_hat = np.cross(s0.r, s0.v) / np.linalg.norm(np.cross(s0.r, s0.v))
            proj = g.aim - np.dot(g.aim, n_hat) * n_hat
            expected = np.linalg.norm(np.linalg.norm(g.aim) * proj / np.linalg.norm(proj) - g.aim)
            assert miss > 1000 and abs(miss - expected) < 0.01


def test_active_set_keeps_bounded_control_on_bound():
    # f = a + b - 3 with a <= 1: the plain min-norm step would push a past its bound.
    cv = ControlVector([Control("a", 1.0, upper=1.0), Control("b", 0.0)])
    res = CallableResidual("sum", lambda ev: ev.data["a"] + ev.data["b"], 3.0, 1e-9)
    prob = TargetingProblem("bounded", cv, [res], lambda c: Evaluation(data=dict(c)))
    out = solve(prob, method="newton")
    assert out.converged and out.iterations <= 2
    assert out.controls["a"] == 1.0 and abs(out.controls["b"] - 2.0) < 1e-9


def test_tli_to_loi_transfer_converges():
    spec = TransferSpec(utc_to_tdb(datetime(2026, 1, 11, tzinfo=timezone.utc)), tof_days=5.0, family=+1)
    sol = design_transfer(EPH, spec)
    m = sol.metrics
    assert sol.converged, sol.summary()
    assert abs(m["periselene_alt_km"] - 100.0) <= 0.1
    assert abs(m["lunar_inc_deg"] - 90.0) <= 0.001
    assert abs(m["tof_days"] - 5.0) * 86_400 <= 1.0
    assert 3000 < m["tli_dv_ms"] < 3250
    assert -2.5 < m["c3_km2s2"] < -1.0
    assert 750 < m["loi_dv_ms"] < 900
    # This date is at the major lunar standstill: this family needs the launch
    # azimuth to raise the parking inclination above 28.5 deg.
    assert m["parking_inc_deg"] > 28.6
    row = sol.to_row()
    assert row["converged"] and "loi_dv_ms" in row and row["tli_utc"].startswith("2026-01-11")
