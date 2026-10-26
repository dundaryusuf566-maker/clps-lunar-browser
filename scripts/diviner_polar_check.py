"""Polar temperatures: our regolith model against what Diviner measured near the south pole.

    python scripts/diviner_polar_check.py --spice            (~5-10 minutes; resumes if interrupted)

Diviner's polar cumulative products (Williams et al. 2019) give, for every 240 m
bin poleward of 80 S, the mean bolometric brightness temperature measured between
July 2009 and February 2019, by local time (96 bins of 0.25 h) and season (summer:
Sun south of the equator; winter: north). This script

1. reads, for each point, the bin it falls in from every 4th local-time file of
   both seasons (48 files; only the needed records, by HTTP range requests, see
   engine/validation/diviner_pcp.py), caching what it read in data/cache;
2. runs the regolith model at the same points over the same years (hourly, DE440,
   LOLA horizon and slope, one year of spin-up), and averages it the way the bins
   were made (same local time and season; radiance-weighted, T = <T^4>^(1/4));
3. compares them.

Pass criterion, fixed before any Diviner value was read: the median absolute
difference over all points, seasons and local-time bins is at most 10 K.

Points: the forecast's reference point and top candidates (web/public/data/forecast.json)
and IM-1's touchdown at Malapert A. Writes web/public/data/diviner_polar.json.
"""

from __future__ import annotations

import argparse
import http.client
import json
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from build_thermal import forcing  # noqa: E402

from engine import __version__  # noqa: E402
from engine.core.constants import AU_KM  # noqa: E402
from engine.core.time import utc_to_tdb  # noqa: E402
from engine.ephemeris.factory import cached_for_window  # noqa: E402
from engine.forecast import get_upcoming  # noqa: E402
from engine.surface.terrain import PolarGrid  # noqa: E402
from engine.surface.thermal import HAYNE2017, Column, Regolith  # noqa: E402
from engine.validation.diviner_pcp import PCP_ROOT, WILLIAMS2019, HttpRange, Rows, detect_layout, find_bin, ltim_url  # noqa: E402
from engine.validation.missions import IM1  # noqa: E402

DEM_PATH = ROOT / "data" / "terrain" / "ldem_75s_120m.img"
DATA = ROOT / "web" / "public" / "data"
CACHE = ROOT / "data" / "cache" / "diviner_pcp_points.json"
DAY = 86_400.0
SPAN = ("2009-07-05", "2019-02-17")         # the PCP's observation span
CRITERION_K = 10.0                          # median |model - Diviner|, fixed before reading Diviner
NIGHT_K = 120.0                             # bins colder than this (Diviner) count as night in the summary


def _epoch(day: str) -> float:
    return utc_to_tdb(datetime.fromisoformat(day).replace(tzinfo=timezone.utc))


def points(forecast_path: Path, top: int) -> list[dict]:
    m = get_upcoming("griffin-1")
    out = [{"key": "ref", "label": m.reference_name, "lat": m.reference_lat, "lon": m.reference_lon}]
    if forecast_path.exists():
        reg = json.loads(forecast_path.read_text()).get("region") or {}
        for k, p in enumerate((reg.get("top") or [])[:top], 1):
            out.append({"key": str(k), "label": f"Candidate {k}", "lat": p["lat"], "lon": p["lon"]})
    out.append({"key": "im1", "label": f"IM-1 touchdown, {IM1.site_name}", "lat": IM1.lat_deg, "lon": IM1.lon_deg})
    return [p for p in out if p["lat"] <= -80.0]


def fetch_diviner(pts: list[dict], bins: list[int], workers: int) -> tuple[dict, dict]:
    """Diviner temperature of every point in every file. One job per file (its points share the reads);
    progress is cached after every file, so an interrupted run continues where it stopped."""
    cache = json.loads(CACHE.read_text()) if CACHE.exists() else {}
    key = lambda p: f"{p['lat']:.5f},{p['lon']:.5f}"            # noqa: E731
    files = [(s, b, ltim_url(s, b)) for s in ("sum", "win") for b in bins]
    todo = [u for _, _, u in files if any(key(p) not in cache.get(u, {}) for p in pts)]
    info = {"requests": 0, "layout": cache.get("_layout"), "failed": []}
    if todo:
        first = HttpRange(todo[0])
        try:
            lay = detect_layout(first, first.size())
        except (OSError, http.client.HTTPException) as e:
            print(f"  could not reach the archive ({type(e).__name__}: {e})")
            info["failed"] = todo
            return {}, info
        finally:
            first.close()
        info["layout"] = cache["_layout"] = lay.name
        info["requests"] += first.requests
        print(f"  table layout: sorted by {'xy'[lay.primary]}, x/y = {lay.name}")
        print(f"  {len(todo)} files to read, {workers} at a time")
        lock = threading.Lock()

        def one(url):
            h = HttpRange(url)
            try:
                n = h.size() // lay.record - 1
                rows = Rows(h, lay.record)
                got = {}
                for p in pts:
                    if key(p) not in cache.get(url, {}):
                        hit = find_bin(h, n, lay, p["lat"], p["lon"], rows=rows)
                        got[key(p)] = None if hit is None else list(hit)
                return url, got, h.requests, None
            except Exception as e:                           # noqa: BLE001 - reported, the run goes on
                return url, None, h.requests, f"{type(e).__name__}: {e}"
            finally:
                h.close()

        done = 0
        with ThreadPoolExecutor(workers) as ex:
            for url, got, nreq, err in ex.map(one, todo):
                done += 1
                info["requests"] += nreq
                with lock:
                    if err is None:
                        cache.setdefault(url, {}).update(got)
                    else:
                        info["failed"].append(url)
                        print(f"  could not read {url.rsplit('/', 1)[-1]}: {err}", flush=True)
                    CACHE.parent.mkdir(parents=True, exist_ok=True)
                    CACHE.write_text(json.dumps(cache))
                print(f"  {done}/{len(todo)} files ({info['requests']} range requests)", flush=True)
    out = {}
    for s, b, u in files:
        for p in pts:
            v = cache.get(u, {}).get(key(p))
            out[(p["key"], s, b)] = None if v is None else v[0]
    return out, info


def model(pts: list[dict], spice: bool, dem_path: Path, bins: list[int]) -> dict:
    r = Regolith()
    s0, s1 = _epoch(SPAN[0]), _epoch(SPAN[1])
    spin0 = s0 - 365.0 * DAY
    cache = cached_for_window(spice, spin0 - DAY, s1 + DAY, step=3600.0)
    ts = np.arange(spin0, s1, 3600.0)
    rot = cache.rotation_many("MOON", ts)
    sun = np.einsum("nij,nj->ni", rot, cache.position_many("SUN", "MOON", ts))
    au = np.linalg.norm(sun, axis=1) / AU_KM
    sun /= np.linalg.norm(sun, axis=1, keepdims=True)
    dem = PolarGrid.load(dem_path)
    F = np.array([forcing(dem, p["lat"], p["lon"], sun, au, r)["F"] for p in pts])
    dem.close()
    spin = ts < s0
    col = Column(len(pts), r)
    col.spin_up(ts[spin], F[:, spin], cycles=4)
    keep = np.flatnonzero(~spin)
    keep = np.concatenate([[keep[0] - 1], keep])
    T = col.run(ts[keep], F[:, keep])["surface"][:, 1:]
    s = sun[keep[1:]]
    lon_ss = np.degrees(np.arctan2(s[:, 1], s[:, 0]))
    summer = s[:, 2] < 0                                   # Sun south of the equator: southern summer
    out = {}
    for k, p in enumerate(pts):
        lt = (12.0 + (p["lon"] - lon_ss) / 15.0) % 24.0
        num = np.floor(lt / 0.25).astype(int) + 1
        for season, sel in (("sum", summer), ("win", ~summer)):
            for b in bins:
                m = sel & (num == b)
                out[(p["key"], season, b)] = float(np.mean(T[k, m] ** 4) ** 0.25) if m.any() else None
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--dem", default=str(DEM_PATH))
    ap.add_argument("--forecast", default=str(DATA / "forecast.json"))
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--every", type=int, default=4, help="use every Nth of the 96 local-time bins")
    ap.add_argument("--workers", type=int, default=4, help="files read in parallel (be gentle with the archive)")
    ap.add_argument("--out", default=str(DATA / "diviner_polar.json"))
    args = ap.parse_args()
    tic = time.perf_counter()
    pts = points(Path(args.forecast), args.top)
    bins = list(range(1, 97, args.every))
    print(f"{len(pts)} points, {len(bins)} local-time bins x 2 seasons")

    print("Reading Diviner (PDS Geosciences, polar cumulative products):")
    div, info = fetch_diviner(pts, bins, args.workers)
    if info["failed"]:
        print(f"\n{len(info['failed'])} of {2 * len(bins)} files could not be read (network). What was read is saved in "
              f"{CACHE}; run the same command again to read the rest (try --workers 2 if it keeps failing).")
        return 2
    print(f"  done ({time.perf_counter() - tic:.0f} s)")
    print(f"Regolith model, {SPAN[0]} .. {SPAN[1]} hourly:")
    mod = model(pts, args.spice, Path(args.dem), bins)
    print(f"  done ({time.perf_counter() - tic:.0f} s)")

    rows, diffs, day, night = [], [], [], []
    for p in pts:
        prow = {**p, "seasons": {}}
        pd = []
        for season in ("sum", "win"):
            series = []
            for b in bins:
                d, m = div.get((p["key"], season, b)), mod.get((p["key"], season, b))
                series.append([round((b - 1) * 0.25, 2), None if d is None else round(d, 1), None if m is None else round(m, 1)])
                if d is not None and m is not None:
                    pd.append(m - d)
                    (night if d < NIGHT_K else day).append(m - d)
            prow["seasons"][season] = series
        diffs += pd
        prow["n"] = len(pd)
        prow["median_abs_k"] = round(float(np.median(np.abs(pd))), 1) if pd else None
        prow["bias_k"] = round(float(np.mean(pd)), 1) if pd else None
        rows.append(prow)
        print(f"  {p['label'][:40]:<40} n {len(pd):3d}  median |d| {prow['median_abs_k']} K  bias {prow['bias_k']} K")
    med = float(np.median(np.abs(diffs))) if diffs else None
    summary = {
        "n": len(diffs), "median_abs_k": None if med is None else round(med, 2),
        "p90_abs_k": round(float(np.percentile(np.abs(diffs), 90)), 1) if diffs else None,
        "bias_day_k": round(float(np.mean(day)), 1) if day else None, "n_day": len(day),
        "bias_night_k": round(float(np.mean(night)), 1) if night else None, "n_night": len(night),
        "criterion_k": CRITERION_K, "pass": med is not None and med <= CRITERION_K,
    }
    print(f"\nAll: median |model - Diviner| {summary['median_abs_k']} K over {summary['n']} bins "
          f"(day bias {summary['bias_day_k']} K, night bias {summary['bias_night_k']} K): "
          f"{'PASS' if summary['pass'] else 'FAIL'} (criterion {CRITERION_K:g} K, fixed beforehand)")
    doc = {
        "meta": {"generated_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"), "engine_version": __version__,
                 "ephemeris": "spice" if args.spice else "analytic", "dem": Path(args.dem).stem.upper(),
                 "span_utc": list(SPAN), "bins": bins, "night_below_k": NIGHT_K, "layout": info["layout"],
                 "range_requests": info["requests"], "diviner_source": WILLIAMS2019, "diviner_archive": PCP_ROOT,
                 "model_source": HAYNE2017,
                 "notes": ["Diviner: mean bolometric brightness temperature of the 240 m bin, all nadir observations "
                           "July 2009 - February 2019, by local time and season (Williams et al. 2019).",
                           "Model: Hayne et al. (2017) regolith with the engine's Sun, the LOLA horizon (0.5 deg, 250 km) "
                           "and slope, averaged over the same local time and season, radiance-weighted.",
                           "Not in the model: roughness below the 240 m map (it makes sunlit and shadowed patches inside "
                           "a bin, which raises the bolometric temperature at low Sun) and light and heat from terrain "
                           "(under 2 K at these points, see the forecast)."]},
        "summary": summary,
        "points": rows,
    }
    Path(args.out).write_text(json.dumps(doc, separators=(",", ":"), allow_nan=False))
    print(f"-> {args.out} ({time.perf_counter() - tic:.0f} s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
