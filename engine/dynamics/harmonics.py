"""Zonal spherical-harmonic gravity of the central body (degree 2..N).

Potential (a = -grad U):
    U_n = + GM Jn Rⁿ / r^(n+1) * Pn(s),   s = (r̂ · pole)
Acceleration of degree n:
    a_n = GM Jn Rⁿ / r^(n+2) * [ ((n+1) Pn(s) + s Pn'(s)) r̂ - Pn'(s) pole ]

Zonal terms matter enormously at the Moon: the odd zonals (J3, J5, J7) are what
create lunar frozen orbits. Tesseral terms (C22 etc.) will come with the full
GRAIL field in `harmonics_full.py`.
"""

from __future__ import annotations

import numpy as np

from ..core.constants import body as get_body
from .base import DynamicsContext, ForceModel


def legendre_with_derivative(n_max: int, s: float) -> tuple[np.ndarray, np.ndarray]:
    """P_n(s) and P_n'(s) for n = 0..n_max via the standard recurrences."""
    p = np.zeros(n_max + 1)
    dp = np.zeros(n_max + 1)
    p[0] = 1.0
    if n_max >= 1:
        p[1], dp[1] = s, 1.0
    for n in range(1, n_max):
        p[n + 1] = ((2 * n + 1) * s * p[n] - n * p[n - 1]) / (n + 1)
        dp[n + 1] = (n + 1) * p[n] + s * dp[n]
    return p, dp


class ZonalHarmonics(ForceModel):
    def __init__(
        self,
        body: str,
        degree: int | None = None,
        zonals: dict[int, float] | None = None,
        gm: float | None = None,
        radius: float | None = None,
        fixed_pole: np.ndarray | None = None,
    ):
        b = get_body(body)
        self.body = b.name
        self.gm = gm if gm is not None else b.gm
        self.radius = radius if radius is not None else b.radius
        coeffs = dict(zonals if zonals is not None else b.zonals)
        if degree is not None:
            coeffs = {n: j for n, j in coeffs.items() if n <= degree}
        if not coeffs:
            raise ValueError(f"No zonal coefficients for {self.body}")
        self.coeffs = coeffs
        self.n_max = max(coeffs)
        self.fixed_pole = None if fixed_pole is None else np.asarray(fixed_pole, float) / np.linalg.norm(fixed_pole)
        self.name = f"{self.body.lower()}_zonal_J2-J{self.n_max}"

    def _pole(self, t, ctx) -> np.ndarray:
        if self.fixed_pole is not None:
            return self.fixed_pole
        return ctx.ephemeris.pole(self.body, t)

    def acceleration(self, t, r, v, ctx: DynamicsContext) -> np.ndarray:
        pole = self._pole(t, ctx)
        rn = np.linalg.norm(r)
        rhat = r / rn
        s = float(np.dot(rhat, pole))
        p, dp = legendre_with_derivative(self.n_max, s)
        a = np.zeros(3)
        for n, jn in self.coeffs.items():
            k = self.gm * jn * self.radius**n / rn ** (n + 2)
            a += k * (((n + 1) * p[n] + s * dp[n]) * rhat - dp[n] * pole)
        return a

    def potential(self, t, r, ctx) -> float:
        pole = self._pole(t, ctx)
        rn = np.linalg.norm(r)
        s = float(np.dot(r / rn, pole))
        p, _ = legendre_with_derivative(self.n_max, s)
        return sum(self.gm * jn * self.radius**n / rn ** (n + 1) * p[n] for n, jn in self.coeffs.items())

    def describe(self):
        return {**super().describe(), "body": self.body, "degree": self.n_max, "coefficients": self.coeffs}
