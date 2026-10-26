"""A whole mission on one clock, for the 3D journey view.

    parking orbit -> TLI -> coast (the engine's propagated transfer) -> LOI ->
    wait in lunar orbit -> plane change -> descent -> touchdown

What comes from where:

* Parking orbit and coast: the transfer as the engine solved it (TransferDesigner
  re-propagated from the stored controls), the same paths as the transfer view.
* Lunar orbit: the model the landing analysis uses (circular orbit at the
  capture altitude, plane drifting with the J2 node regression around the lunar
  pole). The analysis does not model where the spacecraft is along its orbit
  (phasing), so the drawing spreads the phase adjustment that brings it over the
  site at the landing time across the wait, and reports how large it is.
* Plane change: the analysis counts one impulsive burn; the drawing turns the
  plane over the last revolution before the descent.
* Descent: schematic. A deorbit half-ellipse from the orbit to a 15 km perilune
  (the analysis's descent model) and a braking arc to the site; its timing and
  ground track are illustrative, its delta-v is the analysis's.

Everything is sampled in J2000, Earth-centred, with the Moon's position at each
sample so the browser can draw Moon-centred paths too.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..core.constants import BODIES
from ..core.time import tdb_to_utc
from ..ephemeris.cached import CachedEphemeris
from ..propagators import propagate
from ..surface.ground import DSN, dsn_mask, j2000_to_earth_fixed, station_ecef_km
from ..surface.landing import ArrivalState, LandingConstraints, node_rate_rad_s, plane_change_ms
from ..surface.sites import MOON_MEAN_RADIUS_KM, LandingSite
from .transfer import TransferDesigner

EARTH, MOON = BODIES["EARTH"], BODIES["MOON"]
DAY = 86_400.0


@dataclass(frozen=True)
class DescentSketch:
    """Illustrative descent: deorbit half-ellipse, then a braking arc to the site."""
    braking_arc_deg: float = 15.0      # ground covered by the braking burn (~450 km)
    braking_min: float = 12.0          # its duration
    samples: int = 160


DESCENT = DescentSketch()


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def _rodrigues(v: np.ndarray, k: np.ndarray, theta) -> np.ndarray:
    """Rotate vector v about unit axis k by angle(s) theta -> (N, 3)."""
    th = np.atleast_1d(theta)[:, None]
    return v * np.cos(th) + np.cross(k, v) * np.sin(th) + k * np.dot(k, v) * (1 - np.cos(th))


def quat_from_matrix(m: np.ndarray) -> np.ndarray:
    """(N, 3, 3) rotation matrices -> (N, 4) quaternions (x, y, z, w), sign-continuous."""
    m = np.atleast_3d(m) if m.ndim == 3 else m[None]
    q = np.empty((len(m), 4))
    for i, r in enumerate(m):
        tr = np.trace(r)
        if tr > 0:
            s = 2 * np.sqrt(tr + 1)
            q[i] = [(r[2, 1] - r[1, 2]) / s, (r[0, 2] - r[2, 0]) / s, (r[1, 0] - r[0, 1]) / s, s / 4]
        else:
            k = int(np.argmax(np.diag(r)))
            a, b = (k + 1) % 3, (k + 2) % 3
            s = 2 * np.sqrt(1 + r[k, k] - r[a, a] - r[b, b])
            v = np.zeros(3)
            v[k] = s / 4
            v[a] = (r[a, k] + r[k, a]) / s
            v[b] = (r[b, k] + r[k, b]) / s
            q[i] = [*v, (r[b, a] - r[a, b]) / s]
        if i and np.dot(q[i], q[i - 1]) < 0:
            q[i] = -q[i]
    return q


def lunar_orbit(arr: ArrivalState, peri_r: np.ndarray, pole: np.ndarray, ts: np.ndarray,
                phase_shift_rad: float = 0.0, t_end: float | None = None) -> np.ndarray:
    """Moon-centred J2000 positions on the analysis's lunar orbit: circular at the
    capture altitude, plane drifting with the J2 node rate. `phase_shift_rad` is
    added linearly between LOI and `t_end`."""
    r = MOON.radius + arr.orbit_alt_km
    n = np.sqrt(MOON.gm / r**3)
    h0 = _unit(arr.h_hat)
    k = _unit(pole)
    e1 = _unit(peri_r - np.dot(peri_r, h0) * h0)
    e2 = np.cross(h0, e1)
    dt = np.asarray(ts, float) - arr.arrival_epoch
    theta = node_rate_rad_s(arr.orbit_alt_km, arr.inc_deg) * dt
    b1, b2 = _rodrigues(e1, k, theta), _rodrigues(e2, k, theta)
    span = (t_end - arr.arrival_epoch) if t_end else 1.0
    u = n * dt + phase_shift_rad * np.clip(dt / span, 0, 1)
    return r * (np.cos(u)[:, None] * b1 + np.sin(u)[:, None] * b2)


def build_journey(cache: CachedEphemeris, designer: TransferDesigner, controls: dict, arr: ArrivalState,
                  site: LandingSite, site_height_m: float, landing_epoch: float, c: LandingConstraints,
                  descent: DescentSketch = DESCENT, orbit_step_s: float = 120.0) -> dict:
    """Sampled journey (see module docstring). Times are TDB seconds past J2000."""
    t_tli = designer.spec.tli_epoch

    # parking orbit (one revolution before TLI, circular) and the coast
    before, _ = designer.tli_state(controls)
    rp = np.linalg.norm(before.r)
    p_park = 2 * np.pi * np.sqrt(rp**3 / EARTH.gm)
    hp = _unit(np.cross(before.r, before.v))
    ang = np.linspace(-2 * np.pi, 0, 73)
    park = _rodrigues(before.r, hp, ang)
    t_park = t_tli + ang / (2 * np.pi) * p_park

    ev = designer.simulate_stage_b(controls)
    earth_seg, moon_seg = ev.segments["earth"], ev.segments["moon"]
    dur_e = earth_seg.epochs[-1] - earth_seg.epochs[0]
    dense_e = propagate(designer.earth_dyn, earth_seg.initial, dur_e, rtol=1e-12, atol=1e-9)
    t_e = earth_seg.epochs[0] + dur_e * np.linspace(0, 1, 260) ** 2
    y_e = np.array([dense_e.state_at(t).r for t in t_e])
    dur_m = moon_seg.epochs[-1] - moon_seg.epochs[0]
    dense_m = propagate(designer.moon_dyn, moon_seg.initial, dur_m, rtol=1e-12, atol=1e-9)
    t_m = moon_seg.epochs[0] + dur_m * (1 - (1 - np.linspace(0, 1, 140)) ** 2)
    y_m = np.array([dense_m.state_at(t).r for t in t_m])            # Moon-centred
    peri = ev.final
    t_loi = float(peri.epoch)

    # landing geometry: the site at touchdown, the plane that contains it
    rot_land = cache.rotation_many("MOON", np.array([landing_epoch]))[0]      # J2000 -> fixed
    up_land = rot_land.T @ site.unit_fixed()
    r_site = MOON_MEAN_RADIUS_KM + site_height_m / 1000.0      # LOLA heights are above 1737.4 km
    a_sk = descent.braking_arc_deg
    r1, r2 = MOON.radius + arr.orbit_alt_km, MOON.radius + c.descent_perilune_alt_km
    a_e = 0.5 * (r1 + r2)
    t_half = np.pi * np.sqrt(a_e**3 / MOON.gm)
    t_brake = descent.braking_min * 60.0
    t_pc = landing_epoch - t_half - t_brake                    # descent starts here
    pole = cache.pole("MOON", t_loi)
    period = 2 * np.pi * np.sqrt(r1**3 / MOON.gm)
    t_blend = max(t_loi, t_pc - period)                        # plane turned over the last revolution

    if t_pc <= t_loi + c.min_coast_days * DAY * 0.5:
        raise ValueError("touchdown is too close to the lunar orbit insertion for this sketch")
    h_pc = _rodrigues(_unit(arr.h_hat), _unit(pole),
                      node_rate_rad_s(arr.orbit_alt_km, arr.inc_deg) * (t_pc - arr.arrival_epoch))[0]
    h_new = _unit(h_pc - np.dot(h_pc, up_land) * up_land)
    turn_deg = float(np.degrees(np.arccos(np.clip(np.dot(h_pc, h_new), -1, 1))))
    axis = np.cross(h_pc, h_new)
    axis = _unit(axis) if np.linalg.norm(axis) > 1e-12 else np.array([1.0, 0.0, 0.0])

    # descent start point in the new plane: half a deorbit ellipse + the braking arc before the site
    f1, f2 = up_land, np.cross(h_new, up_land)
    a0 = -(np.pi + np.radians(a_sk))
    start_dir = np.cos(a0) * f1 + np.sin(a0) * f2
    # where the spacecraft would be at t_pc without a phase adjustment, turned into the new plane
    q_turn = np.radians(turn_deg)
    p0 = lunar_orbit(arr, peri.r, pole, np.array([t_pc]))[0]
    p0 = _rodrigues(p0, axis, q_turn)[0]
    d_phase = np.arctan2(np.dot(np.cross(_unit(p0), start_dir), h_new), np.dot(_unit(p0), start_dir))
    n_orb = np.sqrt(MOON.gm / r1**3)
    phase_pct = 100 * abs(d_phase) / (n_orb * max(t_pc - t_loi, 1.0))

    # sample the wait in orbit
    t_o = np.arange(t_loi, t_pc, orbit_step_s)
    if len(t_o) == 0 or t_o[-1] < t_pc:
        t_o = np.append(t_o, t_pc)
    y_o = lunar_orbit(arr, peri.r, pole, t_o, d_phase, t_pc)
    blend = np.clip((t_o - t_blend) / max(t_pc - t_blend, 1.0), 0, 1)
    blend = blend * blend * (3 - 2 * blend)                    # smoothstep
    for i in np.flatnonzero(blend > 0):
        y_o[i] = _rodrigues(y_o[i], axis, q_turn * blend[i])[0]

    # schematic descent: Kepler half-ellipse from r1 to r2, then the braking arc
    e = (r1 - r2) / (r1 + r2)
    tau = np.linspace(0, t_half, descent.samples // 2)
    M = np.pi + np.sqrt(MOON.gm / a_e**3) * tau
    E = M.copy()
    for _ in range(30):
        E = E - (E - e * np.sin(E) - M) / (1 - e * np.cos(E))
    nu = 2 * np.arctan2(np.sqrt(1 + e) * np.sin(E / 2), np.sqrt(1 - e) * np.cos(E / 2))
    nu = np.unwrap(np.where(nu < 0, nu + 2 * np.pi, nu))
    rr = a_e * (1 - e * np.cos(E))
    aa = a0 + (nu - nu[0])
    s = np.linspace(0, 1, descent.samples - len(tau) + 1)[1:]
    ab = -np.radians(a_sk) * (1 - s) ** 2
    rb = r_site + (r2 - r_site) * (1 - s) ** 1.6
    ang_d = np.concatenate([aa, ab])
    r_d = np.concatenate([rr, rb])
    t_d = np.concatenate([t_pc + tau, t_pc + t_half + s * t_brake])
    y_d = r_d[:, None] * (np.cos(ang_d)[:, None] * f1 + np.sin(ang_d)[:, None] * f2)

    # one timeline, Earth-centred J2000
    t_all = np.concatenate([t_park, t_e[1:], t_m[1:], t_o[1:], t_d[1:]])
    moon_at = cache.position_many("MOON", "EARTH", t_all)
    n1, n2, n3 = len(t_park), len(t_e) - 1, len(t_m) - 1
    mci = np.vstack([park - moon_at[:n1], y_e[1:] - moon_at[n1:n1 + n2], y_m[1:], y_o[1:], y_d[1:]])
    eci = mci + moon_at
    phase = np.concatenate([np.zeros(n1, int), np.ones(n2 + n3, int), np.full(len(t_o) - 1, 2, int),
                            np.full(len(t_d) - 1, 3, int)])
    dsn = dsn_mask(t_all, eci)

    # hourly context: Moon, its orientation, Earth's orientation, the Sun
    th = np.arange(np.floor(t_park[0] / 3600) * 3600, landing_epoch + 2 * DAY, 3600.0)
    moon_h = cache.position_many("MOON", "EARTH", th)
    q_moon = quat_from_matrix(np.transpose(cache.rotation_many("MOON", th), (0, 2, 1)))    # fixed -> J2000
    q_earth = quat_from_matrix(np.transpose(j2000_to_earth_fixed(th), (0, 2, 1)))
    sun_h = _unit(cache.position_many("SUN", "EARTH", th))

    soi = float(earth_seg.epochs[-1])
    events = [
        ("parking", "Parking orbit", float(t_park[0])),
        ("tli", "Trans-lunar injection", float(t_tli)),
        ("soi", "Enters the Moon's sphere of influence", soi),
        ("loi", "Lunar orbit insertion", t_loi),
        ("checkout", f"Checkout done ({c.min_coast_days:g} d)", t_loi + c.min_coast_days * DAY),
        ("plane", "Plane change (drawn over the last orbit)", float(t_blend)),
        ("deorbit", "Deorbit: descent begins (schematic)", float(t_pc)),
        ("braking", "Braking burn (schematic)", float(t_pc + t_half)),
        ("touchdown", "Touchdown", float(landing_epoch)),
    ]
    return {
        "t0_utc": tdb_to_utc(t_tli).isoformat(timespec="seconds"),
        "tli_epoch": float(t_tli),
        "t": np.round(t_all - t_tli, 1).tolist(),
        "eci": np.round(eci, 2).tolist(),
        "mci": np.round(mci, 3).tolist(),
        "phase": phase.tolist(),
        "phase_names": ["parking orbit", "coast", "lunar orbit", "descent (schematic)"],
        "dsn": dsn.astype(int).tolist(),
        "events": [{"id": i, "label": lab, "t": round(t - t_tli, 1),
                    "utc": tdb_to_utc(t).isoformat(timespec="minutes")} for i, lab, t in events],
        "hourly": {
            "t0": round(float(th[0] - t_tli), 1), "step": 3600.0, "n": len(th),
            "moon": np.round(moon_h, 1).tolist(), "q_moon": np.round(q_moon, 9).tolist(),
            "q_earth": np.round(q_earth, 9).tolist(), "sun": np.round(sun_h, 6).tolist(),
        },
        "site": {"lat": site.lat_deg, "lon": site.lon_deg, "name": site.name, "height_m": round(site_height_m, 1),
                 "fixed": np.round(site.unit_fixed(), 9).tolist()},
        "orbit": {"alt_km": round(arr.orbit_alt_km, 2), "inc_deg": round(arr.inc_deg, 2),
                  "period_min": round(period / 60, 1),
                  "node_drift_deg_per_day": round(float(np.degrees(node_rate_rad_s(arr.orbit_alt_km, arr.inc_deg)) * DAY), 3),
                  "phase_adjust_deg": round(float(np.degrees(d_phase)), 2),
                  "phase_adjust_pct_of_motion": round(float(phase_pct), 3),
                  "plane_turn_deg": round(turn_deg, 3),
                  "plane_turn_ms": round(float(plane_change_ms(turn_deg, arr.orbit_alt_km)), 1)},
        "descent": {"perilune_km": c.descent_perilune_alt_km, "half_ellipse_min": round(t_half / 60, 1),
                    "braking_min": descent.braking_min, "braking_arc_deg": a_sk, "schematic": True},
        "stations": [{"name": s.name, "ecef": np.round(station_ecef_km(s)[0], 3).tolist(), "bit": s.bit} for s in DSN],
        "radii": {"earth": EARTH.radius, "moon": MOON_MEAN_RADIUS_KM},
    }
