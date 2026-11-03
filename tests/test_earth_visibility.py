"""Earth visibility maps (engine/surface/earth_visibility.py): the geometry, the horizon lookup, and
pre-registered check A on a level sphere (analytic ephemeris here; the build script runs it with DE440)."""

from datetime import datetime, timezone

import numpy as np

from engine.core.time import utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.surface import earth_visibility as ev

T0 = utc_to_tdb(datetime.fromisoformat(ev.PERIOD_UTC[0]).replace(tzinfo=timezone.utc))
T1 = utc_to_tdb(datetime.fromisoformat(ev.PERIOD_UTC[1]).replace(tzinfo=timezone.utc))
CACHE = CachedEphemeris.build(AnalyticEphemeris(), T0 - 86400.0, T1 + 86400.0, 3600.0)
TS = np.arange(T0, T1, 6 * 3600.0)          # 6-hourly is enough for the geometry tests
SKY = ev.build_sky(CACHE, TS, -1.0)


def test_level_sphere_near_and_far_side():
    # Check A's near/far part. Its limb part needs the libration in longitude, which comes from the
    # Moon's eccentric orbit: the analytic ephemeris has a circular orbit (the sub-Earth longitude
    # moves only 0.14..0.61 deg), so the limbs are judged with DE440 only, by build_earth_visibility.py
    # and web/tests/earthvis.check.mjs.
    p = ev.check_a(SKY)["earth_in_view_pct"]
    assert p["near_centre"] == 100.0 and p["far_centre"] == 0.0, p


def test_horizon_lookup_linear_and_periodic():
    H = np.zeros((1, 360))
    H[0, 359], H[0, 0], H[0, 1] = 2.0, 4.0, 6.0
    az = np.array([[0.0, 0.5, 359.5, 360.0, 720.25]])
    np.testing.assert_allclose(ev.horizon_at(H, az), [[4.0, 5.0, 3.0, 4.0, 4.5]])


def test_a_wall_hides_the_earth_and_a_trench_shows_it():
    lat, lon = np.array([-89.0, -89.0, -89.0]), np.array([0.0, 0.0, 0.0])
    H = np.stack([np.full(360, -5.0), np.zeros(360), np.full(360, 30.0)])
    s = ev.shares(lat, lon, H, SKY)
    flat = ev.shares(lat, lon, None, SKY)
    assert s["earth"][2] == 0.0 and s["sun_earth"][2] == 0.0 and s["dsn"][2] == 0.0
    assert s["earth"][1] == flat["earth"][1]
    assert s["earth"][0] >= s["earth"][1]
    assert np.all(s["sun_earth"] <= s["earth"]) and np.all(s["dsn"] <= s["earth"])


def test_parallax_matches_the_browser_rule():
    # the Earth seen from the site, not from the Moon's centre: near the limb this lowers it by up to ~0.26 deg
    up, north, east = ev.site_frames(np.array([0.0]), np.array([90.0]))
    e = SKY.earth_fixed_km[None, :, :]
    _, el_site = ev.az_el(e - ev.MOON_R_KM * up[:, None, :], up, north, east)
    _, el_centre = ev.az_el(e, up, north, east)
    d = el_centre - el_site
    assert 0.0 < float(d.max()) < 0.3


def test_grid_interpolation_reweights_missing_nodes():
    H = np.zeros((2, 2, 4))
    H[0, 0] = 1.0
    H[0, 1] = 3.0
    H[1, 0] = np.nan
    H[1, 1] = 5.0
    h = ev.interp_grid(H, 0.0, 5.0, 2.5, 2.5)             # centre: three nodes, equal weights
    np.testing.assert_allclose(h, np.full(4, 3.0))
    assert ev.interp_grid(np.full((2, 2, 4), np.nan), 0.0, 5.0, 2.5, 2.5) is None


def test_check_b_judgement():
    good = ev.judge_b(np.r_[np.full(80, 1.0), np.full(20, 12.0)], np.full(100, 10.0))
    assert good["pass"] and good["median_pp"] == 1.0
    assert not ev.judge_b(np.full(100, 6.0), np.full(100, 20.0))["pass"]          # median over 5
    assert not ev.judge_b(np.r_[np.full(85, 1.0), np.full(15, 20.0)], np.full(100, 10.0))["pass"]   # p90 over 15
    assert not ev.judge_b(np.full(100, 2.0), np.full(100, 1.0))["pass"]           # no better than flat


def test_neighbour_spread_and_check_c_judgement():
    E = np.array([[0.0, 10.0], [np.nan, 40.0]])
    assert ev.neighbour_spread(E, 0.0, 5.0, 2.5, 2.5) == 40.0          # three grid points: 0, 10, 40
    assert np.isnan(ev.neighbour_spread(np.full((2, 2), np.nan), 0.0, 5.0, 2.5, 2.5))
    d = np.r_[np.full(80, 1.0), np.full(20, 40.0)]
    c = ev.judge_c(d, np.r_[np.zeros(80, bool), np.ones(20, bool)])          # flags catch every large error
    assert c["pass"] and c["unflagged_p90_pp"] == 1.0 and c["large_errors_flagged"] == 20
    assert not ev.judge_c(d, np.zeros(100, bool))["pass"]                    # nothing flagged: tail remains
    assert not ev.judge_c(d, np.r_[np.zeros(60, bool), np.ones(40, bool)])["pass"]   # 40% flagged: too many
