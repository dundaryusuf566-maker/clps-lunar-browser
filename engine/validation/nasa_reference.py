"""Comparison with the NASA Ames Lunar Browser reference figure.

Reference: Genova, Morrison-Fogel & Levinson-Muth, "Transfers from TLI to Lunar
Frozen Orbits with Applications to NASA's CLPS & Artemis Programs", AAS/AIAA
Space Flight Mechanics Meeting, Jan 2024; figure "LOI dV vs. Launch Epoch, from
December 2025 to March 2026" in the NASA Ames Lunar Browser slides (challenge
resource). NASA publishes the figure, not the data, so the values below were
read off it: dates to about +-1.5 days, delta-v to about +-3 m/s.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

REFERENCE = {
    "source": ("Genova, Morrison-Fogel & Levinson-Muth (2024), AAS/AIAA Space Flight Mechanics Meeting; "
               "NASA Ames Lunar Browser slides, figure 'LOI dV vs. Launch Epoch, December 2025 to March 2026'"),
    "read_accuracy": "read off the published figure: dates +-1.5 days, delta-v +-3 m/s",
    "window": ["2025-12-07", "2026-03-31"],
    "tof_days": [4, 12],
    "loi_min_ms": 797.0,
    "loi_max_ms": 980.0,
    # Lowest point of each monthly trough (launch date, LOI delta-v).
    "minima": [
        {"month": "2025-12", "date": "2025-12-11", "loi_dv_ms": 797.0},
        {"month": "2026-01", "date": "2026-01-08", "loi_dv_ms": 797.0},
        {"month": "2026-02", "date": "2026-02-05", "loi_dv_ms": 797.0},
        {"month": "2026-03", "date": "2026-03-05", "loi_dv_ms": 799.0},
    ],
}


def compare(rows: list[dict], dense_rows: list[dict] | None = None) -> dict:
    """Our sweep (CSV rows, converged only) against the reference figure."""
    ok = [r for r in rows if str(r.get("converged")) == "True"]
    if not ok:
        raise ValueError("no converged transfers to compare")
    v = [float(r["loi_dv_ms"]) for r in ok]
    lo, hi = min(v), max(v)
    by_month: dict[str, list[dict]] = defaultdict(list)
    for r in ok:
        by_month[r["tli_utc"][:7]].append(r)
    minima = []
    for ref in REFERENCE["minima"]:
        cand = by_month.get(ref["month"], [])
        if not cand:
            continue
        best = min(cand, key=lambda r: float(r["loi_dv_ms"]))
        d_ours = date.fromisoformat(best["tli_utc"][:10])
        minima.append({
            "month": ref["month"],
            "nasa_date": ref["date"], "nasa_loi_dv_ms": ref["loi_dv_ms"],
            "our_date": d_ours.isoformat(), "our_loi_dv_ms": round(float(best["loi_dv_ms"]), 1),
            "our_tof_days": float(best["spec_tof_days"]),
            "days_apart": (d_ours - date.fromisoformat(ref["date"])).days,
        })
    steps = sorted({r["tli_utc"][:10] for r in ok})
    grid = (date.fromisoformat(steps[1]) - date.fromisoformat(steps[0])).days if len(steps) > 1 else None
    points = [{"tli": r["tli_utc"][:10], "tof": float(r["spec_tof_days"]), "loi": round(float(r["loi_dv_ms"]), 1)}
              for r in sorted(ok, key=lambda r: (r["tli_utc"], float(r["spec_tof_days"])))]
    out = {
        "reference": REFERENCE,
        "ephemeris": ok[0].get("ephemeris", ""),
        "count": len(ok), "requested": len(rows),
        "grid_days": grid,
        "band_ms": [round(lo, 1), round(hi, 1)],
        "band_error_ms": [round(lo - REFERENCE["loi_min_ms"], 1), round(hi - REFERENCE["loi_max_ms"], 1)],
        "minima": minima,
        "points": points,
    }
    if dense_rows:
        d = [r for r in dense_rows if str(r.get("converged")) == "True"]
        if d:
            b = min(d, key=lambda r: float(r["loi_dv_ms"]))
            ref = min(REFERENCE["minima"], key=lambda m: abs((date.fromisoformat(m["date"]) -
                                                              date.fromisoformat(b["tli_utc"][:10])).days))
            out["dense_minimum"] = {
                "count": len(d), "tli_utc": b["tli_utc"][:16], "tof_days": float(b["spec_tof_days"]),
                "loi_dv_ms": round(float(b["loi_dv_ms"]), 1), "nasa_loi_dv_ms": ref["loi_dv_ms"],
                "error_pct": round(100 * (float(b["loi_dv_ms"]) - ref["loi_dv_ms"]) / ref["loi_dv_ms"], 2),
            }
    return out
