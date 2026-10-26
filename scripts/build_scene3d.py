"""Build the 3D scene of the forecast region for the browser (web/public/data/scene3d.*).

    python scripts/build_scene3d.py --spice        # Griffin-1 region, DE440 Sun and Earth (~1-2 min)

Needs the LOLA map (scripts/download_terrain.py). Reads web/public/data/forecast.json,
if present, for the check points (the reference point and the top candidates).

Writes
    scene3d.json   metadata, offsets into the binary file, the engine's check values
    scene3d.bin    terrain heights (int16), hourly Sun / Earth directions (float32),
                   horizon masks and the engine's sun clearance at the check points (int16)

and prints how well the browser's shadow algorithm (run here in numpy) agrees with
the engine's full-resolution horizon masks. The page repeats the same comparison on
the GPU, with the code that draws the shadows.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402
from engine.core.time import tdb_to_utc, utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.forecast import get_upcoming  # noqa: E402
from engine.surface.scene3d import (  # noqa: E402
    MARCH, MOON_R_KM, RINGS, agreement, crop_rings, engine_sun_clear, enu_basis, march_sun_clear, unit,
)
from engine.surface.terrain import SOLAR_SEMI_DIAMETER_DEG, PolarGrid  # noqa: E402
from engine.validation.illumination import sun_directions_fixed  # noqa: E402

DEM_PATH = ROOT / "data" / "terrain" / "ldem_75s_120m.img"
DATA = ROOT / "web" / "public" / "data"
DAY = 86_400.0
CHECK_STRIDE_H = 3
OBSERVER_M = 2.0


def _epoch(day: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(day).replace(tzinfo=timezone.utc))


def check_points(m, forecast: dict | None, n_top: int) -> list[dict]:
    pts = [{"label": m.reference_name, "kind": "reference", "lat": m.reference_lat, "lon": m.reference_lon,
            "horizon": m.horizon}]
    if forecast and forecast.get("region"):
        for k, p in enumerate(forecast["region"].get("top", [])[:n_top], 1):
            pts.append({"label": f"Candidate {k}", "kind": "top", "rank": k, "lat": p["lat"], "lon": p["lon"]})
    else:
        pts.append({"label": "Region centre", "kind": "extra", "lat": m.region_center[0], "lon": m.region_center[1]})
    return pts


class Blob:
    """Sections of one little-endian binary file, each 4-byte aligned."""

    def __init__(self):
        self.parts: list[bytes] = []
        self.size = 0
        self.index: dict[str, dict] = {}

    def add(self, name: str, arr: np.ndarray) -> None:
        dt = {"int16": "<i2", "float32": "<f4"}[str(arr.dtype)]
        raw = np.ascontiguousarray(arr).astype(dt).tobytes()
        self.index[name] = {"offset": self.size, "dtype": str(arr.dtype), "shape": list(arr.shape)}
        pad = (-len(raw)) % 4
        self.parts.append(raw + b"\0" * pad)
        self.size += len(raw) + pad

    def bytes(self) -> bytes:
        return b"".join(self.parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mission", default="griffin-1")
    ap.add_argument("--spice", action="store_true", help="DE440 ephemeris (recommended)")
    ap.add_argument("--dem", default=str(DEM_PATH))
    ap.add_argument("--forecast", default=str(DATA / "forecast.json"))
    ap.add_argument("--top", type=int, default=10, help="top candidates to use as check points")
    ap.add_argument("--out-dir", default=str(DATA))
    args = ap.parse_args()
    tic = time.perf_counter()

    m = get_upcoming(args.mission)
    dem_path = Path(args.dem)
    if not dem_path.exists():
        print(f"{dem_path} missing: run scripts/download_terrain.py first")
        return 1
    fpath = Path(args.forecast)
    forecast = json.loads(fpath.read_text()) if fpath.exists() else None
    if forecast is None:
        print(f"note: {fpath} not found; check points are the reference point and the region centre only")
    tag = "spice" if args.spice else "analytic"

    dem = PolarGrid.load(dem_path)
    grids, (lc, sc) = crop_rings(dem, *m.region_center, inner_half_km=m.region_half_km + 1.0)
    inner = grids[0]
    c_lat, c_lon = (float(v) for v in dem.latlon(lc, sc))
    print("Terrain: " + ", ".join(f"{g.shape[1]}x{g.shape[0]} at {g.step_km * 1000:.0f} m "
                                  f"(+-{(g.shape[0] // 2) * g.step_km:.0f} km)" for g in grids)
          + f", centre {c_lat:.4f}, {c_lon:.4f}")
    h_in = inner.heights_km()
    if np.isnan(h_in).any():
        print("inner grid reaches past the map; choose a region inside the map")
        return 1

    # Sun and Earth, hourly, from the start of the landing period to one lunar day after its end.
    p0, p1 = _epoch(m.landing_first), _epoch(m.landing_last)
    start, end = p0 - DAY, p1 + 16 * DAY
    cache = cached_for_window(args.spice, start - DAY, end + DAY, step=3600.0)
    ts, sun = sun_directions_fixed(cache, start, end)
    rot = cache.rotation_many("MOON", ts)
    earth = np.einsum("nij,nj->ni", rot, cache.position_many("EARTH", "MOON", ts))
    C = unit(c_lat, c_lon) * MOON_R_KM
    e_rel = earth - C
    e_dist = np.linalg.norm(e_rel, axis=1)
    series = np.column_stack([sun, e_rel / e_dist[:, None], e_dist]).astype(np.float32)
    t0_utc = tdb_to_utc(float(ts[0]))

    # Check points: the engine's sun clearance from full-resolution masks vs the shader's march.
    k_check = np.flatnonzero((ts >= p0) & (ts <= p1))[::CHECK_STRIDE_H]
    pts = check_points(m, forecast, args.top)
    masks, eng, rows = [], [], []
    all_e, all_p = [], []
    for p in pts:
        try:
            ec, mask = engine_sun_clear(dem, p["lat"], p["lon"], sun[k_check], observer_m=OBSERVER_M)
            pc = march_sun_clear(grids, p["lat"], p["lon"], sun[k_check], observer_m=OBSERVER_M)
        except ValueError as exc:
            print(f"  skip {p['label']}: {exc}")
            continue
        a = agreement(pc, ec)
        rows.append({**p, "height_m": round(mask.site_height_m, 1), "python_vs_engine": a})
        masks.append(np.round(mask.elev_deg * 100))
        eng.append(np.round(np.clip(ec, -300, 300) * 100))
        all_e.append(ec)
        all_p.append(pc)
        print(f"  {p['label']:<40} median |d| {a['median_abs_deg']:.3f} deg, lit/hidden agree "
              f"{a['lit_agree_pct']}% of {a['lit_compared']}")
    dem.close()
    total = agreement(np.concatenate(all_p), np.concatenate(all_e))

    blob = Blob()
    for k, g in enumerate(grids):
        blob.add(f"grid{k}", g.dn)
    blob.add("series", series)
    blob.add("masks", np.array(masks, dtype=np.int16))
    blob.add("engine_clear", np.array(eng, dtype=np.int16))

    E = enu_basis(c_lat, c_lon)
    meta = {
        "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "engine_version": __version__, "ephemeris": tag, "dem": dem.name, "mission": m.name,
        "forecast_sha256": (forecast or {}).get("meta", {}).get("sha256"),
        "moon_radius_km": MOON_R_KM, "solar_semi_diameter_deg": SOLAR_SEMI_DIAMETER_DEG,
        "observer_m": OBSERVER_M, "march": MARCH,
        "frame": {"lat": c_lat, "lon": c_lon, "east": E[0].tolist(), "north": E[1].tolist(), "up": E[2].tolist(),
                  "note": "scene = east, north, up (km) from the reference sphere point below the region centre"},
        "region": {"center_lat": m.region_center[0], "center_lon": m.region_center[1],
                   "half_km": m.region_half_km, "step_km": m.region_step_km,
                   "landing_period_utc": [m.landing_first, m.landing_last]},
        "grids": [{**g.meta(), "block": b, "section": f"grid{k}"} for k, (g, (b, _)) in enumerate(zip(grids, RINGS))],
        "height_range_m": [float(np.nanmin(h_in) * 1000), float(np.nanmax(h_in) * 1000),
                           max(float(np.nanmax(g.heights_km())) * 1000 for g in grids)],
        "time": {"t0_utc": t0_utc.isoformat(timespec="seconds").replace("+00:00", "Z"), "step_s": 3600.0,
                 "n": len(ts), "series": "sun unit (3), earth unit from the region centre (3), earth distance km"},
        "checks": {"points": rows, "time_index": [int(k_check[0]), CHECK_STRIDE_H, len(k_check)],
                   "mask_az_step_deg": 0.5, "python_vs_engine": total,
                   "method": ("engine: full-resolution horizon mask (0.5 deg azimuth, 250 km, 120 m steps); "
                              "scene: the ray march the 3D view uses, on its 120 m, 360 m and 1.2 km grids")},
        "binary": {"file": "scene3d.bin", "sections": blob.index},
    }
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    (out / "scene3d.bin").write_bytes(blob.bytes())
    (out / "scene3d.json").write_text(json.dumps(meta, separators=(",", ":")))
    t_last = t0_utc + timedelta(hours=len(ts) - 1)
    print(f"\nShadow algorithm vs engine, {total['n']} point-hours: median |d| {total['median_abs_deg']} deg, "
          f"p95 {total['p95_abs_deg']} deg, lit/hidden agree {total['lit_agree_pct']}%, "
          f"solar disc {total['mean_abs_disc_pct']} pp")
    print(f"-> {out / 'scene3d.json'}, {out / 'scene3d.bin'} ({blob.size / 1e6:.1f} MB), "
          f"{t0_utc:%Y-%m-%d} .. {t_last:%Y-%m-%d}, {time.perf_counter() - tic:.0f} s")
    return 0


if __name__ == "__main__":
    sys.exit(main())
