"""Demo: target a lunar arrival to a 100 km polar periselene with a small
trajectory-correction maneuver (TCM), then report the LOI cost.

This is a miniature of the real TLI -> LOI problem and exercises every layer:
ephemeris, force composer, events, residuals, solver, force budget.

    python examples/01_lunar_arrival_targeting.py
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from engine.core.constants import BODIES
from engine.core.frames import frame_from_pole
from engine.core.state import State
from engine.core.time import utc_to_tdb
from engine.dynamics import earth_moon_model
from engine.ephemeris import AnalyticEphemeris
from engine.orbits import Elements, elements_to_cartesian
from engine.propagators import Impact, Periapsis, propagate
from engine.targeting import Control, ControlVector, Evaluation, FinalElement, TargetingProblem, solve
from engine.validation import force_budget, format_budget

MOON = BODIES["MOON"]
eph = AnalyticEphemeris()
dyn = earth_moon_model("MOON", eph, fidelity="high")
epoch = utc_to_tdb(datetime(2026, 11, 14, 12, tzinfo=timezone.utc))

# Lunar-equator frame: inclination is measured w.r.t. the Moon's pole.
lunar_eq = frame_from_pole(eph.pole("MOON", epoch), np.array([1.0, 0.0, 0.0]))

# Incoming hyperbola, deliberately off-target: 300 km periselene, 80 deg inclination.
v_inf = 0.9
sma = -MOON.gm / v_inf**2
rp = MOON.radius + 300.0
ecc = 1 - rp / sma
p = sma * (1 - ecc**2)
nu0 = -np.arccos((p / 30_000.0 - 1) / ecc)  # inbound, 30 000 km from the Moon
arrival = Elements(sma, ecc, np.radians(80.0), np.radians(40.0), np.radians(250.0), nu0)
s0 = State(epoch, elements_to_cartesian(arrival, MOON.gm, frame=lunar_eq), "MOON")


def simulate(c: dict) -> Evaluation:
    dv = np.array([c["tcm_x"], c["tcm_y"], c["tcm_z"]])
    traj = propagate(dyn, s0.with_delta_v(dv), 3 * 86_400, events=[Periapsis(terminal=True), Impact()], dense=False)
    final = traj.final
    v_p = np.linalg.norm(final.v)
    loi = v_p - np.sqrt(MOON.gm / np.linalg.norm(final.r))  # circularize at periselene
    return Evaluation(final=final, segments={"coast": traj},
                      data={"tcm_dv": float(np.linalg.norm(dv)), "loi_dv": float(loi),
                            "tof_h": (final.epoch - epoch) / 3600})


controls = ControlVector([Control(f"tcm_{a}", 0.0, scale=0.01, fd_step=1e-5, unit="km/s") for a in "xyz"])
residuals = [
    FinalElement("periapsis_alt", 100.0, 0.01, MOON.gm, body_radius=MOON.radius),
    FinalElement("inc", np.radians(90.0), np.radians(0.001), MOON.gm, frame=lunar_eq),
]
problem = TargetingProblem("lunar-arrival", controls, residuals, simulate)

print("Initial residuals:")
for row in problem.report(simulate(controls.as_dict())):
    print(f"  {row['name']:<20} {row['measured']:>10.4f} -> target {row['target']:.4f} {row['unit']}")

result = solve(problem, method="newton", verbose=True)
print()
print(result.summary())
d = result.evaluation.data
print(f"\n  TCM  dv = {d['tcm_dv'] * 1000:8.2f} m/s   (min-norm: 3 controls, 2 residuals)")
print(f"  LOI  dv = {d['loi_dv'] * 1000:8.2f} m/s   (circularize at periselene)")
print(f"  time to periselene = {d['tof_h']:.2f} h")

print("\nForce budget along the converged arrival:")
traj = propagate(dyn, s0.with_delta_v([result.controls[f"tcm_{a}"] for a in "xyz"]),
                 d["tof_h"] * 3600)
print(format_budget(force_budget(traj)))
