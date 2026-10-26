"""Retrodiction: run the browser on a mission that already flew and compare.

Three questions, each answered only from the launch date, the site coordinates
and the capture orbit (nothing about the real landing goes in):

1. Reconstruction. With the real TLI epoch and transit time, does the engine
   converge, and is its LOI delta-v close to the reported one? Does the landing
   analysis of that arrival find the real touchdown instant landable
   (lighting, Earth in view, plane change within budget)?
2. Lighting at the real touchdown (flat horizon): Sun and Earth elevation,
   rising or setting Sun, sunrise before and sunset after.
3. Launch windows. Scan TLI dates around the launch, keep the days from which a
   landing is possible within a short loiter, group them into windows and check
   that the real launch windows fall inside them.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import numpy as np

from ..core.time import tdb_to_utc, utc_to_tdb
from ..ephemeris.cached import CachedEphemeris
from ..surface.geometry import earth_az_el_deg, local_frame, sun_az_el_deg
from ..surface.ground import dsn_mask, site_from_earth_km, station_names
from ..surface.terrain import load_horizon
from ..surface.landing import (
    LandingConstraints, SiteTimeline, analyze, arrival_from_row, intervals, opportunities,
)
from .missions import MissionRecord

DAY = 86_400.0

# CLPS landers carry little loiter capability: IM-1 waited 1.3 days in lunar
# orbit, IM-2 3.2 days. The scan therefore allows at most 4 days.
MISSION_CONSTRAINTS = LandingConstraints(max_wait_days=4.0)
SCAN_TOFS = (4.0, 5.0, 6.0, 7.0)
# The capture inclination is a design choice. A polar site sits a few degrees
# from the pole, so a strictly polar orbit only passes over it twice a month;
# tilting the orbit a few degrees brings the site under the ground track sooner.
# The band is near-polar (80-100 deg). The scan grid step (4 deg) is under twice
# the plane-change budget angle (5.3 deg at 100 km), so every inclination in the
# band is within 2 deg of a grid point.
RECON_INCS = tuple(float(i) for i in range(80, 101))
SCAN_INCS = (82.0, 86.0, 90.0, 94.0, 98.0)


def mission_constraints(m: MissionRecord, c: LandingConstraints = MISSION_CONSTRAINTS) -> LandingConstraints:
    """The retrodiction's constraints, with the mission's published loiter in lunar orbit where it has one."""
    return c if m.max_wait_days is None else replace(c, max_wait_days=m.max_wait_days)


def utc_epoch(iso: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc))


def utc_str(epoch: float | None, spec: str = "minutes") -> str | None:
    return None if epoch is None else tdb_to_utc(epoch).isoformat(timespec=spec).replace("+00:00", "Z")


def _day(epoch: float) -> str:
    return tdb_to_utc(epoch).date().isoformat()


# --- jobs ------------------------------------------------------------------------
def reconstruction_jobs(m: MissionRecord, incs=None) -> list[dict]:
    """The real TLI epoch and transit time, both approach families, the mission's inclination band."""
    incs = incs or m.recon_incs or RECON_INCS
    tli, loi = utc_epoch(m.tli_utc), utc_epoch(m.loi_utc)
    return [dict(tli_epoch=tli, tof_days=round((loi - tli) / DAY, 4), family=f, lunar_inc_deg=float(i),
                 periselene_alt_km=m.orbit_alt_km, parking_inc_deg=28.5) for i in incs for f in (1, -1)]


def scan_jobs(m: MissionRecord, days_before: int, days_after: int, tofs=SCAN_TOFS, incs=None,
              family: int = 1, alt_km: float = 100.0) -> list[dict]:
    """One TLI per day at the real TLI time of day, from `days_before` to `days_after`."""
    incs = incs or m.scan_incs or SCAN_INCS
    tli = utc_epoch(m.tli_utc)
    return [dict(tli_epoch=tli + d * DAY, tof_days=float(t), family=family, lunar_inc_deg=float(i),
                 periselene_alt_km=alt_km, parking_inc_deg=28.5)
            for d in range(-days_before, days_after + 1) for t in tofs for i in incs]


def window_span(jobs: list[dict], c: LandingConstraints) -> tuple[float, float]:
    """Ephemeris span the analysis of these jobs needs."""
    tli = [j["tli_epoch"] for j in jobs]
    arr = [j["tli_epoch"] + j["tof_days"] * DAY for j in jobs]
    return min(tli) - 2 * DAY, max(arr) + (c.max_wait_days + c.daylight_horizon_days + 25) * DAY


# --- lighting ----------------------------------------------------------------------
def _sun_events(ts: np.ndarray, clear: np.ndarray, epoch: float, i: int) -> dict:
    above = clear > 0
    rise = np.flatnonzero(above[1:] & ~above[:-1]) + 1
    sets = np.flatnonzero(~above[1:] & above[:-1]) + 1
    rise, sets = rise[rise <= i], sets[sets > i]
    sunrise = float(ts[rise[-1]]) if rise.size else None
    sunset = float(ts[sets[0]]) if sets.size else None
    return {
        "sunrise_utc": utc_str(sunrise), "sunset_utc": utc_str(sunset),
        "days_since_sunrise": None if sunrise is None else round((epoch - sunrise) / DAY, 2),
        "daylight_left_days": None if sunset is None else round((sunset - epoch) / DAY, 2),
    }


def lighting(cache: CachedEphemeris, site, epoch: float, span_days: float = 20.0, step_s: float = 600.0) -> dict:
    """Sun / Earth geometry at `epoch` with the surrounding sunrise / sunset, on a
    flat horizon and, when the site has a LOLA horizon mask, above the terrain."""
    ts = epoch + np.arange(-span_days * DAY, span_days * DAY + step_s, step_s)
    ts = ts[(ts >= cache.t0) & (ts <= cache.t1)]
    frame = local_frame(cache, site, ts)
    sun_az, sun = sun_az_el_deg(cache, site, ts, frame)
    earth_az, earth = earth_az_el_deg(cache, site, ts, frame)
    i = int(np.argmin(np.abs(ts - epoch)))
    dsn = dsn_mask(ts[i:i + 1], site_from_earth_km(cache, ts[i:i + 1], frame[0][i:i + 1]))
    out = {
        "dsn_stations": station_names(int(dsn[0])),
        "sun_elev_deg": round(float(sun[i]), 2),
        "sun_az_deg": round(float(sun_az[i]), 1),
        "earth_elev_deg": round(float(earth[i]), 2),
        "sun_rising": bool(sun[min(i + 1, len(ts) - 1)] > sun[max(i - 1, 0)]),
        "max_sun_elev_deg": round(float(sun.max()), 2),
        **_sun_events(ts, sun, epoch, i),
        "terrain": None,
    }
    mask = load_horizon(site.horizon) if getattr(site, "horizon", None) else None
    if mask is not None:
        sun_hz, earth_hz = mask.elevation(sun_az), mask.elevation(earth_az)
        out["terrain"] = {
            "source": mask.source, "observer_m": mask.observer_m, "site_height_m": round(mask.site_height_m, 0),
            "horizon_sun_deg": round(float(sun_hz[i]), 2),
            "sun_clear_deg": round(float(sun[i] - sun_hz[i]), 2),
            "earth_clear_deg": round(float(earth[i] - earth_hz[i]), 2),
            **_sun_events(ts, sun - sun_hz, epoch, i),
        }
    return out


# --- 1. reconstruction ---------------------------------------------------------------
def _spec_inc(row: dict) -> float:
    return round(float(row["spec_lunar_inc_deg"]), 3)


def reconstruct(cache: CachedEphemeris, m: MissionRecord, rows: list[dict],
                c: LandingConstraints = MISSION_CONSTRAINTS) -> dict:
    """Landing analysis of every arrival designed with the real TLI and transit time.

    Returns the strictly polar orbit (what the database assumes) and the
    near-polar inclination that best serves the real touchdown."""
    site = m.site()
    land = utc_epoch(m.landing_utc)
    designs, failed = [], 0
    for row in rows:
        if str(row.get("converged")) != "True":
            failed += 1
            continue
        arr = arrival_from_row(row)
        start = arr.arrival_epoch + c.min_coast_days * DAY - 3600
        end = arr.arrival_epoch + (c.max_wait_days + c.daylight_horizon_days + 1) * DAY
        tl = SiteTimeline.build(cache, site, start, end, c)
        pole = cache.pole("MOON", arr.arrival_epoch)
        res = analyze(arr, tl, c, pole)
        op = opportunities(arr, tl, c, pole)
        landable = op.landable(c.max_plane_change_ms)
        k = int(np.argmin(np.abs(op.ts - land)))
        in_wait = op.ts[0] <= land <= op.ts[-1]
        designs.append({
            "family": int(float(row["spec_family"])),
            "lunar_inc_deg": _spec_inc(row),
            "tof_days": round(float(row["tof_days"]), 3),
            "loi_dv_ms": round(arr.loi_ms, 1),
            "loi_dv_error_pct": None if m.loi_dv_ms is None else round(100 * (arr.loi_ms - m.loi_dv_ms) / m.loi_dv_ms, 2),
            "tli_dv_ms": round(float(row["tli_dv_ms"]), 1),
            "c3_km2s2": round(float(row["c3_km2s2"]), 3),
            "arrival_utc": utc_str(arr.arrival_epoch),
            "windows": [{"start_utc": utc_str(a), "end_utc": utc_str(b), "hours": round((b - a) / 3600, 1)}
                        for a, b in intervals(op.ts, landable)],
            "first_landing": res.to_dict(),
            "at_real_landing": None if not in_wait else {
                "plane_change_deg": round(float(op.angle_deg[k]), 2),
                "plane_change_ms": round(float(op.plane_ms[k]), 1),
                "light_and_comms_ok": bool(op.ok[k]),
                "landable": bool(landable[k]),
            },
            "real_landing_landable": bool(in_wait and landable[k]),
        })
    polar = [d for d in designs if abs(d["lunar_inc_deg"] - 90.0) < 1e-6]
    scored = [d for d in designs if d["at_real_landing"] is not None]
    tuned = min(scored, key=lambda d: d["at_real_landing"]["plane_change_ms"]) if scored else None
    loi = [d["loi_dv_ms"] for d in designs]
    return {
        "designs": len(designs), "failed": failed,
        "polar": polar,
        "tuned": tuned,
        "landable_incs": sorted({d["lunar_inc_deg"] for d in designs if d["real_landing_landable"]}),
        "loi_dv_range_ms": [min(loi), max(loi)] if loi else None,
        "loi_dv_reported_ms": m.loi_dv_ms,
        "curve": [{"inc": d["lunar_inc_deg"], "family": d["family"],
                   "plane_ms": None if d["at_real_landing"] is None else d["at_real_landing"]["plane_change_ms"]}
                  for d in sorted(designs, key=lambda d: (d["family"], d["lunar_inc_deg"]))],
    }


# --- 3. launch-window scan ------------------------------------------------------------
def scan(cache: CachedEphemeris, m: MissionRecord, rows: list[dict], c: LandingConstraints = MISSION_CONSTRAINTS) -> dict:
    """Best landing option for every scanned TLI day, grouped into launch windows."""
    site = m.site()
    rows = [r for r in rows if str(r.get("converged")) == "True"]
    arrivals = [arrival_from_row(r) for r in rows]
    a = np.array([x.arrival_epoch for x in arrivals])
    tl = SiteTimeline.build(cache, site, a.min() + c.min_coast_days * DAY - 3600,
                            a.max() + (c.max_wait_days + c.daylight_horizon_days + 1) * DAY, c)
    by_day: dict[str, list] = {}
    for row, arr in zip(rows, arrivals):
        res = analyze(arr, tl, c, cache.pole("MOON", arr.arrival_epoch))
        by_day.setdefault(_day(float(row["spec_tli_epoch"])), []).append((row, res))

    days = []
    for day in sorted(by_day):
        opts = by_day[day]
        ok = [(r, x) for r, x in opts if x.feasible]
        best = min(ok, key=lambda p: (p[1].total_from_loi_ms, p[1].landing_epoch)) if ok else None
        codes = sorted({x.code for _, x in opts if not x.feasible})
        days.append({
            "tli_day": day,
            "feasible": best is not None,
            "feasible_polar": any(abs(_spec_inc(r) - 90.0) < 1e-6 for r, _ in ok),
            "options": len(ok), "tried": len(opts),
            "tof_days": None if best is None else float(best[0]["spec_tof_days"]),
            "lunar_inc_deg": None if best is None else _spec_inc(best[0]),
            "landing_utc": None if best is None else best[1].landing_utc,
            "wait_days": None if best is None else round(best[1].wait_days, 2),
            "daylight_days": None if best is None else round(best[1].daylight_days, 2),
            "loi_dv_ms": None if best is None else round(float(best[0]["loi_dv_ms"]), 1),
            "surface_dv_ms": None if best is None else round(best[1].surface_dv_ms, 1),
            "total_from_loi_ms": None if best is None else round(best[1].total_from_loi_ms, 1),
            "why_not": "" if best is not None else ",".join(codes),
        })

    windows = launch_windows([d["tli_day"] for d in days], [d["feasible"] for d in days])
    windows_polar = launch_windows([d["tli_day"] for d in days], [d["feasible_polar"] for d in days])
    real = []
    for first, last, note in m.launch_windows:
        inside = [w for w in windows if w["first"] <= first and last <= w["last"]]
        covered = [d["tli_day"] for d in days if first <= d["tli_day"] <= last and d["feasible"]]
        scanned = [d["tli_day"] for d in days if first <= d["tli_day"] <= last]
        real.append({"first": first, "last": last, "note": note, "scanned_days": len(scanned),
                     "feasible_days": len(covered), "inside_predicted": bool(inside) and len(scanned) > 0,
                     "predicted": inside[0] if inside else None})
    launch_day = tdb_to_utc(utc_epoch(m.launch_utc)).date().isoformat()
    on_launch = next((d for d in days if d["tli_day"] == _day(utc_epoch(m.tli_utc))), None)
    return {"constraints": c.to_dict(), "tofs": sorted({float(r["spec_tof_days"]) for r in rows}),
            "incs": sorted({_spec_inc(r) for r in rows}),
            "days": days, "windows": windows, "windows_polar": windows_polar, "real_windows": real,
            "launch_day": launch_day, "on_launch_day": on_launch}


def launch_windows(days: list[str], feasible: list[bool]) -> list[dict]:
    """Runs of consecutive feasible days (a missing day breaks the run)."""
    out, run = [], []
    prev = None
    for day, ok in zip(days, feasible):
        d = datetime.fromisoformat(day).date()
        if ok and run and prev is not None and (d - prev).days == 1:
            run.append(day)
        elif ok:
            if run:
                out.append(run)
            run = [day]
        else:
            if run:
                out.append(run)
            run = []
        prev = d
    if run:
        out.append(run)
    return [{"first": r[0], "last": r[-1], "days": len(r)} for r in out]


# --- everything for one mission --------------------------------------------------------
def retrodict(cache: CachedEphemeris, m: MissionRecord, point_rows: list[dict], scan_rows: list[dict],
              c: LandingConstraints = MISSION_CONSTRAINTS) -> dict:
    c = mission_constraints(m, c)
    land = utc_epoch(m.landing_utc)
    light = lighting(cache, m.site(), land)
    recon = reconstruct(cache, m, point_rows, c)
    sc = scan(cache, m, scan_rows, c)
    end = None
    if m.surface_end_utc and light["sunset_utc"]:
        end = round((utc_epoch(m.surface_end_utc) - land) / DAY, 2)
    t = light["terrain"] if c.use_terrain else None
    horizon = "LOLA terrain" if t else "flat"
    sun_clear = t["sun_clear_deg"] if t else light["sun_elev_deg"]
    earth_clear = t["earth_clear_deg"] if t else light["earth_elev_deg"]
    checks = [
        {"id": "converged", "label": "Engine converges on the real TLI date and transit time",
         "pass": recon["failed"] == 0 and recon["designs"] > 0,
         "value": f"{recon['designs']}/{recon['designs'] + recon['failed']}"},
        {"id": "sun", "label": f"Sun up and rising at the real touchdown ({horizon} horizon, browser's lighting rule)",
         "pass": m.site().sun_min_deg <= sun_clear <= m.site().sun_max_deg and light["sun_rising"], "value": sun_clear},
        {"id": "earth", "label": f"Earth in view at the real touchdown ({horizon} horizon)",
         "pass": earth_clear >= c.min_earth_elev_deg, "value": earth_clear},
        {"id": "landable", "label": "Real touchdown is landable from the reconstructed arrival"
         + (" (near-polar orbit)" if m.polar else f" (capture orbit {min(m.recon_incs or RECON_INCS):g}-{max(m.recon_incs or RECON_INCS):g} deg)"),
         "pass": bool(recon["landable_incs"]),
         "value": None if recon["tuned"] is None else recon["tuned"]["at_real_landing"]["plane_change_ms"]},
    ]
    if m.launch_windows:                     # no launch window to test when the launch was not tied to the Moon
        checks.append({"id": "windows", "label": "Every real launch window lies inside a predicted window",
                       "pass": all(w["inside_predicted"] for w in sc["real_windows"])})
    on = sc["on_launch_day"]
    miss = None
    if on and on["landing_utc"]:
        miss = round((utc_epoch(on["landing_utc"]) - land) / DAY, 2)
    sc["landing_miss_days"] = miss
    checks.append({"id": "landing-date",
                   "label": "From the real launch day, the browser's own pick lands within a day of the real touchdown"
                   if m.launch_windows else "From the real TLI day, the browser's own pick lands within a day of the real touchdown",
                   "pass": miss is not None and abs(miss) <= 1.0, "value": miss})
    sunset = None
    if m.sunset_utc:
        pred = light["terrain"]["sunset_utc"] if (light["terrain"] and c.use_terrain) else light["sunset_utc"]
        hours = None if pred is None else round((utc_epoch(pred) - utc_epoch(m.sunset_utc)) / 3600.0, 2)
        sunset = {"predicted_utc": pred, "real_utc": m.sunset_utc, "hours_off": hours, "tolerance_h": m.sunset_tol_h,
                  "note": m.sunset_note}
        checks.append({"id": "sunset", "label": f"Sunset after the touchdown within {m.sunset_tol_h:g} h of the real one ({horizon} horizon)",
                       "pass": hours is not None and abs(hours) <= m.sunset_tol_h, "value": hours})
    if m.loi_dv_ms is not None and recon["polar"]:
        err = min(abs(r["loi_dv_error_pct"]) for r in recon["polar"])
        checks.insert(1, {"id": "loi", "label": f"LOI delta-v within 3% of the reported {m.loi_dv_ms:.0f} m/s",
                          "pass": err <= 3.0, "value": err})
    return {
        "mission": m.to_dict(),
        "ephemeris": cache.source,
        "lighting_at_landing": light,
        "sunset": sunset,
        "constraints": c.to_dict(),
        "surface_days_flown": end,
        "reconstruction": recon,
        "scan": sc,
        "checks": checks,
    }
