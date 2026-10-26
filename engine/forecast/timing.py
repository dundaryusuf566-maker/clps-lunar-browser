"""When: launch windows and landing dates for an upcoming mission.

The same transfer design, landing rule and loiter limit that were tested on
IM-1 and IM-2 (engine/validation/retrodiction.py), plus the operator's
announced minimum sunlight after touchdown. Nothing here is tuned to a result.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone

import numpy as np

from ..core.time import tdb_to_utc, utc_to_tdb
from ..ephemeris.cached import CachedEphemeris
from ..surface.landing import LandingConstraints, SiteTimeline, analyze, arrival_from_row
from ..validation.retrodiction import MISSION_CONSTRAINTS, SCAN_INCS, SCAN_TOFS, launch_windows
from .upcoming import UpcomingMission

DAY = 86_400.0


def forecast_constraints(m: UpcomingMission) -> LandingConstraints:
    """The retrodiction's constraints with the mission's sunlight requirement."""
    return replace(MISSION_CONSTRAINTS, min_daylight_days=m.min_daylight_days, energy_window_days=m.energy_window_days)


def _day0(iso: str) -> datetime:
    return datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)


def forecast_jobs(m: UpcomingMission, tofs=SCAN_TOFS, incs=SCAN_INCS, family: int = 1,
                  alt_km: float = 100.0) -> list[dict]:
    """One TLI per day (00:00 UTC) over the scanned period, every transit time and inclination."""
    jobs, d, last = [], _day0(m.tli_first), _day0(m.tli_last)
    while d <= last:
        e = utc_to_tdb(d)
        jobs += [dict(tli_epoch=e, tof_days=float(t), family=family, lunar_inc_deg=float(i),
                      periselene_alt_km=alt_km, parking_inc_deg=28.5) for t in tofs for i in incs]
        d += timedelta(days=1)
    return jobs


def jobs_span(jobs: list[dict], c: LandingConstraints) -> tuple[float, float]:
    tli = [j["tli_epoch"] for j in jobs]
    arr = [j["tli_epoch"] + j["tof_days"] * DAY for j in jobs]
    return min(tli) - 2 * DAY, max(arr) + (c.max_wait_days + c.daylight_horizon_days + 25) * DAY


def _utc(epoch: float | None) -> str | None:
    return None if epoch is None else tdb_to_utc(epoch).isoformat(timespec="minutes").replace("+00:00", "Z")


def time_forecast(cache: CachedEphemeris, m: UpcomingMission, rows: list[dict],
                  c: LandingConstraints | None = None, calibration: list[dict] | None = None) -> dict:
    """Best landing option for every TLI day, grouped into launch windows."""
    c = c or forecast_constraints(m)
    site = m.site()
    rows = [r for r in rows if str(r.get("converged")) == "True"]
    if not rows:
        raise ValueError("no converged transfers to forecast from")
    arrivals = [arrival_from_row(r) for r in rows]
    a = np.array([x.arrival_epoch for x in arrivals])
    tl = SiteTimeline.build(cache, site, a.min() + c.min_coast_days * DAY - 3600,
                            a.max() + (c.max_wait_days + c.daylight_horizon_days + 1) * DAY, c)
    by_day: dict[str, list] = {}
    for row, arr in zip(rows, arrivals):
        res = analyze(arr, tl, c, cache.pole("MOON", arr.arrival_epoch))
        by_day.setdefault(tdb_to_utc(float(row["spec_tli_epoch"])).date().isoformat(), []).append((row, res))

    days = []
    for day in sorted(by_day):
        opts = by_day[day]
        ok = [(r, x) for r, x in opts if x.feasible]
        best = min(ok, key=lambda p: (p[1].total_from_loi_ms, p[1].landing_epoch)) if ok else None
        landings = sorted(x.landing_epoch for _, x in ok)
        days.append({
            "tli_day": day, "feasible": best is not None, "options": len(ok), "tried": len(opts),
            "tof_days": None if best is None else float(best[0]["spec_tof_days"]),
            "lunar_inc_deg": None if best is None else round(float(best[0]["spec_lunar_inc_deg"]), 1),
            "landing_utc": None if best is None else best[1].landing_utc,
            "landing_range_utc": [_utc(landings[0]), _utc(landings[-1])] if landings else None,
            "wait_days": None if best is None else round(best[1].wait_days, 2),
            "daylight_days": None if best is None else round(best[1].daylight_days, 2),
            "daylight_capped": None if best is None else bool(best[1].daylight_capped),
            "sun_elev_deg": None if best is None else round(best[1].sun_elev_deg, 2),
            "sun_horizon_deg": None if best is None else round(best[1].sun_horizon_deg or 0.0, 2),
            "dsn_stations": None if best is None else best[1].dsn_stations,
            "energy_pct": None if best is None else round(best[1].energy_pct, 1),
            "max_dark_gap_h": None if best is None else round(best[1].max_dark_gap_h, 1),
            "loi_dv_ms": None if best is None else round(float(best[0]["loi_dv_ms"]), 1),
            "total_from_loi_ms": None if best is None else round(best[1].total_from_loi_ms, 1),
            "why_not": "" if best is not None else ",".join(sorted({x.code for _, x in opts})),
        })

    windows = []
    for w in launch_windows([d["tli_day"] for d in days], [d["feasible"] for d in days]):
        inside = [d for d in days if w["first"] <= d["tli_day"] <= w["last"] and d["feasible"]]
        best = min(inside, key=lambda d: d["total_from_loi_ms"])
        land = sorted(d["landing_utc"] for d in inside)
        windows.append({**w, "landing_first_utc": land[0], "landing_last_utc": land[-1],
                        "best_tli_day": best["tli_day"], "best_landing_utc": best["landing_utc"],
                        "best_total_from_loi_ms": best["total_from_loi_ms"],
                        "min_daylight_days": min(d["daylight_days"] for d in inside),
                        "max_daylight_days": max(d["daylight_days"] for d in inside)})
    return {
        "reference": {"name": m.reference_name, "lat_deg": m.reference_lat, "lon_deg": m.reference_lon,
                      "terrain": tl.terrain},
        "constraints": c.to_dict(),
        "tofs": sorted({float(r["spec_tof_days"]) for r in rows}),
        "incs": sorted({round(float(r["spec_lunar_inc_deg"]), 1) for r in rows}),
        "transfers": len(rows),
        "days": days, "windows": windows,
        "calibration": calibration or [],
    }
