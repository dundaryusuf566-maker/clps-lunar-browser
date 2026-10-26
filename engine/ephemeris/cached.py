"""Tabulated ephemeris with cubic Hermite interpolation.

One transfer design queries the ephemeris ~200 000 times (third-body forces and
the lunar pole at every integrator stage). Against SPICE that dominates the run
time. CachedEphemeris samples a base provider once on a uniform grid and then
answers each query with an O(1) cubic Hermite interpolation using both the
sampled positions and velocities.

Interpolation error (position) ~ h^4 / 384 * |d^4 r / dt^4|. For the Moon with
h = 1 h this is ~1e-5 km - far below the DE440 uncertainty itself. The default
step is 1 hour; `validate_against()` measures the real error against the base.

Tables can be saved as .npz and loaded on machines without SPICE, so the whole
team can design transfers with DE440 data.

Format v2 also tabulates the lunar body-fixed x axis (prime meridian), so the
full J2000 -> MOON_PA / IAU_MOON rotation is available for surface work. The
*_many methods evaluate whole time grids at once for the landing analysis.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np

from .base import EphemerisProvider

_FORMAT_VERSION = 2


class CachedEphemeris(EphemerisProvider):
    """Geocentric states of `bodies` (and spin poles of `pole_bodies`) on a grid.

    Any (target, observer) pair among EARTH and the cached bodies is supported:
    state(target, observer) = geo(target) - geo(observer).
    """

    def __init__(self, t0: float, step: float, states: dict[str, np.ndarray],
                 poles: dict[str, np.ndarray], source: str = "unknown",
                 xaxes: dict[str, np.ndarray] | None = None):
        self.t0, self.step = float(t0), float(step)
        xaxes = xaxes or {}
        n = {len(v) for v in states.values()} | {len(v) for v in poles.values()} | {len(v) for v in xaxes.values()}
        if len(n) != 1:
            raise ValueError("All tables must have the same number of samples")
        self.n = n.pop()
        if self.n < 2:
            raise ValueError("Need at least two samples")
        self.t1 = self.t0 + (self.n - 1) * self.step
        self._pos = {b.upper(): np.ascontiguousarray(s[:, :3]) for b, s in states.items()}
        self._vel = {b.upper(): np.ascontiguousarray(s[:, 3:6]) for b, s in states.items()}
        self._pole = {b.upper(): np.ascontiguousarray(p) for b, p in poles.items()}
        # Pole derivatives by central differences (poles move very slowly).
        self._pole_rate = {b: np.gradient(p, self.step, axis=0) for b, p in self._pole.items()}
        # Per-interval polynomial coefficients, flattened to plain Python tuples:
        # for 3-vectors, float arithmetic beats numpy's per-call overhead ~4x.
        self._coef = {b: self._flat(self._coefficients(self._pos[b], self._vel[b], self.step)) for b in self._pos}
        self._pole_coef = {b: self._flat(self._coefficients(self._pole[b], self._pole_rate[b], self.step))
                           for b in self._pole}
        # Body-fixed x axis (prime meridian direction) for bodies with a rotation model.
        self._xaxis = {b.upper(): np.ascontiguousarray(x) for b, x in xaxes.items()}
        missing = [b for b in self._xaxis if b not in self._pole]
        if missing:
            raise ValueError(f"Rotation tables need a pole table too: {missing}")
        self._xaxis_coef = {b: self._coefficients(x, np.gradient(x, self.step, axis=0), self.step)
                            for b, x in self._xaxis.items()}
        # numpy coefficient arrays for vectorised (*_many) evaluation
        self._coef_np = {b: self._coefficients(self._pos[b], self._vel[b], self.step) for b in self._pos}
        self._pole_coef_np = {b: self._coefficients(self._pole[b], self._pole_rate[b], self.step) for b in self._pole}
        self.source = source
        self.name = f"cached({source})"

    # --- construction ----------------------------------------------------------
    @classmethod
    def build(cls, base: EphemerisProvider, start: float, end: float, step: float = 3600.0,
              bodies: tuple[str, ...] = ("MOON", "SUN"),
              pole_bodies: tuple[str, ...] = ("MOON", "EARTH"),
              rotation_bodies: tuple[str, ...] = ("MOON",)) -> "CachedEphemeris":
        """Sample `base` from start to end (TDB s); the grid is extended to cover end.
        Rotation tables are added for `rotation_bodies` the base can rotate."""
        if end <= start:
            raise ValueError("end must be after start")
        n = int(np.ceil((end - start) / step)) + 1
        ts = start + step * np.arange(n)
        states = {b: np.array([base.state(b, "EARTH", t) for t in ts]) for b in bodies}
        poles, xaxes = {}, {}
        for b in pole_bodies:
            if b in rotation_bodies and base.body_fixed_rotation(b, ts[0]) is not None:
                mats = np.array([base.body_fixed_rotation(b, t) for t in ts])
                xaxes[b], poles[b] = mats[:, 0, :], mats[:, 2, :]
            else:
                poles[b] = np.array([base.pole(b, t) for t in ts])
        return cls(start, step, states, poles, source=base.name, xaxes=xaxes)

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        arrays = {f"state_{b}": np.hstack([self._pos[b], self._vel[b]]) for b in self._pos}
        arrays.update({f"pole_{b}": p for b, p in self._pole.items()})
        arrays.update({f"xaxis_{b}": x for b, x in self._xaxis.items()})
        np.savez_compressed(path, t0=self.t0, step=self.step, source=self.source,
                            version=_FORMAT_VERSION, **arrays)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "CachedEphemeris":
        with np.load(Path(path), allow_pickle=False) as z:
            version = int(z["version"])
            if version not in (1, _FORMAT_VERSION):
                raise ValueError(f"Unsupported cache format version {version}")
            states = {k[6:]: z[k] for k in z.files if k.startswith("state_")}
            poles = {k[5:]: z[k] for k in z.files if k.startswith("pole_")}
            xaxes = {k[6:]: z[k] for k in z.files if k.startswith("xaxis_")}  # v1 files have none
            return cls(float(z["t0"]), float(z["step"]), states, poles, source=str(z["source"]), xaxes=xaxes)

    @property
    def has_rotation(self) -> bool:
        return "MOON" in self._xaxis

    # --- interpolation ---------------------------------------------------------
    def covers(self, start: float, end: float) -> bool:
        return self.t0 <= start and end <= self.t1

    def _locate(self, t: float) -> tuple[int, float]:
        if not self.t0 <= t <= self.t1:
            from ..core.time import tdb_to_utc
            raise ValueError(
                f"Epoch {tdb_to_utc(t):%Y-%m-%d %H:%M} UTC is outside the ephemeris cache "
                f"({tdb_to_utc(self.t0):%Y-%m-%d} .. {tdb_to_utc(self.t1):%Y-%m-%d}, source {self.source}); "
                "rebuild the cache with a wider window"
            )
        x = (t - self.t0) / self.step
        i = min(int(x), self.n - 2)
        return i, x - i

    @staticmethod
    def _coefficients(p: np.ndarray, v: np.ndarray, h: float) -> np.ndarray:
        """Cubic Hermite as a0 + a1 s + a2 s^2 + a3 s^3 per interval, s in [0, 1]:
        shape (n-1, 4, 3)."""
        p0, p1, m0, m1 = p[:-1], p[1:], v[:-1] * h, v[1:] * h
        return np.stack([p0, m0, -3 * p0 - 2 * m0 + 3 * p1 - m1, 2 * p0 + m0 - 2 * p1 + m1], axis=1)

    @staticmethod
    def _flat(coef: np.ndarray) -> list[tuple[float, ...]]:
        """(n-1, 4, 3) -> list of 12-tuples (a0x a0y a0z a1x ... a3z)."""
        return [tuple(row) for row in coef.reshape(len(coef), 12).tolist()]

    def _eval(self, coef: list, t: float, with_rate: bool):
        i, s = self._locate(t)
        a0x, a0y, a0z, a1x, a1y, a1z, a2x, a2y, a2z, a3x, a3y, a3z = coef[i]
        pos = np.array((
            a0x + s * (a1x + s * (a2x + s * a3x)),
            a0y + s * (a1y + s * (a2y + s * a3y)),
            a0z + s * (a1z + s * (a2z + s * a3z)),
        ))
        if not with_rate:
            return pos, None
        h = self.step
        rate = np.array((
            (a1x + s * (2 * a2x + 3 * s * a3x)) / h,
            (a1y + s * (2 * a2y + 3 * s * a3y)) / h,
            (a1z + s * (2 * a2z + 3 * s * a3z)) / h,
        ))
        return pos, rate

    def _geo(self, body: str, t: float, with_velocity: bool):
        body = body.upper()
        if body == "EARTH":
            return np.zeros(3), (np.zeros(3) if with_velocity else None)
        coef = self._coef.get(body)
        if coef is None:
            raise KeyError(f"'{body}' is not in the ephemeris cache (has: {sorted(self._pos)})")
        return self._eval(coef, t, with_velocity)

    # --- interface ---------------------------------------------------------------
    def state(self, target: str, observer: str, epoch: float) -> np.ndarray:
        target, observer = target.upper(), observer.upper()
        if target == observer:
            return np.zeros(6)
        rt, vt = self._geo(target, epoch, True)
        if observer == "EARTH":
            return np.concatenate([rt, vt])
        ro, vo = self._geo(observer, epoch, True)
        return np.concatenate([rt - ro, vt - vo])

    def position(self, target: str, observer: str, epoch: float) -> np.ndarray:
        target, observer = target.upper(), observer.upper()
        if target == observer:
            return np.zeros(3)
        if observer == "EARTH":  # the common case: skip the zero subtraction
            return self._geo(target, epoch, False)[0]
        return self._geo(target, epoch, False)[0] - self._geo(observer, epoch, False)[0]

    def pole(self, body: str, epoch: float) -> np.ndarray:
        body = body.upper()
        coef = self._pole_coef.get(body)
        if coef is None:
            raise KeyError(f"No cached pole for '{body}' (has: {sorted(self._pole)})")
        i, s = self._locate(epoch)
        a0x, a0y, a0z, a1x, a1y, a1z, a2x, a2y, a2z, a3x, a3y, a3z = coef[i]
        x = a0x + s * (a1x + s * (a2x + s * a3x))
        y = a0y + s * (a1y + s * (a2y + s * a3y))
        z = a0z + s * (a1z + s * (a2z + s * a3z))
        n = math.sqrt(x * x + y * y + z * z)
        return np.array((x / n, y / n, z / n))

    def body_fixed_rotation(self, body: str, epoch: float) -> np.ndarray | None:
        body = body.upper()
        coef = self._xaxis_coef.get(body)
        if coef is None:
            return None
        i, s = self._locate(epoch)
        c = coef[i]
        x = c[0] + s * (c[1] + s * (c[2] + s * c[3]))
        z = self.pole(body, epoch)
        x = x - np.dot(x, z) * z
        x /= np.linalg.norm(x)
        return np.vstack([x, np.cross(z, x), z])

    # --- vectorised evaluation (whole time grids) -------------------------------
    def _locate_many(self, ts: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        ts = np.asarray(ts, dtype=float)
        if ts.size and (ts.min() < self.t0 or ts.max() > self.t1):
            self._locate(float(ts.min()) if ts.min() < self.t0 else float(ts.max()))  # raises with dates
        x = (ts - self.t0) / self.step
        i = np.minimum(x.astype(int), self.n - 2)
        return i, (x - i)[:, None]

    @staticmethod
    def _eval_many(coef: np.ndarray, i: np.ndarray, s: np.ndarray) -> np.ndarray:
        c = coef[i]  # (N, 4, 3)
        return c[:, 0] + s * (c[:, 1] + s * (c[:, 2] + s * c[:, 3]))

    def position_many(self, target: str, observer: str, ts) -> np.ndarray:
        """(N, 3) positions of target relative to observer at epochs ts."""
        i, s = self._locate_many(ts)

        def geo(b):
            b = b.upper()
            if b == "EARTH":
                return np.zeros((len(i), 3))
            if b not in self._coef_np:
                raise KeyError(f"'{b}' is not in the ephemeris cache (has: {sorted(self._pos)})")
            return self._eval_many(self._coef_np[b], i, s)
        return geo(target) - geo(observer)

    def pole_many(self, body: str, ts) -> np.ndarray:
        i, s = self._locate_many(ts)
        p = self._eval_many(self._pole_coef_np[body.upper()], i, s)
        return p / np.linalg.norm(p, axis=1, keepdims=True)

    def rotation_many(self, body: str, ts) -> np.ndarray:
        """(N, 3, 3) J2000 -> body-fixed rotations."""
        body = body.upper()
        if body not in self._xaxis_coef:
            raise KeyError(f"No rotation table for '{body}' in this cache (rebuild it with a v2 cache)")
        i, s = self._locate_many(ts)
        z = self.pole_many(body, ts)
        x = self._eval_many(self._xaxis_coef[body], i, s)
        x = x - np.sum(x * z, axis=1, keepdims=True) * z
        x /= np.linalg.norm(x, axis=1, keepdims=True)
        return np.stack([x, np.cross(z, x), z], axis=1)

    # --- diagnostics -------------------------------------------------------------
    def validate_against(self, base: EphemerisProvider, n_samples: int = 500, seed: int = 0) -> dict:
        """Max interpolation error vs the base provider at random epochs."""
        rng = np.random.default_rng(seed)
        ts = rng.uniform(self.t0, self.t1, n_samples)
        out = {}
        for b in self._pos:
            dr = [np.linalg.norm(self.state(b, "EARTH", t)[:3] - base.state(b, "EARTH", t)[:3]) for t in ts]
            dv = [np.linalg.norm(self.state(b, "EARTH", t)[3:] - base.state(b, "EARTH", t)[3:]) for t in ts]
            out[b] = {"max_pos_err_km": float(np.max(dr)), "max_vel_err_km_s": float(np.max(dv))}
        for b in self._pole:
            da = [np.arccos(np.clip(np.dot(self.pole(b, t), base.pole(b, t)), -1, 1)) for t in ts]
            out[f"{b}_pole"] = {"max_angle_err_deg": float(np.degrees(np.max(da)))}
        for b in self._xaxis:
            dm = []
            for t in ts:
                rb = base.body_fixed_rotation(b, t)
                if rb is None:
                    break
                dm.append(np.arccos(np.clip(np.dot(self.body_fixed_rotation(b, t)[0], rb[0]), -1, 1)))
            if dm:
                out[f"{b}_meridian"] = {"max_angle_err_deg": float(np.degrees(np.max(dm)))}
        return out
