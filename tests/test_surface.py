from datetime import datetime, timezone

import unittest

import numpy as np

from engine.core.time import utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris, iau_moon
from engine.surface import (
    SITES, ArrivalState, LandingConstraints, SiteTimeline, analyze, custom_site, descent_delta_v_ms,
    earth_elevation_deg, get_site, node_rate_rad_s, plane_change_ms, selenographic, site_inertial,
    sun_elevation_deg,
)

BASE = AnalyticEphemeris()
T0 = utc_to_tdb(datetime(2026, 1, 1, tzinfo=timezone.utc))
CACHE = CachedEphemeris.build(BASE, T0, T0 + 90 * 86_400.0)
DAY = 86_400.0


def test_iau_rotation_is_orthonormal_and_spins_sidereally():
    for t in (0.0, T0, T0 + 1e6):
        r = iau_moon.rotation(t)
        np.testing.assert_allclose(r @ r.T, np.eye(3), atol=1e-12)
        np.testing.assert_allclose(r[2], iau_moon.pole(t), atol=1e-12)
    a, b = iau_moon.rotation(T0), iau_moon.rotation(T0 + 27.321661 * DAY)
    assert np.degrees(np.arccos(np.clip(a[0] @ b[0], -1, 1))) < 0.2


def test_moon_keeps_one_face_to_earth():
    # Sub-Earth point stays within the optical libration (|lat|, |lon| < 8 deg).
    for t in np.linspace(T0, T0 + 60 * DAY, 13):
        lat, lon = selenographic(CACHE, -CACHE.position("MOON", "EARTH", t), t)
        assert abs(lat) < 8 and abs(lon) < 8


def test_cache_rotation_matches_base():
    err = CACHE.validate_against(BASE, n_samples=200)
    assert err["MOON_meridian"]["max_angle_err_deg"] < 1e-4
    t = T0 + 12345.6
    np.testing.assert_allclose(CACHE.rotation_many("MOON", [t])[0], CACHE.body_fixed_rotation("MOON", t), atol=1e-14)


def test_subsolar_and_sub_earth_points():
    t = T0 + 20 * DAY
    lat, lon = selenographic(CACHE, CACHE.position("SUN", "MOON", t), t)
    assert abs(sun_elevation_deg(CACHE, custom_site(lat, lon), [t])[0] - 90) < 1e-6
    assert abs(sun_elevation_deg(CACHE, custom_site(-lat, lon + 180), [t])[0] + 90) < 1e-6
    lat, lon = selenographic(CACHE, CACHE.position("EARTH", "MOON", t), t)
    assert earth_elevation_deg(CACHE, custom_site(lat, lon), [t])[0] > 89.9
    far = get_site("schrodinger")
    assert np.all(earth_elevation_deg(CACHE, far, np.linspace(T0, T0 + 60 * DAY, 500)) < 0)


def test_sunrise_repeats_every_synodic_month():
    site = get_site("apollo-11")
    ts = np.arange(T0, T0 + 88 * DAY, 600.0)
    el = sun_elevation_deg(CACHE, site, ts)
    rises = ts[1:][(el[:-1] < 0) & (el[1:] >= 0)]
    assert len(rises) >= 2
    period = np.diff(rises) / DAY
    assert np.all(np.abs(period - 29.53) < 0.6)


def test_delta_v_models():
    assert abs(float(plane_change_ms(1.0, 100.0)) - 28.5) < 0.2
    assert 1800 < descent_delta_v_ms(100.0, LandingConstraints()) < 1950
    assert abs(node_rate_rad_s(100.0, 90.0)) < 1e-15
    assert node_rate_rad_s(100.0, 60.0) < 0  # prograde orbit: node regresses


def _arrival_in_plane_of_site_at(t_land: float, site) -> ArrivalState:
    """Polar orbit whose plane contains the site at t_land (zero plane change there)."""
    up = site_inertial(CACHE, site, [t_land])[0]
    pole = CACHE.pole("MOON", t_land)
    h = np.cross(up, pole)  # normal to the meridian plane through the site: polar orbit
    return ArrivalState(t_land - 5 * DAY, h / np.linalg.norm(h), 100.0, 90.0, 820.0)


def test_landing_finds_the_planned_dawn_opportunity():
    site = get_site("apollo-11")
    c = LandingConstraints()
    tl = SiteTimeline.build(CACHE, site, T0, T0 + 85 * DAY, c)
    # first dawn inside the window: Sun crossing ~6 deg while rising
    i = int(np.nonzero((tl.sun_el > 6) & (np.gradient(tl.sun_el) > 0) & (tl.ts > T0 + 10 * DAY))[0][0])
    t_land = float(tl.ts[i])
    arr = _arrival_in_plane_of_site_at(t_land, site)
    res = analyze(arr, tl, c, CACHE.pole("MOON", t_land))
    assert res.feasible, res.reason
    assert res.plane_change_ms < 25          # aligned at t_land; earlier, still-cheap slots allowed
    assert site.sun_min_deg <= res.sun_elev_deg <= site.sun_max_deg
    assert abs(res.wait_days - 5) < 0.6
    assert 10 < res.daylight_days < 15.5      # a lunar day minus the morning already gone
    assert abs(res.total_from_loi_ms - (820 + res.plane_change_ms + res.descent_ms)) < 1e-6


def test_landing_reasons_when_infeasible():
    c = LandingConstraints(max_plane_change_ms=5.0)
    site = get_site("mare-crisium")
    tl = SiteTimeline.build(CACHE, site, T0, T0 + 85 * DAY, c)
    # orbit plane perpendicular to the dawn geometry: big plane change everywhere
    arr = ArrivalState(T0 + 5 * DAY, CACHE.pole("MOON", T0 + 5 * DAY), 100.0, 0.0, 820.0)
    res = analyze(arr, tl, c, CACHE.pole("MOON", T0))
    assert not res.feasible and "plane change" in res.reason and res.best_plane_change_ms > 5
    far = custom_site(-75.0, 132.4, requires_relay=False)
    tl_far = SiteTimeline.build(CACHE, far, T0, T0 + 85 * DAY, c)
    res = analyze(arr, tl_far, c, CACHE.pole("MOON", T0))
    assert not res.feasible and "Earth" in res.reason


def test_site_catalogue():
    ids = [s.id for s in SITES]
    assert len(ids) == len(set(ids)) >= 7
    for s in SITES:
        assert -90 <= s.lat_deg <= 90 and -180 <= s.lon_deg <= 180 and s.source.startswith("https://")
        np.testing.assert_allclose(np.linalg.norm(s.unit_fixed()), 1.0)
    assert get_site("schrodinger").requires_relay


def test_iau_orientation_against_spice_if_available():
    """Runs only where spiceypy and the DE440 kernels are installed; skipped otherwise."""
    try:
        from engine.ephemeris.factory import base_ephemeris
        spice = base_ephemeris(use_spice=True)
    except (ImportError, FileNotFoundError) as exc:
        raise unittest.SkipTest(f"SPICE not available: {exc}")
    for t in np.linspace(T0, T0 + 365 * DAY, 25):
        a, b = iau_moon.rotation(t), spice.body_fixed_rotation("MOON", t)
        assert np.degrees(np.arccos(np.clip(a[2] @ b[2], -1, 1))) < 0.1   # pole
        assert np.degrees(np.arccos(np.clip(a[0] @ b[0], -1, 1))) < 0.1   # prime meridian
