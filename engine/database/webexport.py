"""Turn a sweep CSV into the static files the web UI reads.

    web/public/data/transfers.json          one entry per converged transfer
    web/public/data/landings.json           landing analysis per (site, transfer) + Sun series
    web/public/data/trajectories/<id>.json  paths for the 3D view

The same building blocks (table_entry, trajectory_payload, landing_entry) are
used by the API server for transfers designed live.
"""

from __future__ import annotations

import csv
import json
import math
import time
from dataclasses import fields as dc_fields
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from ..core.constants import BODIES
from ..ephemeris.cached import CachedEphemeris
from ..mission.transfer import CONTROL_KEYS, TransferDesigner, TransferSpec
from ..propagators import propagate
from ..surface import SITES, LandingConstraints, LandingResult, analysis_window, analyze_many, arrival_from_row
from ..surface.terrain import load_horizon

MOON = BODIES["MOON"]
DAY = 86_400.0
_SPEC_FIELDS = {f.name for f in dc_fields(TransferSpec)}
SPEC_DEFAULTS = {f.name: f.default for f in dc_fields(TransferSpec) if f.name not in ("tli_epoch", "tof_days")}


# --- helpers ---------------------------------------------------------------------
def _parse(value):
    if not isinstance(value, str):
        return value
    if value in ("", "None"):
        return None
    if value in ("True", "False"):
        return value == "True"
    try:
        f = float(value)
    except ValueError:
        return value
    return int(f) if f.is_integer() and "." not in value and "e" not in value.lower() else f


def parse_row(row: dict) -> dict:
    return {k: _parse(v) for k, v in row.items()}


def num(x, digits: int):
    """Rounded float, or None for missing / NaN (JSON has no NaN)."""
    if x is None:
        return None
    x = float(x)
    return None if not math.isfinite(x) else round(x, digits)


def dump(obj, path: Path) -> None:
    path.write_text(json.dumps(obj, separators=(",", ":"), allow_nan=False))


def transfer_id(row: dict) -> str:
    fam = "p" if int(row["spec_family"]) > 0 else "m"
    stamp = str(row["tli_utc"])[:16].replace("-", "").replace(":", "")
    return f"{stamp}_t{float(row['spec_tof_days']):05.2f}_{fam}".replace(".", "")


def spec_from_row(row: dict) -> TransferSpec:
    kw = {k[5:]: v for k, v in row.items() if k.startswith("spec_") and k[5:] in _SPEC_FIELDS}
    for key in ("family", "plane_branch"):
        kw[key] = int(kw[key])
    return TransferSpec(**kw)


def controls_from_row(row: dict) -> dict:
    return {k: float(row[k]) for k in CONTROL_KEYS}


# --- per-transfer payloads -----------------------------------------------------------
def table_entry(row: dict, tid: str | None = None) -> dict:
    """Compact record for transfers.json (row: parsed CSV row or to_row() dict)."""
    return {
        "id": tid or transfer_id(row),
        "tli_utc": row["tli_utc"],
        "tli_epoch": num(row["spec_tli_epoch"], 3),
        "tof_days": num(row["spec_tof_days"], 4),
        "tof_actual_days": num(row["tof_days"], 5),
        "family": int(row["spec_family"]),
        "lunar_inc_deg": num(row["spec_lunar_inc_deg"], 3),
        "target_alt_km": num(row["spec_periselene_alt_km"], 3),
        "periselene_alt_km": num(row["periselene_alt_km"], 3),
        "loi_dv_ms": num(row["loi_dv_ms"], 2),
        "tli_dv_ms": num(row["tli_dv_ms"], 2),
        "total_dv_ms": num(row["total_dv_ms"], 2),
        "c3_km2s2": num(row["c3_km2s2"], 4),
        "v_inf_kms": num(row["v_inf_kms"], 4),
        "raan_moon_sun_deg": num(row["raan_moon_sun_deg"], 2),
        "periselene_lat_deg": num(row["periselene_lat_deg"], 2),
        "periselene_lon_deg": num(row.get("periselene_lon_deg"), 2),
        "parking_inc_deg": num(row["parking_inc_deg"], 3),
        "parking_raan_deg": num(row["parking_raan_deg"], 3),
        "controls": [float(row[k]) for k in CONTROL_KEYS],
        "has_trajectory": False,
    }


def _r(arr, digits):
    return np.round(np.asarray(arr, float), digits).tolist()


def trajectory_payload(designer: TransferDesigner, controls: dict, eph) -> dict:
    """Paths for the 3D view, re-propagated from the solved controls."""
    ev = designer.simulate_stage_b(controls)
    earth_seg, moon_seg = ev.segments["earth"], ev.segments["moon"]
    t_tli = designer.spec.tli_epoch

    dur_e = earth_seg.epochs[-1] - earth_seg.epochs[0]
    dense_e = propagate(designer.earth_dyn, earth_seg.initial, dur_e, rtol=1e-12, atol=1e-9)
    t_e = earth_seg.epochs[0] + dur_e * np.linspace(0, 1, 240) ** 2       # crowd near TLI
    y_e = np.array([dense_e.state_at(t).r for t in t_e])
    dur_m = moon_seg.epochs[-1] - moon_seg.epochs[0]
    dense_m = propagate(designer.moon_dyn, moon_seg.initial, dur_m, rtol=1e-12, atol=1e-9)
    t_m = moon_seg.epochs[0] + dur_m * (1 - (1 - np.linspace(0, 1, 100)) ** 2)  # crowd near periselene
    y_m = np.array([dense_m.state_at(t).r for t in t_m])
    y_m_eci = y_m + np.array([eph.position("MOON", "EARTH", t) for t in t_m])

    peri = ev.final
    rp = np.linalg.norm(peri.r)
    spec = designer.spec
    ra = MOON.radius + (spec.apolune_alt_km if spec.apolune_alt_km is not None else spec.periselene_alt_km)
    v_cap = np.sqrt(MOON.gm * (2 / rp - 2 / (rp + ra)))
    captured = peri.with_delta_v((v_cap - np.linalg.norm(peri.v)) * peri.v / np.linalg.norm(peri.v))
    period = 2 * np.pi * np.sqrt((0.5 * (rp + ra)) ** 3 / MOON.gm)
    _, orbit_pts = propagate(designer.moon_dyn, captured, period).sample(120)

    t_arr = peri.epoch
    ring = np.array([eph.position("MOON", "EARTH", t) for t in t_arr + np.linspace(-14 * DAY, 14 * DAY, 90)])
    sun = eph.position("SUN", "EARTH", t_arr)
    return {
        "t": _r(np.concatenate([t_e, t_m[1:]]) - t_tli, 0),
        "sc_eci": _r(np.vstack([y_e, y_m_eci[1:]]), 0),
        "moon_tli": _r(eph.position("MOON", "EARTH", t_tli), 0),
        "moon_arrival": _r(eph.position("MOON", "EARTH", t_arr), 0),
        "approach_mci": _r(y_m, 1),
        "capture_mci": _r(orbit_pts[:, :3], 1),
        "moon_ring_eci": _r(ring, 0),
        "sun_dir": _r(sun / np.linalg.norm(sun), 5),
        "moon_pole": _r(eph.pole("MOON", t_arr), 6),
        "events": {"tli": 0.0, "soi": round(float(earth_seg.epochs[-1] - t_tli), 1),
                   "periselene": round(float(t_arr - t_tli), 1)},
        "radii": {"earth": BODIES["EARTH"].radius, "moon": MOON.radius},
    }


def landing_entry(res: LandingResult):
    """Compact landing result: list of numbers when feasible, [code, best] otherwise.
    Feasible: [wait_d, plane_ms, sun_deg, earth_deg, daylight_d, capped, sun_horizon_deg,
               dsn_bitmask, energy_pct, max_dark_gap_h]."""
    if res.feasible:
        return [num(res.wait_days, 3), num(res.plane_change_ms, 1), num(res.sun_elev_deg, 1),
                num(res.earth_elev_deg, 1), num(res.daylight_days, 2), int(res.daylight_capped),
                num(res.sun_horizon_deg, 1), int(res.dsn), num(res.energy_pct, 1), num(res.max_dark_gap_h, 1)]
    return [res.code, num(res.best_plane_change_ms, 0)]


def site_terrain(site, c: LandingConstraints) -> dict | None:
    """Horizon panorama of a site for the UI, or None (flat horizon)."""
    mask = load_horizon(site.horizon) if (c.use_terrain and site.horizon) else None
    if mask is None:
        return None
    return {"source": mask.source, "map_scale_m": mask.map_scale_m, "observer_m": mask.observer_m,
            "site_height_m": round(mask.site_height_m), "max_dist_km": mask.max_dist_km,
            "az_step_deg": float(mask.az_deg[1] - mask.az_deg[0]),
            "elev_deg": [round(float(v), 2) for v in mask.elev_deg],
            "dist_km": [round(float(v), 1) for v in mask.dist_km]}


def landing_meta(c: LandingConstraints, descent_ms: float) -> dict:
    sites = []
    for s in SITES:
        d = s.to_dict()
        d["terrain"] = site_terrain(s, c)
        sites.append(d)
    with_terrain = [d["name"] for d in sites if d["terrain"]]
    if with_terrain:
        src = sites[[d["terrain"] is not None for d in sites].index(True)]["terrain"]["source"]
        horizon_note = (f"Terrain horizon from LOLA {src} for {', '.join(with_terrain)} (observer 2 m, 250 km); "
                        "flat local horizon elsewhere.")
    else:
        horizon_note = "Flat local horizon (terrain shadowing not modelled)."
    return {
        "constraints": c.to_dict(),
        "descent_ms": num(descent_ms, 1),
        "sites": sites,
        "model_notes": [
            horizon_note,
            "Orbit plane drift: lunar J2 secular term only.",
            "Descent: deorbit to 15 km perilune, braking burn with 6 % losses, 60 m/s terminal margin.",
            f"Energy: share of the solar disc above the terrain over the first {c.energy_window_days:g} days on the surface.",
            "Ground stations: NASA DSN Goldstone, Madrid, Canberra, Moon above a 10 deg mask (our assumption).",
        ],
    }


# --- whole dataset ------------------------------------------------------------------
def pick_trajectories(entries: list[dict], mode: str) -> set[str]:
    if mode == "none":
        return set()
    if mode == "all":
        return {e["id"] for e in entries}
    if mode == "best":  # cheapest LOI per TLI date and family
        best: dict[tuple, dict] = {}
        for e in entries:
            key = (e["tli_utc"][:10], e["family"])
            if key not in best or e["loi_dv_ms"] < best[key]["loi_dv_ms"]:
                best[key] = e
        return {e["id"] for e in best.values()}
    raise ValueError(f"trajectories must be all, best or none (got {mode!r})")


def export_dataset(csv_path: str | Path, out_dir: str | Path, cache: CachedEphemeris,
                   trajectories: str = "all", constraints: LandingConstraints | None = None,
                   log=print) -> dict:
    c = constraints or LandingConstraints()
    with open(csv_path, newline="") as fh:
        rows = [parse_row(r) for r in csv.DictReader(fh) if r.get("converged") == "True"]
    if not rows:
        raise ValueError(f"No converged transfers in {csv_path}")
    out = Path(out_dir)
    traj_dir = out / "trajectories"
    traj_dir.mkdir(parents=True, exist_ok=True)
    tic = time.perf_counter()

    entries = [table_entry(r) for r in rows]
    order = sorted(range(len(rows)), key=lambda i: (entries[i]["tli_utc"], entries[i]["tof_days"], entries[i]["family"]))
    rows, entries = [rows[i] for i in order], [entries[i] for i in order]

    # Landing analysis for every site.
    arrivals = [arrival_from_row(r) for r in rows]
    results, timelines = analyze_many(cache, arrivals, SITES, c)
    landings = {
        "meta": landing_meta(c, results[SITES[0].id][0].descent_ms),
        "series": {sid: tl.sun_series(every=12) for sid, tl in timelines.items()},
        "results": {sid: {e["id"]: landing_entry(res) for e, res in zip(entries, lst)} for sid, lst in results.items()},
    }
    n_ok = {sid: sum(r.feasible for r in lst) for sid, lst in results.items()}
    log(f"  landing analysis: {len(rows)} transfers x {len(SITES)} sites ({time.perf_counter() - tic:.1f} s); "
        f"feasible: " + ", ".join(f"{k} {v}" for k, v in n_ok.items()))

    wanted = pick_trajectories(entries, trajectories)
    keep = {f"{tid}.json" for tid in wanted}
    for old in traj_dir.glob("*.json"):  # drop paths from earlier exports
        if old.name not in keep:
            old.unlink()
    for i, (row, e) in enumerate(zip(rows, entries), 1):
        if e["id"] not in wanted:
            continue
        designer = TransferDesigner(cache, spec_from_row(row))
        payload = trajectory_payload(designer, controls_from_row(row), cache)
        payload["id"] = e["id"]
        dump(payload, traj_dir / f"{e['id']}.json")
        e["has_trajectory"] = True
        if i % 100 == 0:
            log(f"  trajectories {i}/{len(rows)}")

    dates = [e["tli_utc"] for e in entries]
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "ephemeris": str(rows[0].get("ephemeris", cache.source)),
        "count": len(entries),
        "families": sorted({e["family"] for e in entries}),
        "first_tli_utc": min(dates), "last_tli_utc": max(dates),
        "capture_orbit": {"periselene_alt_km": rows[0]["spec_periselene_alt_km"],
                          "apolune_alt_km": rows[0]["spec_apolune_alt_km"],
                          "lunar_inc_deg": rows[0]["spec_lunar_inc_deg"]},
        "parking_orbit": {"alt_km": rows[0]["spec_parking_alt_km"], "min_inc_deg": rows[0]["spec_parking_inc_deg"]},
        "spec_defaults": {k: v for k, v in SPEC_DEFAULTS.items()},
        "control_keys": list(CONTROL_KEYS),
        "trajectories": trajectories,
        "source_csv": Path(csv_path).name,
    }
    dump({"meta": meta, "rows": entries}, out / "transfers.json")
    dump(landings, out / "landings.json")
    size = sum(p.stat().st_size for p in out.rglob("*.json")) / 1e6
    log(f"  {len(entries)} transfers, {len(wanted)} paths -> {out} ({size:.1f} MB, {time.perf_counter() - tic:.0f} s)")
    return meta


def export_window(csv_path: str | Path, c: LandingConstraints | None = None) -> tuple[float, float]:
    """Ephemeris span export_dataset needs for this CSV."""
    c = c or LandingConstraints()
    with open(csv_path, newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("converged") == "True"]
    if not rows:
        raise ValueError(f"No converged transfers in {csv_path}")
    tli = [float(r["spec_tli_epoch"]) for r in rows]
    arr = [float(r["arrival_epoch"]) for r in rows]
    a0, a1 = analysis_window(arr, c)
    return min(min(tli) - 16 * DAY, a0) - DAY, max(a1, max(arr) + 16 * DAY) + DAY
