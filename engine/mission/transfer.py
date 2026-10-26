"""TLI -> LOI transfer designer.

Given a TLI epoch and a time of flight, find the parking-orbit geometry and TLI
burn that deliver the spacecraft to a lunar periselene of given altitude and
inclination, then compute the LOI burn into the capture orbit.

Simulation (two segments, patched at the lunar sphere of influence):
    1. Earth-centred: parking orbit + tangential TLI -> SOI entry
    2. Moon-centred:  SOI entry -> periselene (or impact)

Targeting (two stages):
    A. B-plane stage: residuals on the osculating hyperbola at SOI entry
       (B·T and B·R errors w.r.t. the B vector that gives the target periselene
       and inclination for the chosen family, plus estimated periselene time).
       Smooth and robust even far from the solution, including would-be impact
       cases, and the B·T/B·R pair keeps the two solution families apart.
    B. Refinement: residuals on the actually propagated periselene
       (altitude, inclination, time) starting from stage A's solution.

Controls: parking-orbit RAAN and inclination (>= launch-site latitude, i.e.
the launch azimuth), argument of latitude at TLI, TLI delta-v, and an optional
out-of-plane TLI component.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from ..core.constants import BODIES
from ..core.frames import frame_from_pole, moon_sun_frame
from ..core.state import State
from ..core.time import tdb_to_utc
from ..dynamics import earth_moon_model
from ..ephemeris import change_center
from ..ephemeris.base import EphemerisProvider
from ..orbits.bplane import (
    bplane_angle_for_inclination, bplane_from_state, hyperbolic_time_to_periapsis,
    impact_parameter_for_periapsis,
)
from ..orbits.elements import Elements, cartesian_to_elements, elements_to_cartesian
from ..propagators import ClosestApproach, DistanceToBody, Impact, Periapsis, propagate
from ..targeting import Control, ControlVector, DataResidual, Evaluation, TargetingProblem, solve
from ..targeting.solvers import SolverResult
from .guess import conic_tli_guess

EARTH, MOON = BODIES["EARTH"], BODIES["MOON"]
DAY = 86_400.0

# Canonical column order of a solution-database row (see TransferSolution.to_row).
CONTROL_KEYS = ("raan", "parking_inc", "arg_lat", "tli_dv", "tli_dv_n")
METRIC_KEYS = (
    "tli_dv_ms", "tli_dv_out_of_plane_ms", "c3_km2s2", "v_inf_kms", "loi_dv_ms", "total_dv_ms",
    "tof_days", "periselene_alt_km", "lunar_inc_deg", "raan_moon_sun_deg", "periselene_lat_deg",
    "periselene_lon_deg", "arrival_epoch", "parking_raan_deg", "parking_inc_deg", "impact",
    "cap_hx", "cap_hy", "cap_hz",
)


@dataclass
class TransferSpec:
    tli_epoch: float                 # TDB seconds past J2000
    tof_days: float                  # TLI -> periselene
    parking_alt_km: float = 185.0
    parking_inc_deg: float = 28.5    # minimum inclination (launch-site latitude)
    parking_inc_free: bool = True    # let the launch azimuth raise the inclination
    parking_inc_max_deg: float = 60.0
    periselene_alt_km: float = 100.0
    lunar_inc_deg: float = 90.0      # w.r.t. lunar equator
    apolune_alt_km: float | None = None  # None -> circular capture orbit
    family: int = +1                 # B-plane solution family (+1 / -1)
    plane_branch: int = 0            # which parking plane contains the aim point
    allow_plane_change: bool = False  # out-of-plane TLI component as an extra control
    fidelity: str = "medium"         # force model fidelity ("low" | "medium" | "high")
    soi_km: float = 66_100.0


@dataclass
class TransferSolution:
    spec: TransferSpec
    converged: bool
    controls: dict[str, float]
    metrics: dict[str, float]
    stage_a: SolverResult
    stage_b: SolverResult | None
    segments: dict = field(default_factory=dict, repr=False)

    def to_row(self) -> dict:
        """Flat record for the solution database (column order: row_fields())."""
        row = {f"spec_{k}": v for k, v in asdict(self.spec).items()}
        row["converged"] = self.converged
        row.update({k: self.controls.get(k) for k in CONTROL_KEYS})
        row.update({k: self.metrics.get(k) for k in METRIC_KEYS})
        row["tli_utc"] = tdb_to_utc(self.spec.tli_epoch).isoformat(timespec="seconds")
        return row

    def summary(self) -> str:
        m = self.metrics
        return (
            f"TLI {tdb_to_utc(self.spec.tli_epoch):%Y-%m-%d %H:%M} UTC  tof {m['tof_days']:.3f} d  "
            f"{'CONVERGED' if self.converged else 'NOT CONVERGED'}\n"
            f"  TLI dv {m['tli_dv_ms']:8.1f} m/s   C3 {m['c3_km2s2']:7.3f} km²/s²   v_inf@Moon {m['v_inf_kms']:.3f} km/s\n"
            f"  LOI dv {m['loi_dv_ms']:8.1f} m/s   periselene {m['periselene_alt_km']:.2f} km   "
            f"inc {m['lunar_inc_deg']:.3f}°   RAAN(Moon-Sun) {m['raan_moon_sun_deg']:.1f}°\n"
            f"  periselene latitude {m['periselene_lat_deg']:.2f}°   solver evals A/B: "
            f"{self.stage_a.evaluations}/{self.stage_b.evaluations if self.stage_b else 0}"
        )


class TransferDesigner:
    def __init__(self, ephemeris: EphemerisProvider, spec: TransferSpec):
        self.eph, self.spec = ephemeris, spec
        self.earth_dyn = earth_moon_model("EARTH", ephemeris, spec.fidelity)
        self.moon_dyn = earth_moon_model("MOON", ephemeris, spec.fidelity)
        self.rp_target = MOON.radius + spec.periselene_alt_km
        self.inc_target = np.radians(spec.lunar_inc_deg)
        self.tof = spec.tof_days * DAY
        self.arrival_epoch = spec.tli_epoch + self.tof

    # --- simulation ------------------------------------------------------------
    def tli_state(self, c: dict) -> tuple[State, State]:
        """Parking-orbit state at TLI epoch and the post-burn state."""
        r_p = EARTH.radius + self.spec.parking_alt_km
        inc = c.get("parking_inc", np.radians(self.spec.parking_inc_deg))
        el = Elements(r_p, 0.0, inc, c["raan"], 0.0, c["arg_lat"])
        before = State(self.spec.tli_epoch, elements_to_cartesian(el, EARTH.gm), "EARTH")
        v_hat = before.v / np.linalg.norm(before.v)
        h_hat = np.cross(before.r, before.v)
        h_hat /= np.linalg.norm(h_hat)
        return before, before.with_delta_v(c["tli_dv"] * v_hat + c.get("tli_dv_n", 0.0) * h_hat)

    def _segment_earth(self, after: State, rtol: float):
        events = [DistanceToBody("MOON", self.spec.soi_km), ClosestApproach("MOON", max_distance_km=4 * self.spec.soi_km)]
        traj = propagate(self.earth_dyn, after, self.tof + 3 * DAY, events=events, rtol=rtol, atol=1e-8, dense=False)
        return traj, change_center(traj.final, "MOON", self.eph)

    def simulate_stage_a(self, c: dict) -> Evaluation:
        _, after = self.tli_state(c)
        traj, entry = self._segment_earth(after, rtol=1e-10)
        try:
            pole = self.eph.pole("MOON", entry.epoch)
            bp = bplane_from_state(entry.r, entry.v, MOON.gm, pole)
            t_peri = entry.epoch + hyperbolic_time_to_periapsis(entry.r, entry.v, MOON.gm)
        except ValueError:
            return Evaluation(final=entry, data={"bt_err": np.nan, "br_err": np.nan, "t_peri": np.nan})
        # Desired B vector for the *current* asymptote: |B| from the target
        # periselene, angle from the target inclination and chosen family.
        b_star = impact_parameter_for_periapsis(self.rp_target, bp.v_inf, MOON.gm)
        theta = bplane_angle_for_inclination(self.inc_target, bp.s_hat, pole, self.spec.family)
        return Evaluation(final=entry, segments={"earth": traj},
                          data={"bt_err": bp.b_dot_t - b_star * np.cos(theta),
                                "br_err": bp.b_dot_r - b_star * np.sin(theta),
                                "t_peri": t_peri - self.spec.tli_epoch,
                                "rp_osc": bp.rp, "inc_osc": bp.inclination, "b_km": bp.b, "v_inf": bp.v_inf})

    def simulate_stage_b(self, c: dict) -> Evaluation:
        _, after = self.tli_state(c)
        traj_e, entry = self._segment_earth(after, rtol=1e-12)
        traj_m = propagate(self.moon_dyn, entry, 3 * DAY, events=[Periapsis(terminal=True), Impact()],
                           rtol=1e-12, atol=1e-9, dense=False)
        peri = traj_m.final
        el = cartesian_to_elements(peri.r, peri.v, MOON.gm, frame_from_pole(self.eph.pole("MOON", peri.epoch), [1.0, 0, 0]))
        return Evaluation(final=peri, segments={"earth": traj_e, "moon": traj_m},
                          data={"periselene_alt": el.periapsis_radius() - MOON.radius, "inc": el.inc,
                                "t_peri": peri.epoch - self.spec.tli_epoch,
                                "impact": traj_m.terminated_by == "impact"})

    # --- targeting -------------------------------------------------------------
    def _controls(self, raan, inc, arg_lat, dv, dv_n=0.0) -> ControlVector:
        # Out-of-plane TLI component: only needed when the Moon's declination is
        # at or beyond the parking inclination (e.g. the 2024-2026 major lunar
        # standstill with a 28.5 deg parking orbit). Its scale makes it "expensive"
        # for the min-norm Newton step, so RAAN / timing are preferred.
        return ControlVector([
            Control("raan", raan, scale=0.01, fd_step=1e-5, unit="rad"),
            # Inclination is "expensive" (small scale) so the min-norm step only
            # moves it when RAAN / timing cannot do the job.
            Control("parking_inc", inc, scale=0.001, fd_step=1e-4, unit="rad",
                    lower=np.radians(self.spec.parking_inc_deg), upper=np.radians(self.spec.parking_inc_max_deg),
                    fixed=not self.spec.parking_inc_free),
            Control("arg_lat", arg_lat, scale=0.01, fd_step=1e-5, unit="rad"),
            Control("tli_dv", dv, scale=0.001, fd_step=1e-4, lower=2.5, upper=3.6, unit="km/s"),
            Control("tli_dv_n", dv_n, scale=0.001, fd_step=1e-4, lower=-0.3, upper=0.3,
                    fixed=not self.spec.allow_plane_change, unit="km/s"),
        ])

    def solve(self, verbose: bool = False) -> TransferSolution:
        s = self.spec
        g = conic_tli_guess(self.eph, s.tli_epoch, self.tof, s.parking_alt_km, np.radians(s.parking_inc_deg),
                            self.rp_target, self.inc_target, s.family, s.plane_branch,
                            inc_free=s.parking_inc_free, inc_max=np.radians(s.parking_inc_max_deg))
        controls = self._controls(g.raan, g.inc, g.arg_lat, g.dv)

        res_a = [
            DataResidual("bt_err", 0.0, 1.0, unit="km", name="b_dot_t_error"),
            DataResidual("br_err", 0.0, 1.0, unit="km", name="b_dot_r_error"),
            DataResidual("t_peri", self.tof, 60.0, unit="s", name="time_to_periselene"),
        ]
        stage_a = solve(TargetingProblem("tli-loi/bplane", controls, res_a, self.simulate_stage_a),
                        method="newton", max_iter=25, max_step=50.0, verbose=verbose)

        stage_b = None
        if stage_a.converged:
            a = stage_a.controls
            controls_b = self._controls(a["raan"], a["parking_inc"], a["arg_lat"], a["tli_dv"], a["tli_dv_n"])
            for ctrl in controls_b.controls:
                ctrl.fd_step /= 10
            res_b = [
                DataResidual("periselene_alt", s.periselene_alt_km, 0.1, unit="km"),
                DataResidual("inc", self.inc_target, np.radians(0.001), unit="rad", name="inclination"),
                DataResidual("t_peri", self.tof, 1.0, unit="s", name="time_to_periselene"),
            ]
            stage_b = solve(TargetingProblem("tli-loi/periselene", controls_b, res_b, self.simulate_stage_b),
                            method="newton", max_iter=10, verbose=verbose)

        final = stage_b if stage_b is not None else stage_a
        converged = bool(stage_b is not None and stage_b.converged)
        ev = self.simulate_stage_b(final.controls)
        metrics = self._metrics(final.controls, ev)
        return TransferSolution(s, converged, dict(final.controls), metrics, stage_a, stage_b, ev.segments)

    # --- outputs ---------------------------------------------------------------
    def _metrics(self, c: dict, ev: Evaluation) -> dict[str, float]:
        before, after = self.tli_state(c)
        c3 = float(np.dot(after.v, after.v) - 2 * EARTH.gm / np.linalg.norm(after.r))
        peri = ev.final
        rp = np.linalg.norm(peri.r)
        ra = MOON.radius + (self.spec.apolune_alt_km if self.spec.apolune_alt_km is not None else self.spec.periselene_alt_km)
        v_capture = np.sqrt(MOON.gm * (2 / rp - 2 / (rp + ra)))
        loi = float(np.linalg.norm(peri.v) - v_capture)
        captured = peri.with_delta_v(-loi * peri.v / np.linalg.norm(peri.v))

        pole = self.eph.pole("MOON", peri.epoch)
        sun = self.eph.position("SUN", "MOON", peri.epoch)
        el_ms = cartesian_to_elements(captured.r, captured.v, MOON.gm, moon_sun_frame(pole, sun))
        entry = ev.segments["moon"].initial
        v_inf = float(np.sqrt(np.dot(entry.v, entry.v) - 2 * MOON.gm / np.linalg.norm(entry.r)))
        h_hat = np.cross(captured.r, captured.v)
        h_hat /= np.linalg.norm(h_hat)
        rot = self.eph.body_fixed_rotation("MOON", peri.epoch)
        peri_lon = float("nan")
        if rot is not None:
            pf = rot @ peri.r
            peri_lon = float(np.degrees(np.arctan2(pf[1], pf[0])))
        return {
            "tli_dv_ms": float(np.hypot(c["tli_dv"], c.get("tli_dv_n", 0.0)) * 1000),
            "tli_dv_out_of_plane_ms": float(c.get("tli_dv_n", 0.0) * 1000),
            "c3_km2s2": c3,
            "v_inf_kms": v_inf,
            "loi_dv_ms": loi * 1000,
            "total_dv_ms": float((np.hypot(c["tli_dv"], c.get("tli_dv_n", 0.0)) + loi) * 1000),
            "tof_days": ev.data["t_peri"] / DAY,
            "periselene_alt_km": float(ev.data["periselene_alt"]),
            "lunar_inc_deg": float(np.degrees(ev.data["inc"])),
            "raan_moon_sun_deg": float(np.degrees(el_ms.raan)),
            "periselene_lat_deg": float(np.degrees(np.arcsin(np.dot(peri.r, pole) / rp))),
            "arrival_epoch": float(peri.epoch),
            "parking_raan_deg": float(np.degrees(c["raan"]) % 360),
            "parking_inc_deg": float(np.degrees(c["parking_inc"])),
            "impact": float(ev.data["impact"]),
            "periselene_lon_deg": peri_lon,
            # Capture-orbit angular-momentum direction (J2000): the orbit plane,
            # which the landing analysis compares with the site's position.
            "cap_hx": float(h_hat[0]), "cap_hy": float(h_hat[1]), "cap_hz": float(h_hat[2]),
        }


def row_fields() -> list[str]:
    """Column names of TransferSolution.to_row(), in order."""
    spec = [f"spec_{k}" for k in TransferSpec.__dataclass_fields__]
    return [*spec, "converged", *CONTROL_KEYS, *METRIC_KEYS, "tli_utc"]


def design_transfer(ephemeris: EphemerisProvider, spec: TransferSpec, verbose: bool = False) -> TransferSolution:
    return TransferDesigner(ephemeris, spec).solve(verbose=verbose)
