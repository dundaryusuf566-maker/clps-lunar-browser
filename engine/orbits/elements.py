"""Classical orbital elements <-> Cartesian state.

Elements can be expressed relative to any reference frame by passing a rotation
matrix `frame` (inertial -> reference), e.g. the lunar equator or the Moon-Sun
frame used for RAAN(Moon-Sun).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

_TINY = 1e-11


@dataclass
class Elements:
    sma: float        # km (negative for hyperbolic)
    ecc: float
    inc: float        # rad
    raan: float       # rad
    argp: float       # rad
    nu: float         # true anomaly, rad

    def as_degrees(self) -> dict:
        d = asdict(self)
        for k in ("inc", "raan", "argp", "nu"):
            d[k] = float(np.degrees(d[k]))
        return d

    def periapsis_radius(self) -> float:
        return self.sma * (1 - self.ecc)

    def apoapsis_radius(self) -> float:
        return self.sma * (1 + self.ecc) if self.ecc < 1 else np.inf


def cartesian_to_elements(r, v, gm: float, frame: np.ndarray | None = None) -> Elements:
    r = np.asarray(r, float)
    v = np.asarray(v, float)
    if frame is not None:
        r, v = frame @ r, frame @ v
    rn, vn = np.linalg.norm(r), np.linalg.norm(v)
    h = np.cross(r, v)
    hn = np.linalg.norm(h)
    n = np.cross([0.0, 0.0, 1.0], h)
    nn = np.linalg.norm(n)
    e_vec = ((vn**2 - gm / rn) * r - np.dot(r, v) * v) / gm
    ecc = np.linalg.norm(e_vec)
    energy = vn**2 / 2 - gm / rn
    sma = -gm / (2 * energy) if abs(energy) > _TINY else np.inf
    inc = np.arccos(np.clip(h[2] / hn, -1, 1))

    equatorial = nn <= _TINY
    if not equatorial:
        raan = np.arctan2(n[1], n[0]) % (2 * np.pi)
    else:  # node undefined: measure from the x-axis
        raan, n, nn = 0.0, np.array([1.0, 0.0, 0.0]), 1.0
    # Quadrant test for angles measured from the node line.
    def _below(vec):
        return vec[1] < 0 if equatorial else vec[2] < 0

    if ecc > _TINY:
        argp = np.arccos(np.clip(np.dot(n, e_vec) / (nn * ecc), -1, 1))
        if _below(e_vec):
            argp = 2 * np.pi - argp
        nu = np.arccos(np.clip(np.dot(e_vec, r) / (ecc * rn), -1, 1))
        if np.dot(r, v) < 0:
            nu = 2 * np.pi - nu
    else:  # circular: periapsis undefined, nu = argument of latitude
        argp = 0.0
        nu = np.arccos(np.clip(np.dot(n, r) / (nn * rn), -1, 1))
        if _below(r):
            nu = 2 * np.pi - nu
    return Elements(sma, ecc, inc, raan, argp, nu)


def elements_to_cartesian(el: Elements, gm: float, frame: np.ndarray | None = None) -> np.ndarray:
    p = el.sma * (1 - el.ecc**2)
    r_pf = p / (1 + el.ecc * np.cos(el.nu)) * np.array([np.cos(el.nu), np.sin(el.nu), 0.0])
    v_pf = np.sqrt(gm / p) * np.array([-np.sin(el.nu), el.ecc + np.cos(el.nu), 0.0])
    cO, sO = np.cos(el.raan), np.sin(el.raan)
    ci, si = np.cos(el.inc), np.sin(el.inc)
    cw, sw = np.cos(el.argp), np.sin(el.argp)
    q = np.array([
        [cO * cw - sO * sw * ci, -cO * sw - sO * cw * ci, sO * si],
        [sO * cw + cO * sw * ci, -sO * sw + cO * cw * ci, -cO * si],
        [sw * si, cw * si, ci],
    ])
    r, v = q @ r_pf, q @ v_pf
    if frame is not None:  # back from reference frame to inertial
        r, v = frame.T @ r, frame.T @ v
    return np.concatenate([r, v])


def orbital_period(sma: float, gm: float) -> float:
    return 2 * np.pi * np.sqrt(sma**3 / gm)
