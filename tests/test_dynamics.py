import numpy as np

from engine.core.constants import BODIES
from engine.core.state import State
from engine.dynamics import (
    DynamicsModel, PointMassGravity, SolarRadiationPressure, ThirdBodyGravity, ZonalHarmonics,
    earth_moon_model,
)
from engine.ephemeris import AnalyticEphemeris
from engine.orbits import Elements, cartesian_to_elements, elements_to_cartesian, orbital_period
from engine.propagators import Apoapsis, Impact, Periapsis, propagate
from engine.validation import energy_drift, round_trip_error

EPH = AnalyticEphemeris()
EARTH, MOON = BODIES["EARTH"], BODIES["MOON"]
Z = np.array([0.0, 0.0, 1.0])


def _leo_state(alt=400.0, inc=51.6):
    el = Elements(EARTH.radius + alt, 0.0, np.radians(inc), 0.3, 0.0, 0.0)
    return State(0.0, elements_to_cartesian(el, EARTH.gm), "EARTH"), el


def test_two_body_period_closure():
    dyn = DynamicsModel("EARTH", EPH, [PointMassGravity("EARTH")])
    s0, el = _leo_state()
    traj = propagate(dyn, s0, orbital_period(el.sma, EARTH.gm))
    assert np.linalg.norm(traj.final.r - s0.r) < 1e-5  # km
    assert np.max(np.abs(energy_drift(traj))) < 1e-11


def test_zonal_acceleration_is_minus_gradient_of_potential():
    f = ZonalHarmonics("MOON", fixed_pole=Z)
    dyn = DynamicsModel("MOON", EPH, [f])
    for r in [np.array([1900.0, 300.0, 800.0]), np.array([-500.0, 1200.0, -1700.0])]:
        h = 1e-3
        grad = np.array([
            (f.potential(0, r + h * e, dyn.ctx) - f.potential(0, r - h * e, dyn.ctx)) / (2 * h)
            for e in np.eye(3)
        ])
        np.testing.assert_allclose(f.acceleration(0, r, None, dyn.ctx), -grad, rtol=1e-6, atol=1e-16)


def test_lunar_zonal_energy_conserved():
    dyn = DynamicsModel("MOON", EPH, [PointMassGravity("MOON"), ZonalHarmonics("MOON", fixed_pole=Z)])
    el = Elements(MOON.radius + 100, 0.05, np.radians(80), 1.0, 2.0, 0.0)
    s0 = State(0.0, elements_to_cartesian(el, MOON.gm), "MOON")
    traj = propagate(dyn, s0, 86_400.0)
    assert np.max(np.abs(energy_drift(traj))) < 1e-10


def test_j2_nodal_regression_matches_theory():
    dyn = DynamicsModel("EARTH", EPH, [PointMassGravity("EARTH"), ZonalHarmonics("EARTH", degree=2, fixed_pole=Z)])
    s0, el = _leo_state()
    duration = 2 * 86_400.0
    traj = propagate(dyn, s0, duration)
    ts, ys = traj.sample(400)
    raan = np.unwrap([cartesian_to_elements(y[:3], y[3:], EARTH.gm).raan for y in ys])
    rate_numeric = np.polyfit(ts, raan, 1)[0]
    n = np.sqrt(EARTH.gm / el.sma**3)
    rate_theory = -1.5 * n * EARTH.zonals[2] * (EARTH.radius / el.sma) ** 2 * np.cos(el.inc)
    assert abs(rate_numeric / rate_theory - 1) < 0.02


def test_third_body_tidal_limit():
    f = ThirdBodyGravity("MOON")
    dyn = DynamicsModel("EARTH", EPH, [f])
    rb = dyn.ctx.body_position("MOON", 0.0)
    assert np.linalg.norm(f.acceleration(0.0, np.zeros(3), None, dyn.ctx)) < 1e-20
    r = 1e4 * rb / np.linalg.norm(rb)  # 10 000 km toward the Moon
    expected = 2 * MOON.gm * 1e4 / np.linalg.norm(rb) ** 3
    assert abs(np.linalg.norm(f.acceleration(0.0, r, None, dyn.ctx)) / expected - 1) < 0.1


def test_breakdown_sums_to_total():
    dyn = earth_moon_model("MOON", EPH, fidelity="high")
    y = np.array([1900.0, 200.0, 300.0, 0.1, 1.5, 0.2])
    total = dyn.acceleration(1e6, y)
    np.testing.assert_allclose(sum(dyn.breakdown(1e6, y).values()), total, rtol=1e-14)


def test_srp_magnitude_and_shadow():
    srp = SolarRadiationPressure()
    dyn = DynamicsModel("EARTH", EPH, [srp])
    sc = dyn.spacecraft
    r_sun = dyn.ctx.body_position("SUN", 0.0)
    u = r_sun / np.linalg.norm(r_sun)
    lit = srp.acceleration(0.0, 10_000 * u, None, dyn.ctx)
    expected = 4.56e-6 * sc.reflectivity_cr * sc.srp_area_m2 / sc.mass_kg / 1000
    assert abs(np.linalg.norm(lit) / expected - 1) < 0.05
    assert np.dot(lit, u) < 0  # pushes away from the Sun
    assert np.linalg.norm(srp.acceleration(0.0, -10_000 * u, None, dyn.ctx)) == 0.0


def test_periapsis_event_timing():
    dyn = DynamicsModel("MOON", EPH, [PointMassGravity("MOON")])
    el = Elements(3000.0, 0.3, np.radians(60), 0.0, 0.0, np.pi)  # start at apoapsis
    s0 = State(0.0, elements_to_cartesian(el, MOON.gm), "MOON")
    period = orbital_period(el.sma, MOON.gm)
    traj = propagate(dyn, s0, 1.2 * period, events=[Periapsis(), Apoapsis()])
    peri = traj.hits("periapsis")
    assert len(peri) == 1 and abs(peri[0].epoch - period / 2) < 1e-3
    assert abs(np.linalg.norm(peri[0].vector[:3]) - el.periapsis_radius()) < 1e-6


def test_impact_event_terminates():
    dyn = DynamicsModel("MOON", EPH, [PointMassGravity("MOON")])
    el = Elements(1800.0, 0.1, 0.5, 0.0, 0.0, np.pi)  # periapsis below the surface
    s0 = State(0.0, elements_to_cartesian(el, MOON.gm), "MOON")
    traj = propagate(dyn, s0, 1e5, events=[Impact()])
    assert traj.terminated_by == "impact"
    assert abs(np.linalg.norm(traj.final.r) - MOON.radius) < 1e-6


def test_round_trip_full_model():
    dyn = earth_moon_model("MOON", EPH, fidelity="medium")
    el = Elements(MOON.radius + 100, 0.0, np.radians(90), 0.0, 0.0, 0.0)
    s0 = State(1e8, elements_to_cartesian(el, MOON.gm), "MOON")
    dr, dv = round_trip_error(dyn, s0, 86_400.0)
    assert dr < 1e-4 and dv < 1e-7
