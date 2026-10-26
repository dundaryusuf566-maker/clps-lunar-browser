"""Build the 3D journey data: IM-1 and IM-2 as reconstructed, Griffin-1 as forecast.

    python scripts/build_journeys.py --spice          (~1 minute)

Needs, from earlier runs (no new transfers are designed here):
    data/cache/retro_im-1_spice_point.csv, retro_im-2_spice_point.csv   (build_validation.py)
    data/cache/forecast_griffin-1_spice.csv, web/public/data/forecast.json (build_forecast.py)
and optionally the LOLA map (data/terrain) for the south polar terrain on the Moon.

IM-1 and IM-2: the real TLI date and transit time, the near-polar orbit that needs
the smallest plane change for the real touchdown, landing at the real touchdown
time (the reconstruction on the Validation page). Griffin-1: the best launch of the
forecast's first window (or --window N), landing when the forecast says.

Writes web/public/data/journeys.json (+ moon_cap.bin with the polar terrain).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from sweep_transfers import read_rows  # noqa: E402

from engine import __version__  # noqa: E402
from engine.core.time import tdb_to_utc  # noqa: E402
from engine.database.webexport import controls_from_row, parse_row, spec_from_row  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.forecast import forecast_constraints, get_upcoming  # noqa: E402
from engine.mission.journey import build_journey  # noqa: E402
from engine.mission.transfer import TransferDesigner  # noqa: E402
from engine.surface import SiteTimeline, analyze, arrival_from_row, opportunities  # noqa: E402
from engine.surface.terrain import PolarGrid, load_horizon  # noqa: E402
from engine.validation.missions import MISSIONS  # noqa: E402
from engine.validation.retrodiction import MISSION_CONSTRAINTS, utc_epoch  # noqa: E402

CACHE = ROOT / "data" / "cache"
DATA = ROOT / "web" / "public" / "data"
DEM_PATH = ROOT / "data" / "terrain" / "ldem_75s_120m.img"
DAY = 86_400.0


def _utc(e: float) -> str:
    return tdb_to_utc(e).isoformat(timespec="minutes").replace("+00:00", "Z")


def _height_m(site) -> float:
    mask = load_horizon(site.horizon) if site.horizon else None
    return float(mask.site_height_m) if mask is not None else 0.0


def _span(rows: list[dict], extra_days: float) -> tuple[float, float]:
    tli = [float(r["spec_tli_epoch"]) for r in rows]
    arr = [float(r["arrival_epoch"]) for r in rows]
    return min(tli) - 2 * DAY, max(arr) + extra_days * DAY


def flown(m, tag: str, spice: bool) -> dict | None:
    path = CACHE / f"retro_{m.id}_{tag}_point.csv"
    rows = [parse_row(r) for r in read_rows(path) if str(r.get("converged")) == "True"]
    if not rows:
        print(f"  {path.name} missing or empty: run scripts/build_validation.py first; skipping {m.id}")
        return None
    c = MISSION_CONSTRAINTS
    site = m.site()
    land = utc_epoch(m.landing_utc)
    cache = cached_for_window(spice, *_span(rows, c.max_wait_days + c.daylight_horizon_days + 3))
    best = None
    for row in rows:
        arr = arrival_from_row(row)
        tl = SiteTimeline.build(cache, site, arr.arrival_epoch + c.min_coast_days * DAY - 3600,
                                arr.arrival_epoch + (c.max_wait_days + c.daylight_horizon_days + 1) * DAY, c)
        op = opportunities(arr, tl, c, cache.pole("MOON", arr.arrival_epoch))
        if not op.ts[0] <= land <= op.ts[-1]:
            continue
        k = int(np.argmin(np.abs(op.ts - land)))
        if best is None or op.plane_ms[k] < best[1]:
            best = (row, float(op.plane_ms[k]), float(op.angle_deg[k]), bool(op.landable(c.max_plane_change_ms)[k]))
    if best is None:
        print(f"  no reconstructed arrival covers the real touchdown of {m.id}")
        return None
    row, pc_ms, pc_deg, landable = best
    arr = arrival_from_row(row)
    j = build_journey(cache, TransferDesigner(cache, spec_from_row(row)), controls_from_row(row), arr, site,
                      _height_m(site), land, c)
    j.update({
        "id": m.id, "name": m.name, "kind": "flown", "site_name": m.site_name,
        "story": ("Reconstruction: the real TLI date and transit time, the near-polar orbit that needs the smallest "
                  "plane change for the real touchdown, landing at the real touchdown time."),
        "facts": {
            "launch_utc": m.launch_utc, "tli_utc": _utc(float(row["spec_tli_epoch"])),
            "loi_utc": _utc(arr.arrival_epoch), "real_loi_utc": m.loi_utc,
            "landing_utc": _utc(land), "real_landing_utc": m.landing_utc,
            "tof_days": round(float(row["tof_days"]), 3), "lunar_inc_deg": round(arr.inc_deg, 2),
            "family": int(row["spec_family"]),
            "tli_dv_ms": round(float(row["tli_dv_ms"]), 1), "loi_dv_ms": round(arr.loi_ms, 1),
            "real_loi_dv_ms": m.loi_dv_ms,
            "wait_days": round((land - arr.arrival_epoch) / DAY, 2),
            "plane_change_deg": round(pc_deg, 3), "plane_change_ms": round(pc_ms, 1),
            "landable_by_rules": landable,
        },
        "sources": [list(s) for s in m.sources],
    })
    return j


def forecast(tag: str, spice: bool, window: int, fpath: Path | None = None, cpath: Path | None = None) -> dict | None:
    m = get_upcoming("griffin-1")
    fpath = fpath or DATA / "forecast.json"
    cpath = cpath or CACHE / f"forecast_{m.id}_{tag}.csv"
    if not fpath.exists() or not cpath.exists():
        print(f"  {fpath.name} or {cpath.name} missing: run scripts/build_forecast.py first; skipping Griffin-1")
        return None
    fc = json.loads(fpath.read_text())
    wins = fc["time"]["windows"]
    if not wins:
        print("  the forecast has no launch window")
        return None
    w = wins[min(window, len(wins)) - 1]
    day = w["best_tli_day"]
    rows = [parse_row(r) for r in read_rows(cpath) if str(r.get("converged")) == "True"
            and tdb_to_utc(float(r["spec_tli_epoch"])).date().isoformat() == day]
    c = forecast_constraints(m)
    site = m.site()
    cache = cached_for_window(spice, *_span(rows, c.max_wait_days + c.daylight_horizon_days + 3))
    arrivals = [arrival_from_row(r) for r in rows]
    a = np.array([x.arrival_epoch for x in arrivals])
    tl = SiteTimeline.build(cache, site, a.min() + c.min_coast_days * DAY - 3600,
                            a.max() + (c.max_wait_days + c.daylight_horizon_days + 1) * DAY, c)
    ok = []
    for row, arr in zip(rows, arrivals):
        res = analyze(arr, tl, c, cache.pole("MOON", arr.arrival_epoch))
        if res.feasible:
            ok.append((row, arr, res))
    if not ok:
        print(f"  no feasible transfer on {day}")
        return None
    row, arr, res = min(ok, key=lambda p: (p[2].total_from_loi_ms, p[2].landing_epoch))
    if res.landing_utc[:16] != w["best_landing_utc"][:16]:
        print(f"  note: landing {res.landing_utc} differs from the forecast's {w['best_landing_utc']}")
    j = build_journey(cache, TransferDesigner(cache, spec_from_row(row)), controls_from_row(row), arr, site,
                      _height_m(site), res.landing_epoch, c)
    j.update({
        "id": m.id, "name": m.name, "kind": "forecast", "site_name": m.reference_name,
        "story": (f"Forecast: the best launch of window {wins.index(w) + 1} ({w['first']} .. {w['last']}), "
                  "landing at the reference point when the registered forecast says. The real flight will differ."),
        "facts": {
            "tli_utc": _utc(float(row["spec_tli_epoch"])), "loi_utc": _utc(arr.arrival_epoch),
            "landing_utc": _utc(res.landing_epoch), "tof_days": round(float(row["tof_days"]), 3),
            "lunar_inc_deg": round(arr.inc_deg, 2), "family": int(row["spec_family"]),
            "tli_dv_ms": round(float(row["tli_dv_ms"]), 1), "loi_dv_ms": round(arr.loi_ms, 1),
            "wait_days": round(res.wait_days, 2), "plane_change_deg": round(res.plane_change_deg, 3),
            "plane_change_ms": round(res.plane_change_ms, 1), "daylight_days": round(res.daylight_days, 2),
            "forecast_sha256": fc["meta"]["sha256"], "window": wins.index(w) + 1,
        },
        "sources": [list(s) for s in m.sources],
    })
    return j


def polar_cap(dem_path: Path, block: int = 16) -> tuple[dict, bytes] | None:
    """The LOLA south polar map as block means (~2 km), for the Moon in the journey view."""
    if not dem_path.exists():
        return None
    with PolarGrid.load(dem_path) as g:
        n = g.lines // block
        raw = np.asarray(g.data[:n * block, :n * block], dtype=np.float64)
        dn = np.round(raw.reshape(n, block, n, block).mean(axis=(1, 3))).astype("<i2")
        s_km = g.map_scale_m / 1000.0
        off = (block - 1) / 2.0
        meta = {"file": "moon_cap.bin", "n": n, "step_km": block * s_km,
                "x0_km": (off - g.sample_offset) * s_km, "y0_km": (off - g.line_offset) * s_km,
                "scale_m": g.scale, "offset_m": g.offset - g.radius_m, "dem": g.name, "block": block}
    return meta, dn.tobytes()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true", help="DE440 ephemeris (recommended)")
    ap.add_argument("--window", type=int, default=1, help="forecast launch window for Griffin-1 (1-based)")
    ap.add_argument("--dem", default=str(DEM_PATH))
    ap.add_argument("--forecast", default=str(DATA / "forecast.json"))
    ap.add_argument("--forecast-csv", default=None, help="default: data/cache/forecast_griffin-1_<ephemeris>.csv")
    ap.add_argument("--out-dir", default=str(DATA))
    args = ap.parse_args()
    tic = time.perf_counter()
    tag = "spice" if args.spice else "analytic"
    out = []
    for m in MISSIONS:
        print(f"== {m.name}")
        j = flown(m, tag, args.spice)
        if j:
            out.append(j)
    print("== Griffin-1 (forecast)")
    j = forecast(tag, args.spice, args.window, Path(args.forecast),
                 Path(args.forecast_csv) if args.forecast_csv else None)
    if j:
        out.append(j)
    for j in out:
        f, o = j["facts"], j["orbit"]
        print(f"  {j['id']}: TLI {f['tli_utc']}, {f['tof_days']} d coast, LOI {f['loi_utc']}, {f['wait_days']} d in orbit, "
              f"plane change {f['plane_change_ms']} m/s, touchdown {f['landing_utc']}"
              f"{' (real ' + f['real_landing_utc'] + ')' if f.get('real_landing_utc') else ''}; "
              f"phase adjustment {o['phase_adjust_pct_of_motion']}% of the orbital motion; {len(j['t'])} samples")
    if not out:
        print("nothing to write")
        return 1
    od = Path(args.out_dir)
    od.mkdir(parents=True, exist_ok=True)
    cap = polar_cap(Path(args.dem))
    if cap:
        (od / "moon_cap.bin").write_bytes(cap[1])
    doc = {"meta": {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    "engine_version": __version__, "ephemeris": tag, "moon_cap": cap[0] if cap else None,
                    "notes": ["Paths are the engine's model of each mission, not the flown trajectories: real missions "
                              "made trajectory-correction and phasing burns that are not modelled.",
                              "Lunar orbit: circular, plane drifting with the J2 node regression (the landing "
                              "analysis's model); the phase along the orbit is adjusted so the spacecraft reaches the "
                              "site at the landing time (the analysis does not model phasing).",
                              "Descent: schematic (deorbit half-ellipse to 15 km, braking arc); its delta-v is the "
                              "analysis's, its path and timing are illustrative."]},
           "missions": out}
    (od / "journeys.json").write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
    size = (od / "journeys.json").stat().st_size / 1e6
    print(f"-> {od / 'journeys.json'} ({size:.1f} MB){' + moon_cap.bin' if cap else ''}, "
          f"{time.perf_counter() - tic:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())

