"""B-plane geometry of a hyperbolic approach.

The B-plane is perpendicular to the incoming asymptote S and contains the
target body's centre. The B vector points from the centre to where the
asymptote pierces it; |B| is the impact parameter b. Targeting (B·T, B·R) or
(b, inclination) is far better conditioned than targeting the periapsis
directly, because these quantities stay smooth even for trajectories that would
hit the body. That is why the TLI -> LOI designer solves in the B-plane first.

    T = S x k / |S x k|   (k = reference pole, here the lunar pole)
    R = S x T
    b = h / v_inf
    cos(i) = cos(theta) * cos(dec_S),   B = b (cos(theta) T + sin(theta) R)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class BPlane:
    b: float              # impact parameter, km
    b_dot_t: float        # km
    b_dot_r: float        # km
    theta: float          # angle of B from T toward R, rad
    v_inf: float          # km/s
    s_hat: np.ndarray     # incoming asymptote direction
    inclination: float    # osculating inclination w.r.t. pole, rad
    rp: float             # osculating periapsis radius, km


def bplane_from_state(r: np.ndarray, v: np.ndarray, gm: float, pole: np.ndarray) -> BPlane:
    r, v, pole = np.asarray(r, float), np.asarray(v, float), np.asarray(pole, float)
    rn, vn = np.linalg.norm(r), np.linalg.norm(v)
    energy = vn**2 / 2 - gm / rn
    if energy <= 0:
        raise ValueError("B-plane undefined: orbit is not hyperbolic relative to the target")
    v_inf = np.sqrt(2 * energy)
    h = np.cross(r, v)
    hn = np.linalg.norm(h)
    e_vec = ((vn**2 - gm / rn) * r - np.dot(r, v) * v) / gm
    ecc = np.linalg.norm(e_vec)
    p_hat = e_vec / ecc
    h_hat = h / hn
    q_hat = np.cross(h_hat, p_hat)
    s_hat = p_hat / ecc + np.sqrt(1 - 1 / ecc**2) * q_hat
    t_vec = np.cross(s_hat, pole)
    t_hat = t_vec / np.linalg.norm(t_vec)
    r_hat = np.cross(s_hat, t_hat)
    b_vec = (hn / v_inf) * np.cross(s_hat, h_hat)
    bt, br = float(np.dot(b_vec, t_hat)), float(np.dot(b_vec, r_hat))
    sma = -gm / v_inf**2
    return BPlane(
        b=float(np.linalg.norm(b_vec)), b_dot_t=bt, b_dot_r=br, theta=float(np.arctan2(br, bt)),
        v_inf=float(v_inf), s_hat=s_hat, inclination=float(np.arccos(np.clip(np.dot(h_hat, pole), -1, 1))),
        rp=float(sma * (1 - ecc)),
    )


def impact_parameter_for_periapsis(rp: float, v_inf: float, gm: float) -> float:
    return rp * np.sqrt(1 + 2 * gm / (rp * v_inf**2))


def bplane_angle_for_inclination(inc: float, s_hat: np.ndarray, pole: np.ndarray, family: int = +1) -> float:
    """theta that yields inclination `inc` for asymptote s_hat. family = +1 / -1
    selects one of the two solutions (opposite node geometries). If inc is
    below the asymptote declination (unreachable), returns the closest theta."""
    cos_dec = np.sqrt(max(0.0, 1 - np.dot(s_hat, pole) ** 2))
    c = np.clip(np.cos(inc) / cos_dec, -1, 1) if cos_dec > 1e-12 else 1.0
    return family * float(np.arccos(c))


def hyperbolic_time_to_periapsis(r: np.ndarray, v: np.ndarray, gm: float) -> float:
    """Two-body time from the current (inbound) state to periapsis."""
    rn, vn = np.linalg.norm(r), np.linalg.norm(v)
    sma = -gm / (vn**2 - 2 * gm / rn) if vn**2 != 2 * gm / rn else -np.inf
    e_vec = ((vn**2 - gm / rn) * r - np.dot(r, v) * v) / gm
    ecc = np.linalg.norm(e_vec)
    cosh_f = (1 - rn / sma) / ecc
    f = np.arccosh(max(1.0, cosh_f))
    mean = ecc * np.sinh(f) - f
    t = mean * np.sqrt(-sma**3 / gm)
    return float(t if np.dot(r, v) < 0 else -t)
