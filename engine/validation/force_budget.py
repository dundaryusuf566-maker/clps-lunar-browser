"""Force budget: how much does each effect contribute along a trajectory?

Answers "which perturbations matter here?" - feeds both the validation report
and the UI (e.g. a stacked chart of accelerations along a transfer).
"""

from __future__ import annotations

import numpy as np

from ..propagators.propagator import Trajectory


def force_budget(traj: Trajectory, n_samples: int = 200) -> list[dict]:
    dyn = traj.dynamics
    ts, ys = traj.sample(n_samples)
    mags: dict[str, list[float]] = {f.name: [] for f in dyn.active_forces}
    for t, y in zip(ts, ys):
        for name, a in dyn.breakdown(t, y).items():
            mags[name].append(float(np.linalg.norm(a)))
    total = np.array([np.linalg.norm(dyn.acceleration(t, y)) for t, y in zip(ts, ys)])
    rows = []
    for name, m in mags.items():
        m = np.asarray(m)
        rows.append({
            "force": name,
            "mean_km_s2": float(m.mean()),
            "max_km_s2": float(m.max()),
            "min_km_s2": float(m.min()),
            "mean_ratio_to_total": float(np.mean(m / total)),
        })
    rows.sort(key=lambda r: r["mean_km_s2"], reverse=True)
    return rows


def format_budget(rows: list[dict]) -> str:
    out = [f"  {'force':<28}{'mean [km/s²]':>14}{'max [km/s²]':>14}{'mean / total':>14}"]
    for r in rows:
        out.append(f"  {r['force']:<28}{r['mean_km_s2']:>14.3e}{r['max_km_s2']:>14.3e}{r['mean_ratio_to_total']:>14.2e}")
    return "\n".join(out)
