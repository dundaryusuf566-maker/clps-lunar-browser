"""The Moon's sky for the website: Sun and Earth seen from the Moon, hourly, 2024-2028.

    python scripts/build_ephemeris_table.py --spice           (~1 minute)

The site has no Python behind it, so the browser cannot ask the engine where the
Sun is. This script writes what it needs to answer that itself, for any point on
the Moon and any hour of 2024-2028:

    web/public/data/ephem_moon.bin    float32, little-endian, per hour (11 values):
                                      Sun direction in the Moon-fixed frame (unit x, y, z) and
                                      its distance (AU); Earth from the Moon's centre in the
                                      Moon-fixed frame (km, x, y, z); the J2000 -> Moon-fixed
                                      rotation as a quaternion (x, y, z, w), for the DSN.
    web/public/data/ephem_moon.json   epochs, layout, source.
    web/tests/ephem_reference.json    the engine's own answers (Sun and Earth azimuth and
                                      elevation, DSN stations in view) at fixed points and
                                      times, for web/tests/sky.check.mjs: the browser's
                                      results must match them.

Moon-fixed frame: IAU (the engine's lunar orientation; see engine/ephemeris).
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

from engine import __version__  # noqa: E402
from engine.core.constants import AU_KM  # noqa: E402
from engine.core.time import tdb_to_utc, utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.mission.journey import quat_from_matrix  # noqa: E402
from engine.surface.geometry import earth_az_el_deg, local_frame, sun_az_el_deg  # noqa: E402
from engine.surface.ground import dsn_mask, site_from_earth_km  # noqa: E402
from engine.surface.sites import MOON_MEAN_RADIUS_KM, LandingSite  # noqa: E402

DATA = ROOT / "web" / "public" / "data"
REF = ROOT / "web" / "tests" / "ephem_reference.json"
SPAN = ("2024-01-01", "2029-01-01")
STEP = 3600.0
LAYOUT = ["sun_x", "sun_y", "sun_z", "sun_au", "earth_x_km", "earth_y_km", "earth_z_km", "q_x", "q_y", "q_z", "q_w"]

# reference points: poles, the CLPS sites, the near side's centre, the far side, the limb
REF_SITES = [
    ("south-pole", -89.9, 0.0), ("mons-mouton", -84.79, 29.20), ("malapert-a", -80.13, 1.44),
    ("mare-crisium", 18.56, 61.81), ("reiner-gamma", 7.5, -59.0), ("sub-earth", 0.0, 0.0),
    ("far-side", 10.0, 180.0), ("east-limb", 0.0, 90.0), ("north-pole", 89.5, 45.0),
]


def _epoch(day: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(day).replace(tzinfo=timezone.utc))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true", help="JPL DE440 (recommended)")
    ap.add_argument("--start", default=SPAN[0])
    ap.add_argument("--end", default=SPAN[1])
    ap.add_argument("--out", default=str(DATA))
    ap.add_argument("--ref", default=str(REF))
    args = ap.parse_args()
    tic = time.perf_counter()
    t0, t1 = _epoch(args.start), _epoch(args.end)
    cache = cached_for_window(args.spice, t0 - 2 * STEP, t1 + 2 * STEP, step=STEP)
    ts = np.arange(t0, t1 + 0.5 * STEP, STEP)
    rot = cache.rotation_many("MOON", ts)                                   # J2000 -> Moon-fixed
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    earth = np.einsum("nij,nj->ni", rot, cache.position_many("EARTH", "MOON", ts))
    au = np.linalg.norm(sun, axis=1)
    q = quat_from_matrix(rot)
    table = np.column_stack([sun / au[:, None], au / AU_KM, earth, q]).astype("<f4")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "ephem_moon.bin").write_bytes(table.tobytes())
    meta = {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
            "ephemeris": "JPL DE440" if args.spice else "analytic (demo)", "frame": "IAU Moon-fixed",
            "t0_tdb": float(ts[0]), "step_s": STEP, "n": int(len(ts)), "layout": LAYOUT, "dtype": "float32 little-endian",
            "span_utc": [tdb_to_utc(float(ts[0])).isoformat(timespec="minutes"),
                         tdb_to_utc(float(ts[-1])).isoformat(timespec="minutes")],
            "moon_radius_km": MOON_MEAN_RADIUS_KM, "time": "TDB seconds past J2000; UTC -> TDB as engine/core/time.py"}
    (out / "ephem_moon.json").write_text(json.dumps(meta, indent=1))
    print(f"{len(ts)} hours, {table.nbytes / 1e6:.2f} MB -> {out / 'ephem_moon.bin'}")

    # the engine's own answers at fixed points and times (between the table's nodes on purpose)
    rng = np.random.default_rng(7)
    epochs = np.sort(rng.uniform(t0 + 3 * STEP, t1 - 3 * STEP, 60))
    refs = []
    for sid, lat, lon in REF_SITES:
        site = LandingSite(sid, sid, lat, lon, "", "", "reference point")
        frame = local_frame(cache, site, epochs)
        saz, sel = sun_az_el_deg(cache, site, epochs, frame)
        eaz, eel = earth_az_el_deg(cache, site, epochs, frame)
        dsn = dsn_mask(epochs, site_from_earth_km(cache, epochs, frame[0], MOON_MEAN_RADIUS_KM))
        refs.append({"id": sid, "lat": lat, "lon": lon,
                     "sun_az": np.round(saz, 5).tolist(), "sun_el": np.round(sel, 5).tolist(),
                     "earth_az": np.round(eaz, 5).tolist(), "earth_el": np.round(eel, 5).tolist(),
                     "dsn": dsn.astype(int).tolist()})
    ref = {"meta": {"generated_utc": meta["generated_utc"], "ephemeris": meta["ephemeris"], "engine_version": __version__,
                    "note": "engine results for web/tests/sky.check.mjs; regenerate together with ephem_moon.bin"},
           "utc": [tdb_to_utc(float(e)).isoformat(timespec="milliseconds").replace("+00:00", "Z") for e in epochs],
           "tdb": epochs.tolist(), "sites": refs}
    Path(args.ref).parent.mkdir(parents=True, exist_ok=True)
    Path(args.ref).write_text(json.dumps(ref))
    print(f"reference: {len(REF_SITES)} points x {len(epochs)} epochs -> {args.ref} ({time.perf_counter() - tic:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
