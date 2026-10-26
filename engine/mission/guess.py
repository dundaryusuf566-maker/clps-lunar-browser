"""Patched-conic initial guess for a TLI -> lunar arrival.

Ignores the Moon's gravity: finds the Earth-centred transfer ellipse from a
circular parking orbit whose spacecraft reaches the "aim point" (Moon centre +
desired B vector) exactly at TLI epoch + time of flight. The full-force solver
then corrects this guess; typically the guess is within a few thousand km.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq

from ..core.constants import BODIES
from ..orbits.bplane import bplane_angle_for_inclination, impact_parameter_for_periapsis

EARTH, MOON = BODIES["EARTH"], BODIES["MOON"]


@dataclass
class TliGuess:
    raan: float          # parking-orbit RAAN, rad
    inc: float           # parking-orbit inclination, rad
    arg_lat: float       # argument of latitude of the TLI point, rad
    dv: float            # tangential TLI delta-v, km/s
    apogee_radius: float # km
    arrival_true_anomaly: float
    branch: str          # "outbound" (before apogee) or "inbound"
    aim: np.ndarray      # geocentric aim point at arrival (Moon centre + B vector), km


def _tof_to_radius(r_p: float, r_a: float, r: float, inbound: bool) -> tuple[float, float]:
    """Two-body time from perigee to radius r and the true anomaly there."""
    a = 0.5 * (r_p + r_a)
    e = (r_a - r_p) / (r_a + r_p)
    cos_e = np.clip((1 - r / a) / e, -1, 1)
    ecc_anom = np.arccos(cos_e)
    n = np.sqrt(EARTH.gm / a**3)
    t = (ecc_anom - e * np.sin(ecc_anom)) / n
    nu = 2 * np.arctan2(np.sqrt(1 + e) * np.sin(ecc_anom / 2), np.sqrt(1 - e) * np.cos(ecc_anom / 2))
    if inbound:
        return 2 * np.pi / n - t, 2 * np.pi - nu
    return t, nu


def solve_transfer_ellipse(r_p: float, r_arr: float, tof: float) -> tuple[float, float, str]:
    """Apogee radius and arrival true anomaly that reach radius r_arr in tof."""
    t_half, _ = _tof_to_radius(r_p, r_arr, r_arr, inbound=False)
    inbound = tof > t_half
    def f(r_a):
        return _tof_to_radius(r_p, r_a, r_arr, inbound)[0] - tof
    lo, hi = r_arr * (1 + 1e-9), r_arr * 50
    if np.sign(f(lo)) == np.sign(f(hi)):
        raise ValueError(f"No conic transfer reaches {r_arr:.0f} km in {tof / 86400:.2f} days")
    r_a = brentq(f, lo, hi, xtol=1e-6)
    return r_a, _tof_to_radius(r_p, r_a, r_arr, inbound)[1], "inbound" if inbound else "outbound"


def _plane_raan_containing(point: np.ndarray, inc: float, branch: int = 0) -> float:
    """RAAN of an orbit plane with inclination inc that contains `point`."""
    alpha = np.arctan2(point[1], point[0])
    dec = np.arcsin(point[2] / np.linalg.norm(point))
    x = np.clip(-np.tan(dec) / np.tan(inc), -1, 1)  # unreachable dec -> closest plane
    return float((alpha + np.arcsin(x)) if branch == 0 else (alpha + np.pi - np.arcsin(x))) % (2 * np.pi)


def conic_tli_guess(ephemeris, tli_epoch: float, tof: float, parking_alt: float, parking_inc: float,
                    periselene_radius: float, lunar_inc: float, family: int = +1,
                    plane_branch: int = 0, iterations: int = 3, inc_free: bool = False,
                    inc_margin: float = np.radians(1.0), inc_max: float = np.radians(60.0)) -> TliGuess:
    """parking_inc is the nominal (or, with inc_free, the minimum) inclination.
    With inc_free the plane is tilted to at least |dec(aim)| + inc_margin so it
    is never tangent to the aim point (that geometry is singular for RAAN)."""
    r_p = EARTH.radius + parking_alt
    t_arr = tli_epoch + tof
    moon = ephemeris.state("MOON", "EARTH", t_arr)
    pole = ephemeris.pole("MOON", t_arr)
    aim = moon[:3].copy()

    for _ in range(iterations):
        aim_used = aim.copy()  # geometry below is built for this aim point
        r_arr = np.linalg.norm(aim)
        r_a, nu_arr, branch = solve_transfer_ellipse(r_p, r_arr, tof)
        inc = parking_inc
        if inc_free:
            dec_aim = abs(np.arcsin(aim[2] / r_arr))
            inc = float(np.clip(max(parking_inc, dec_aim + inc_margin), parking_inc, inc_max))
        raan = _plane_raan_containing(aim, inc, plane_branch)
        n_hat = np.array([np.sin(inc) * np.sin(raan), -np.sin(inc) * np.cos(raan), np.cos(inc)])
        # Project aim into the plane (exact when the plane is reachable).
        p_hat = aim - np.dot(aim, n_hat) * n_hat
        p_hat /= np.linalg.norm(p_hat)
        q_hat = np.cross(n_hat, p_hat)
        perigee_dir = np.cos(nu_arr) * p_hat - np.sin(nu_arr) * q_hat

        # Spacecraft velocity at arrival on the conic -> approach asymptote estimate.
        a = 0.5 * (r_p + r_a)
        e = (r_a - r_p) / (r_a + r_p)
        p = a * (1 - e**2)
        perp = np.cross(n_hat, perigee_dir)
        v_arr = np.sqrt(EARTH.gm / p) * (-np.sin(nu_arr) * perigee_dir + (e + np.cos(nu_arr)) * perp)
        v_rel = v_arr - moon[3:]
        v_inf = np.linalg.norm(v_rel)
        s_hat = v_rel / v_inf
        b = impact_parameter_for_periapsis(periselene_radius, v_inf, MOON.gm)
        theta = bplane_angle_for_inclination(lunar_inc, s_hat, pole, family)
        t_hat = np.cross(s_hat, pole)
        t_hat /= np.linalg.norm(t_hat)
        r_hat = np.cross(s_hat, t_hat)
        aim = moon[:3] + b * (np.cos(theta) * t_hat + np.sin(theta) * r_hat)

    node = np.array([np.cos(raan), np.sin(raan), 0.0])
    arg_lat = np.arctan2(np.dot(perigee_dir, np.cross(n_hat, node)), np.dot(perigee_dir, node)) % (2 * np.pi)
    dv = np.sqrt(EARTH.gm * (2 / r_p - 1 / a)) - np.sqrt(EARTH.gm / r_p)
    return TliGuess(raan, inc, float(arg_lat), float(dv), float(r_a), float(nu_arr), branch, aim_used)
