"""Forecasts for upcoming missions: records, time forecast rules, region metrics, registration."""

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine.core.time import tdb_to_utc, utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.forecast import GRIFFIN1, UPCOMING, RegionGrid, forecast_constraints, forecast_jobs, slope_deg, slot_metrics
from engine.forecast.region import REGION_RULES, rank
from engine.surface import ArrivalState, LandingConstraints, SiteTimeline, analyze, custom_site
from engine.surface.terrain import HorizonMask
from engine.validation.illumination import sun_directions_fixed

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tests"))
from test_terrain import R, write_grid  # noqa: E402

DAY = 86_400.0
T0 = utc_to_tdb(datetime(2026, 11, 1, tzinfo=timezone.utc))


def test_upcoming_records_separate_facts_from_assumptions():
    for m in UPCOMING:
        assert m.announced and all(url.startswith("https://") for _, url in m.announced)
        assert m.assumptions and m.sources
        assert m.tli_first < m.tli_last and m.landing_first < m.landing_last
    c = forecast_constraints(GRIFFIN1)
    assert c.min_daylight_days == 5.0 and c.max_wait_days == 4.0      # retrodiction rules + announced 5 days
    jobs = forecast_jobs(GRIFFIN1, tofs=(5.0,), incs=(90.0,))
    assert len(jobs) == 120 and tdb_to_utc(jobs[0]["tli_epoch"]).strftime("%Y-%m-%d %H:%M") == "2026-11-01 00:00"


def test_min_daylight_requirement():
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 70 * DAY, 3600.0)
    site = custom_site(-84.79, 29.2, sun_min_deg=0.5, sun_max_deg=90.0)
    pole = cache.pole("MOON", T0 + 5 * DAY)
    arr = ArrivalState(T0 + 5 * DAY, pole, 100.0, 90.0, 820.0)   # orbit normal along the pole: never mind the plane
    base = LandingConstraints(max_wait_days=30.0, max_plane_change_ms=1e6)
    tl = SiteTimeline.build(cache, site, T0, T0 + 60 * DAY, base)
    free = analyze(arr, tl, base, pole)
    assert free.feasible
    left = tl.daylight_left_days()
    assert left.shape == tl.ts.shape and np.all(np.diff(left)[tl.sun_clear[:-1] > 0] <= 1e-9 + 1 / 144)
    need = LandingConstraints(max_wait_days=30.0, max_plane_change_ms=1e6, min_daylight_days=free.daylight_days + 0.5)
    tl2 = SiteTimeline.build(cache, site, T0, T0 + 60 * DAY, need)
    r = analyze(arr, tl2, need, pole)
    assert (not r.feasible and r.code == "daylight") or r.daylight_days >= need.min_daylight_days
    impossible = LandingConstraints(max_wait_days=30.0, max_plane_change_ms=1e6, min_daylight_days=40.0)
    assert analyze(arr, SiteTimeline.build(cache, site, T0, T0 + 60 * DAY, impossible), impossible, pole).code == "daylight"


def test_slot_metrics_rules():
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 70 * DAY, 3600.0)
    ts, sun = sun_directions_fixed(cache, T0 + DAY, T0 + 65 * DAY)
    rot = cache.rotation_many("MOON", ts)
    earth = np.einsum("nij,nj->ni", rot, cache.position_many("EARTH", "MOON", ts))
    az = np.arange(0, 360, 1.0)
    mk = lambda e: HorizonMask("x", -84.79, 29.2, az, np.full(360, e), np.ones(360), 2.0, 0.0, 1, 1, "T", 1)  # noqa: E731
    period = (T0 + 2 * DAY, T0 + 40 * DAY)
    flat = slot_metrics(mk(0.0), -84.79, 29.2, 1737.4, ts, sun, earth, period, 5.0)
    assert flat["best_daylight_days"] >= 5.0 and flat["slot_days"] > 0 and flat["opportunities"] >= 1
    longer = slot_metrics(mk(0.0), -84.79, 29.2, 1737.4, ts, sun, earth, period, 12.0)
    assert longer["slot_days"] <= flat["slot_days"]
    walled = slot_metrics(mk(1.0), -84.79, 29.2, 1737.4, ts, sun, earth, period, 5.0)
    assert walled["sunlit_pct"] < flat["sunlit_pct"]
    blind = slot_metrics(mk(30.0), -84.79, 29.2, 1737.4, ts, sun, earth, period, 5.0)
    assert blind["best_daylight_days"] is None and blind["slot_days"] == 0 and blind["sunlit_pct"] == 0
    # Energy is measured over its own window, not the 5-day slot rule: inside the slot rule the Sun is
    # up by construction (100 %, no gap); a window that reaches into the lunar night must show less.
    short = slot_metrics(mk(0.0), -84.79, 29.2, 1737.4, ts, sun, earth, period, 5.0,
                         {**REGION_RULES, "energy_window_days": 5.0})
    assert short["energy_pct"] >= 99.0 and short["max_dark_gap_h"] == 0
    long_ = slot_metrics(mk(0.0), -84.79, 29.2, 1737.4, ts, sun, earth, period, 5.0,
                         {**REGION_RULES, "energy_window_days": 25.0})
    assert long_["energy_pct"] < short["energy_pct"] and long_["max_dark_gap_h"] > 0
    assert REGION_RULES["energy_window_days"] == GRIFFIN1.energy_window_days == 14.0


def test_slope_and_region_grid():
    n, scale = 201, 120.0
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        x = (np.arange(n) - (n - 1) / 2) * scale
        heights = np.tile(x * np.tan(np.radians(5.0)), (n, 1))          # a 5 deg plane rising to the right
        with write_grid(Path(tmp), heights, scale) as g:
            lat, lon = g.latlon(100.0, 120.0)
            assert abs(slope_deg(g, float(lat), float(lon)) - 5.0) < 0.05
            pts = RegionGrid(float(lat), float(lon), 4.0, 2.0).points(g)
            assert len(pts) == 25 and {p["x_km"] for p in pts} == {-4.0, -2.0, 0.0, 2.0, 4.0}
            centre = [p for p in pts if p["x_km"] == 0 and p["y_km"] == 0][0]
            assert abs(centre["lat"] - float(lat)) < 1e-4 and abs(centre["lon"] - float(lon)) < 1e-3


def test_ranking_respects_limits():
    base = dict(i=0, j=0, x_km=0, y_km=0, lat=-85, lon=30, height_m=0, horizon_max_deg=0, horizon_mean_deg=0,
                opportunities=1, sunlit_pct=50, earth_when_lit_pct=80, best_daylight_capped=False, best_slot=None,
                first_slot=None, runs=[])
    pts = [dict(base, slope_deg=3, best_daylight_days=10, slot_days=5, earth_after_best_pct=90),
           dict(base, slope_deg=15, best_daylight_days=20, slot_days=9, earth_after_best_pct=90),  # too steep
           dict(base, slope_deg=2, best_daylight_days=18, slot_days=4, earth_after_best_pct=20),   # no Earth
           dict(base, slope_deg=4, best_daylight_days=12, slot_days=1, earth_after_best_pct=60),
           dict(base, slope_deg=1, best_daylight_days=None, slot_days=0, earth_after_best_pct=None)]
    top = rank(pts)
    assert [p["best_daylight_days"] for p in top] == [12, 10]


def test_registration_hash_verifies():
    content = {"mission": {"id": "x"}, "time": {"windows": [1.5, 2]}, "region": None}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    with tempfile.TemporaryDirectory() as tmp:
        f = Path(tmp) / "forecast.json"
        f.write_text(json.dumps({"meta": {"sha256": digest, "registered_utc": "2026-10-18T00:00:00+00:00",
                                          "engine_version": "t", "ephemeris": "t"}, **content}))
        ok = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_forecast.py"), str(f)], capture_output=True)
        assert ok.returncode == 0, ok.stdout
        d = json.loads(f.read_text())
        d["time"]["windows"][0] = 1.6                                       # tamper
        f.write_text(json.dumps(d))
        bad = subprocess.run([sys.executable, str(ROOT / "scripts" / "verify_forecast.py"), str(f)], capture_output=True)
        assert bad.returncode == 1
