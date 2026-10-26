"""Regolith temperatures: one-dimensional heat conduction into the lunar soil.

The model and every constant are those of Hayne et al. (2017), "Global regolith
thermophysical properties of the Moon from the Diviner Lunar Radiometer
Experiment" (JGR Planets 122, doi:10.1002/2017JE005387; arXiv:1711.00977),
Appendix A and Table A1:

    density       rho(z) = rho_d - (rho_d - rho_s) exp(-z / H)
    contact cond. k_c(z) = k_d - (k_d - k_s) (rho_d - rho(z)) / (rho_d - rho_s)
    conductivity  k(z, T) = k_c(z) [1 + chi (T / 350 K)^3]        (radiation between grains)
    heat capacity c(T)    = c0 + c1 T + c2 T^2 + c3 T^3 + c4 T^4  (Hemingway et al. 1981 fit)
    albedo        A(i)    = A0 + a (i / 45 deg)^3 + b (i / 90 deg)^8  (i = solar incidence)
    surface       eps sigma T0^4 = (1 - A(i)) S cos(i) f + k dT/dz|0
    bottom        k dT/dz = Q (geothermal heat flow)

What this module adds to the paper's model is only the forcing: S cos(i) f comes
from the engine's ephemeris (Sun distance and direction), the tilt of the local
surface from the LOLA map, and f, the share of the solar disc above the LOLA
terrain horizon (the same number as the energy budget).

Not modelled here (step 2): sunlight scattered and infrared emitted by the
surrounding terrain. A shadowed point therefore cools towards the geothermal
floor; real shadows near sunlit slopes are warmer. Polar night temperatures from
this module are lower bounds.

Numerics: finite differences on a geometrically stretched grid (Hayne et al.:
first layer a tenth of the diurnal skin depth), explicit in time with the step
limited for stability (Fourier number < 0.5), surface temperature solved from the
energy balance by Newton's method at every step (the surface node has no heat
capacity), deep layers spun up with an accelerated equilibration.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

SIGMA = 5.670374419e-8          # Stefan-Boltzmann, W m^-2 K^-4
LUNATION_S = 29.530589 * 86400.0
HAYNE2017 = "https://arxiv.org/abs/1711.00977"


@dataclass(frozen=True)
class Regolith:
    """Thermophysical constants, Hayne et al. (2017) Table A1 ("standard model")."""
    rho_s: float = 1100.0        # kg m^-3, surface
    rho_d: float = 1800.0        # kg m^-3, at depth
    H: float = 0.06              # m, e-folding depth of density and conductivity
    k_s: float = 7.4e-4          # W m^-1 K^-1, surface contact conductivity
    k_d: float = 3.4e-3          # W m^-1 K^-1, deep contact conductivity
    chi: float = 2.7             # radiative conductivity parameter (at 350 K)
    emissivity: float = 0.95
    A0: float = 0.12             # Bond albedo at normal incidence
    a: float = 0.06              # albedo increase coefficients
    b: float = 0.25
    Q_geo: float = 0.018         # W m^-2, interior heat flow
    S: float = 1361.0            # W m^-2 at 1 AU (Kopp & Lean 2011)
    cp: tuple[float, ...] = (-3.6125, 2.7431, 2.3616e-3, -1.2340e-5, 8.9093e-9)

    def to_dict(self) -> dict:
        return {**asdict(self), "source": HAYNE2017}


def heat_capacity(T, r: Regolith = Regolith()) -> np.ndarray:
    """J kg^-1 K^-1; the fit goes negative below ~1.3 K, so T is floored at 2 K."""
    T = np.maximum(np.asarray(T, float), 2.0)
    c = r.cp
    return c[0] + T * (c[1] + T * (c[2] + T * (c[3] + T * c[4])))


def albedo(inc_rad, r: Regolith = Regolith()) -> np.ndarray:
    i = np.abs(np.asarray(inc_rad, float))
    return r.A0 + r.a * (i / (np.pi / 4)) ** 3 + r.b * (i / (np.pi / 2)) ** 8


def absorbed_flux(cos_inc, disc_fraction, sun_au, r: Regolith = Regolith()) -> np.ndarray:
    """Absorbed sunlight, W m^-2: (1 - A(i)) S / d^2 cos(i) f, zero when the Sun is behind the surface."""
    cos_inc = np.clip(np.asarray(cos_inc, float), -1, 1)
    inc = np.arccos(np.clip(cos_inc, 0, 1))
    lit = cos_inc > 0
    return np.where(lit, (1 - albedo(inc, r)) * r.S / np.asarray(sun_au, float) ** 2 * cos_inc * disc_fraction, 0.0)


def skin_depth(k: float, rho: float, c: float, period_s: float) -> float:
    return float(np.sqrt(k / (rho * c) * period_s / np.pi))


@dataclass
class Grid:
    """Nodes z[0] = 0 (surface) .. z[-1] (bottom) and the soil properties at each."""
    z: np.ndarray
    rho: np.ndarray
    kc: np.ndarray

    @classmethod
    def build(cls, r: Regolith = Regolith(), first_frac: float = 0.1, growth: float = 1.2,
              depth_m: float = 0.8, period_s: float = LUNATION_S) -> "Grid":
        """First layer `first_frac` of the surface diurnal skin depth, each layer
        `growth` times the previous, down to `depth_m` (~15 skin depths)."""
        dz = first_frac * skin_depth(r.k_s, r.rho_s, float(heat_capacity(250.0, r)), period_s)
        z = [0.0]
        while z[-1] < depth_m:
            z.append(z[-1] + dz)
            dz *= growth
        z = np.array(z)
        rho = r.rho_d - (r.rho_d - r.rho_s) * np.exp(-z / r.H)
        kc = r.k_d - (r.k_d - r.k_s) * np.exp(-z / r.H)        # = k_d - (k_d - k_s)(rho_d - rho)/(rho_d - rho_s)
        return cls(z, rho, kc)

    @property
    def h(self) -> np.ndarray:
        return np.diff(self.z)


class Column:
    """Temperatures of any number of independent soil columns (one per site)."""

    def __init__(self, n_sites: int, r: Regolith = Regolith(), grid: Grid | None = None, T0: float = 250.0):
        self.r = r
        self.g = grid or Grid.build(r)
        self.T = np.full((n_sites, len(self.g.z)), float(T0))

    def k(self, T: np.ndarray) -> np.ndarray:
        return self.g.kc * (1 + self.r.chi * (T / 350.0) ** 3)

    def stable_dt(self) -> float:
        """Largest explicit step with Fourier number <= 0.45 for the current temperatures."""
        g, T = self.g, self.T
        h = g.h
        rc = g.rho[1:-1] * heat_capacity(T[:, 1:-1], self.r)
        kk = self.k(T)[:, 1:-1]
        hm = np.minimum(h[:-1], h[1:])
        return float(0.45 * np.min(rc * hm * hm / kk))

    def _surface(self, F: np.ndarray) -> None:
        """Solve eps sigma T0^4 = F + k (T1 - T0) / h0 for T0 (Newton)."""
        r, g, T = self.r, self.g, self.T
        T1 = T[:, 1]
        T0 = T[:, 0].copy()
        h0 = g.h[0]
        for _ in range(30):
            k = 0.5 * (g.kc[0] * (1 + r.chi * (T0 / 350) ** 3) + g.kc[1] * (1 + r.chi * (T1 / 350) ** 3))
            dk = 0.5 * g.kc[0] * r.chi * 3 * T0 ** 2 / 350 ** 3
            f = r.emissivity * SIGMA * T0 ** 4 - F - k * (T1 - T0) / h0
            fp = 4 * r.emissivity * SIGMA * T0 ** 3 + k / h0 - dk * (T1 - T0) / h0
            step = f / fp
            T0 = np.maximum(T0 - step, 2.0)
            if np.max(np.abs(step)) < 1e-6:
                break
        T[:, 0] = T0

    def step(self, F: np.ndarray, dt: float) -> None:
        """Advance by dt seconds with absorbed surface flux F (W m^-2, one per site)."""
        g, T = self.g, self.T
        h = g.h
        k = self.k(T)
        ki = 0.5 * (k[:, :-1] + k[:, 1:])                          # at the interfaces
        flux = ki * np.diff(T, axis=1) / h                         # k dT/dz at the interfaces (W m^-2, > 0: heat flows up)
        rc = g.rho[1:-1] * heat_capacity(T[:, 1:-1], self.r)
        T[:, 1:-1] += dt * 2.0 * (flux[:, 1:] - flux[:, :-1]) / (rc * (h[:-1] + h[1:]))
        T[:, -1] = T[:, -2] + self.r.Q_geo * h[-1] / ki[:, -1]
        self._surface(F)

    def run(self, t_s: np.ndarray, F: np.ndarray, record: bool = True, depths_m: tuple[float, ...] = ()) -> dict:
        """Integrate over the sample times t_s (s, increasing) with the absorbed flux
        F[site, sample], linear in between. Returns surface (and optional depth)
        temperatures at the samples."""
        t_s = np.asarray(t_s, float)
        F = np.atleast_2d(np.asarray(F, float))
        n = len(t_s)
        out = np.empty((F.shape[0], n)) if record else None
        idx = [int(np.argmin(np.abs(self.g.z - d))) for d in depths_m]
        deep = {d: np.empty((F.shape[0], n)) for d in depths_m} if record else {}
        self._surface(F[:, 0])
        if record:
            out[:, 0] = self.T[:, 0]
            for d, i in zip(depths_m, idx):
                deep[d][:, 0] = self.T[:, i]
        for j in range(1, n):
            span = t_s[j] - t_s[j - 1]
            m = max(1, int(np.ceil(span / self.stable_dt())))
            dt = span / m
            for s in range(1, m + 1):
                w = s / m
                self.step(F[:, j - 1] * (1 - w) + F[:, j] * w, dt)
            if record:
                out[:, j] = self.T[:, 0]
                for d, i in zip(depths_m, idx):
                    deep[d][:, j] = self.T[:, i]
        return {"surface": out, "depth": deep, "depth_index": idx}

    def spin_up(self, t_s: np.ndarray, F: np.ndarray, cycles: int = 4, settle_depth_m: float = 0.1) -> list[float]:
        """Run the forcing window repeatedly. After each pass the layers below
        `settle_depth_m` (about two diurnal skin depths, where the daily wave has
        died out but the mean has had time to settle) are reset to the mean that
        layer had during the pass plus the geothermal gradient. That takes the slow
        deep soil to equilibrium in a few passes instead of years. Returns, for each
        pass after the first, the change of that mean temperature (K): the spin-up
        residual."""
        g = self.g
        i0 = int(np.searchsorted(g.z, settle_depth_m))
        changes, prev, hist = [], None, []
        for _ in range(cycles):
            res = self.run(t_s, F, record=True, depths_m=(float(g.z[i0]),))
            mean_deep = res["depth"][float(g.z[i0])].mean(axis=1)
            hist.append(mean_deep.copy())
            if len(hist) == 3:
                # the means approach equilibrium geometrically: Aitken's extrapolation to the limit
                d1, d2 = hist[1] - hist[0], hist[2] - hist[1]
                ratio = np.divide(d2, d1, out=np.zeros_like(d2), where=np.abs(d1) > 1e-9)
                ok = (ratio > 0) & (ratio < 0.95)
                jump = np.where(ok, d2 * ratio / (1 - np.where(ok, ratio, 0)), 0.0)
                mean_deep = hist[2] + np.clip(jump, -60.0, 60.0)
                hist = [mean_deep.copy()]
            below = g.z[i0:] - g.z[i0]
            k_deep = g.kc[i0:] * (1 + self.r.chi * (mean_deep[:, None] / 350) ** 3)
            self.T[:, i0:] = mean_deep[:, None] + self.r.Q_geo * below / k_deep
            if prev is not None:
                changes.append(float(np.max(np.abs(mean_deep - prev))))
            prev = mean_deep
        return changes
