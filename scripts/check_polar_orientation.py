"""Which way round is a LOLA polar map? Checked against named craters, not assumed.

    python scripts/check_polar_orientation.py --pole north           (~1 minute)
    python scripts/check_polar_orientation.py --pole south           (control: the convention already in use)

A polar stereographic map can be read four ways (x and y each one way or mirrored).
Read the wrong way, everything lands at the wrong longitude: the terrain stands in
the wrong directions around every point and the Sun is hidden at the wrong times.

How not to check it: NASA's average-illumination map (AVGVISIB). Averaged over 18.6
years the Sun goes round the sky evenly, so a mirrored or rotated map gives the same
average illumination everywhere; a synthetic test showed all four readings passing.
That comparison checks heights and the distance from the pole, not the orientation.

How this script checks it: six large craters per pole, at their IAU coordinates
(Gazetteer of Planetary Nomenclature, via the craters' Wikipedia articles), spread
around the pole so that no mirror or rotation maps the set onto itself. For each
reading the crater's depth at its official position is measured on the map: mean
height on the rim ring (0.9-1.15 radii) minus the floor (within 0.35 radii). Read the
right way every crater is a deep bowl; read wrongly, the "floor" lands somewhere else.
Criterion, fixed before the first run on real data: a reading passes if every crater
is at least 500 m deep; the answer is accepted only if exactly one reading passes.
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

from engine.surface.terrain import PolarGrid  # noqa: E402

TERRAIN = ROOT / "data" / "terrain"
DEMS = {"north": "ldem_75n_120m.img", "south": "ldem_75s_120m.img"}
READINGS = ((1.0, -1.0), (-1.0, -1.0), (1.0, 1.0), (-1.0, 1.0))
MIN_DEPTH_M = 500.0
# name, latitude, longitude (east), diameter km
CRATERS = {
    "north": [("Peary", 88.63, 24.4, 79.0), ("Byrd", 85.43, 10.07, 97.49), ("Hermite", 86.17, -93.32, 108.64),
              ("Rozhdestvenskiy", 85.2, -155.4, 177.0), ("Plaskett", 82.1, 174.3, 109.0), ("Hevesy", 83.1, 150.1, 49.5)],
    "south": [("Amundsen", -84.5, 82.8, 103.39), ("Cabeus", -84.9, -35.5, 100.58), ("Shoemaker", -88.1, 44.9, 50.9),
              ("Sverdrup", -88.5, -152.0, 35.0), ("Nobile", -85.28, 53.27, 79.27), ("Haworth", -86.9, -4.0, 51.4)],
}


def ring(lat: float, lon: float, r0_km: float, r1_km: float, radius_m: float, n_r: int = 6, n_az: int = 72):
    """Points between r0 and r1 km from (lat, lon) along great circles."""
    d = np.linspace(r0_km, r1_km, n_r)[None, :] * 1000.0 / radius_m
    a = np.radians(np.arange(n_az) * 360.0 / n_az)[:, None]
    p, l = np.radians(lat), np.radians(lon)
    p2 = np.arcsin(np.clip(np.sin(p) * np.cos(d) + np.cos(p) * np.sin(d) * np.cos(a), -1, 1))
    l2 = l + np.arctan2(np.sin(a) * np.sin(d) * np.cos(p), np.cos(d) - np.sin(p) * np.sin(p2))
    return np.degrees(p2).ravel(), np.degrees(l2).ravel()


def depth_m(dem: PolarGrid, lat: float, lon: float, diam_km: float) -> float:
    """Rim ring minus floor, metres, with the map read as dem.x_sign / dem.y_sign say."""
    r = diam_km / 2.0
    floor = dem.value(*ring(lat, lon, 0.0, 0.35 * r, dem.radius_m))
    rim = dem.value(*ring(lat, lon, 0.9 * r, 1.15 * r, dem.radius_m))
    if not (np.isfinite(floor).any() and np.isfinite(rim).any()):
        return float("nan")
    return float(np.nanmean(rim) - np.nanmean(floor))


def check(dem: PolarGrid, craters) -> list[dict]:
    used = (dem.x_sign, dem.y_sign)
    out = []
    for xs, ys in READINGS:
        dem.x_sign, dem.y_sign = xs, ys
        depths = [depth_m(dem, la, lo, dk) for _, la, lo, dk in craters]
        ok = all(np.isfinite(d) and d >= MIN_DEPTH_M for d in depths)
        out.append({"x_sign": xs, "y_sign": ys, "pass": ok, "depths": depths})
    dem.x_sign, dem.y_sign = used
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--pole", choices=("north", "south"), required=True)
    ap.add_argument("--dem")
    args = ap.parse_args()
    tic = time.perf_counter()
    dem = PolarGrid.load(args.dem or TERRAIN / DEMS[args.pole])
    used = (dem.x_sign, dem.y_sign)
    craters = CRATERS[args.pole]
    print(f"{dem.name}: depth of {len(craters)} named craters at their IAU positions, for each way of reading the map")
    print("  reading  " + "".join(f"{c[0][:13]:>15}" for c in craters))
    results = check(dem, craters)
    for r in results:
        tag = "  <- engine" if (r["x_sign"], r["y_sign"]) == used else ""
        print(f"  x{r['x_sign']:+.0f} y{r['y_sign']:+.0f}  " + "".join(f"{d:>14.0f}m" for d in r["depths"])
              + f"   {'PASS' if r['pass'] else 'fail'}{tag}")
    passing = [r for r in results if r["pass"]]
    if len(passing) == 1 and (passing[0]["x_sign"], passing[0]["y_sign"]) == used:
        verdict, code = f"confirmed: only the engine's reading (x{used[0]:+.0f}, y{used[1]:+.0f}) puts every crater where the IAU does", 0
    elif len(passing) == 1:
        p = passing[0]
        verdict, code = (f"the map reads as (x{p['x_sign']:+.0f}, y{p['y_sign']:+.0f}), not as the engine assumes "
                         f"(x{used[0]:+.0f}, y{used[1]:+.0f}): send this output; do not use this pole's terrain yet"), 3
    else:
        verdict, code = f"{len(passing)} readings pass: not decided; send this output", 2
    print(verdict)
    out = TERRAIN / f"_orientation_{args.pole}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({
        "dem": dem.name, "criterion_min_depth_m": MIN_DEPTH_M, "engine_reading": list(used),
        "craters": [{"name": c[0], "lat": c[1], "lon": c[2], "diameter_km": c[3]} for c in craters],
        "craters_source": "IAU Gazetteer of Planetary Nomenclature (via the craters' Wikipedia articles)",
        "readings": [{**{k: r[k] for k in ("x_sign", "y_sign", "pass")},
                      "depths_m": {c[0]: (None if not np.isfinite(d) else round(d)) for c, d in zip(craters, r["depths"])}}
                     for r in results],
        "verdict": verdict, "code": code, "generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }, indent=1)
    out.write_text(text)
    web = ROOT / "web" / "public" / "data" / f"orientation_{args.pole}.json"      # for the Validation page
    web.parent.mkdir(parents=True, exist_ok=True)
    web.write_text(text)
    print(f"-> {out}\n-> {web} ({time.perf_counter() - tic:.0f} s)")
    dem.close()
    return code


if __name__ == "__main__":
    sys.exit(main())
