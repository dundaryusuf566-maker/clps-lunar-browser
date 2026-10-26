"""Ground stations (DSN visibility) and the surface energy budget."""

import unittest
from datetime import datetime, timezone

import numpy as np

from engine.core.time import utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.surface import LandingConstraints, SiteTimeline, custom_site
from engine.surface.ground import DSN, dsn_mask, j2000_to_earth_fixed, station_ecef_km, station_elevations_deg, station_names

DAY = 86_400.0
T0 = utc_to_tdb(datetime(2026, 3, 1, tzinfo=timezone.utc))


def _sun_elev(lat, lon, t):
    sun = AnalyticEphemeris().position("SUN", "EARTH", t)
    r = j2000_to_earth_fixed([t])[0] @ sun
    s = type(DSN[0])("x", "x", lat, lon, 1)
    pos, up = station_ecef_km(s)
    v = r - pos
    return np.degrees(np.arcsin(v @ up / np.linalg.norm(v)))


def test_earth_rotation_puts_the_sun_where_it_should_be():
    # equinox, about local solar noon at Greenwich (equation of time ~ -7.5 min)
    t = utc_to_tdb(datetime(2026, 3, 20, 12, 7, tzinfo=timezone.utc))
    assert _sun_elev(0.0, 0.0, t) > 88.5
    assert abs(_sun_elev(51.48, 0.0, t) - (90 - 51.48)) < 1.5
    assert _sun_elev(0.0, 180.0, t) < -88.5
    # six hours later the Sun is on the horizon at Greenwich
    assert abs(_sun_elev(0.0, 0.0, t + 6 * 3600)) < 2.5


def test_dsn_covers_the_moon_most_of_the_time():
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 30 * DAY, 3600.0)
    ts = T0 + np.arange(0, 28 * DAY, 600.0)
    moon = cache.position_many("MOON", "EARTH", ts)
    el = station_elevations_deg(ts, moon)
    for s in DSN:
        frac = float(np.mean(el[s.id] >= 10.0))
        assert 0.25 < frac < 0.6, (s.id, frac)               # each station: roughly a third to a half of the time
    m = dsn_mask(ts, moon)
    assert float(np.mean(m > 0)) > 0.8                         # the network sees the Moon most of the time
    assert set(np.unique(m)) <= set(range(8))
    assert station_names(5) == ["Goldstone", "Canberra"]


def test_dsn_against_spice_if_available():
    """Runs only where spiceypy and the kernels are installed; skipped otherwise."""
    try:
        import spiceypy as sp

        from engine.ephemeris.factory import base_ephemeris
        base_ephemeris(use_spice=True)
    except (ImportError, FileNotFoundError) as exc:
        raise unittest.SkipTest(f"SPICE not available: {exc}")
    for t in np.linspace(T0, T0 + 365 * DAY, 13):
        ours = j2000_to_earth_fixed([t])[0]
        theirs = np.array(sp.pxform("J2000", "IAU_EARTH", float(t)))
        for v in np.eye(3):
            a, b = ours @ v, theirs @ v
            # IAU_EARTH is a low-precision model (linear pole drift for precession, rotation angle
            # linear in TDB), good to a few hundredths of a degree; 0.2 deg still catches any real error.
            assert np.degrees(np.arccos(np.clip(a @ b, -1, 1))) < 0.2


def test_energy_budget_and_dsn_in_the_timeline():
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 40 * DAY, 3600.0)
    site = custom_site(-84.79, 29.2, sun_min_deg=0.5, sun_max_deg=90.0)
    tl = SiteTimeline.build(cache, site, T0, T0 + 35 * DAY, LandingConstraints())
    f = tl.disc_fraction()
    assert f.min() >= 0 and f.max() <= 1 and np.all(f[tl.sun_clear > 0.3] == 1) and np.all(f[tl.sun_clear < -0.3] == 0)
    lit = int(np.argmax(tl.sun_clear > 1.0))
    pct, gap = tl.energy(lit, 2.0)
    assert pct > 95 and gap == 0
    dark = int(np.argmax(tl.sun_clear < -1.0))
    pct, gap = tl.energy(dark, 1.0)
    assert pct < 5 and gap > 20
    assert tl.dsn.shape == tl.ts.shape and (tl.dsn > 0).mean() > 0.8
    strict = SiteTimeline.build(cache, site, T0, T0 + 35 * DAY, LandingConstraints(require_dsn=True))
    assert strict.ok.sum() <= tl.ok.sum() and not np.any(strict.ok & (strict.dsn == 0))
