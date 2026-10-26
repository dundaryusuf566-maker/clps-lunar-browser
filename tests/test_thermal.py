"""Regolith thermal model (Hayne et al. 2017): analytic limits, conservation,
convergence, and the Diviner equatorial temperatures."""

import numpy as np

from engine.surface.thermal import (
    LUNATION_S, SIGMA, Column, Grid, Regolith, absorbed_flux, albedo, heat_capacity, skin_depth,
)

P = LUNATION_S
_trapz = getattr(np, "trapezoid", None) or np.trapz      # numpy < 2.0


def _equator(column: Column, n: int = 720, cycles: int = 6):
    t = np.arange(0, P + 1, P / n)
    h = 2 * np.pi * t / P                          # hour angle, 0 = local noon
    F = absorbed_flux(np.cos(h), 1.0, 1.0, column.r)[None, :]
    column.spin_up(t, F, cycles=cycles)
    T = column.run(t, F)["surface"][0]
    lt = (h / (2 * np.pi) * 24 + 12) % 24
    at = lambda hour: float(T[np.argmin(np.abs(lt - hour))])   # noqa: E731
    return {"noon": at(12), "midnight": at(0), "predawn": at(5.9), "T": T, "F": F[0], "t": t}


def test_constants_and_laws():
    r = Regolith()
    assert abs(albedo(0.0) - 0.12) < 1e-12
    assert abs(albedo(np.pi / 2) - (0.12 + 0.06 * 8 + 0.25)) < 1e-12           # grazing light is reflected more
    assert 700 < heat_capacity(300.0) < 800 and 100 < heat_capacity(40.0) < 130   # J/kg/K, regolith-like
    assert heat_capacity(0.5) > 0                                                # floored, never negative
    g = Grid.build(r)
    assert abs(g.rho[0] - r.rho_s) < 1e-9 and abs(g.kc[0] - r.k_s) < 1e-12
    assert g.rho[-1] > 1790 and g.kc[-1] > 3.3e-3                                # deep values reached
    assert g.h[0] < 0.2 * skin_depth(r.k_s, r.rho_s, 600.0, P)
    assert float(absorbed_flux(-0.1, 1.0, 1.0)) == 0.0


def test_equator_matches_diviner():
    """Vasavada et al. (2012), quoted by Hayne et al. (2017): typical equatorial
    temperatures ~385 K at noon, 101 K at midnight, 95 K just before sunrise."""
    e = _equator(Column(1))
    assert abs(e["noon"] - 385) < 5, e["noon"]
    assert abs(e["midnight"] - 101) < 5, e["midnight"]
    assert abs(e["predawn"] - 95) < 5, e["predawn"]


def test_noon_is_near_radiative_equilibrium():
    """At noon conduction is a small term: T ~ ((1 - A) S / eps sigma)^(1/4)."""
    r = Regolith()
    e = _equator(Column(1))
    t_eq = ((1 - r.A0) * r.S / (r.emissivity * SIGMA)) ** 0.25
    assert abs(e["noon"] - t_eq) < 1.5


def test_energy_balance_over_a_lunation():
    """In the periodic state, sunlight absorbed + heat from the interior = heat radiated."""
    r = Regolith()
    e = _equator(Column(1), cycles=8)
    absorbed = _trapz(e["F"], e["t"]) / P
    emitted = _trapz(r.emissivity * SIGMA * e["T"] ** 4, e["t"]) / P
    assert abs(absorbed + r.Q_geo - emitted) / emitted < 0.01


def test_diurnal_wave_decays_with_the_skin_depth():
    """Uniform soil, temperature-independent properties, small forcing: the
    temperature wave decays as exp(-z/d) with d = sqrt(kappa P / pi)."""
    r = Regolith(rho_s=1500.0, rho_d=1500.0, k_s=2e-3, k_d=2e-3, chi=0.0, cp=(600.0, 0, 0, 0, 0), Q_geo=0.0)
    c = Column(1, r, Grid.build(r, depth_m=0.6))
    t = np.arange(0, P + 1, P / 720)
    F = (600.0 + 40.0 * np.cos(2 * np.pi * t / P))[None, :]
    assert c.spin_up(t, F, cycles=10)[-1] < 0.1
    z1, z2 = 0.02, 0.06
    res = c.run(t, F, depths_m=(z1, z2))
    zz = [c.g.z[i] for i in res["depth_index"]]
    amp = [np.ptp(res["depth"][z]) / 2 for z in (z1, z2)]
    d = skin_depth(2e-3, 1500.0, 600.0, P)
    expected = np.exp(-(zz[1] - zz[0]) / d)
    assert abs(amp[1] / amp[0] - expected) / expected < 0.05


def test_grid_and_time_step_convergence():
    coarse = _equator(Column(1), n=720)
    r = Regolith()
    fine = _equator(Column(1, r, Grid.build(r, first_frac=0.05, growth=1.1)), n=1440)
    for k in ("noon", "midnight", "predawn"):
        assert abs(coarse[k] - fine[k]) < 1.0, (k, coarse[k], fine[k])
