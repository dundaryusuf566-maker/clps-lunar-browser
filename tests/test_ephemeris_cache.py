import tempfile
from datetime import datetime, timezone
from pathlib import Path

import unittest

import numpy as np

from engine.core.time import utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.mission import TransferSpec, design_transfer

BASE = AnalyticEphemeris()
T0 = utc_to_tdb(datetime(2026, 1, 1, tzinfo=timezone.utc))
CACHE = CachedEphemeris.build(BASE, T0, T0 + 20 * 86_400.0)


def _raises(exc, fn):
    try:
        fn()
    except exc:
        return True
    return False


def test_exact_at_grid_nodes():
    for k in (0, 7, CACHE.n - 1):
        t = CACHE.t0 + k * CACHE.step
        np.testing.assert_allclose(CACHE.state("MOON", "EARTH", t), BASE.state("MOON", "EARTH", t), atol=1e-9)


def test_interpolation_accuracy():
    err = CACHE.validate_against(BASE, n_samples=300)
    assert err["MOON"]["max_pos_err_km"] < 1e-3          # < 1 m
    assert err["MOON"]["max_vel_err_km_s"] < 1e-6
    assert err["SUN"]["max_pos_err_km"] < 1e-2           # < 10 m at 1 AU
    assert err["MOON_pole"]["max_angle_err_deg"] < 1e-6


def test_relative_pairs_and_position_shortcut():
    t = T0 + 3.3e5
    for target, observer in [("SUN", "MOON"), ("EARTH", "MOON"), ("MOON", "SUN")]:
        np.testing.assert_allclose(CACHE.state(target, observer, t), BASE.state(target, observer, t), atol=1e-2)
        np.testing.assert_allclose(CACHE.position(target, observer, t), CACHE.state(target, observer, t)[:3], atol=1e-12)
    assert np.all(CACHE.state("MOON", "MOON", t) == 0)


def test_save_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = CACHE.save(Path(d) / "eph.npz")
        loaded = CachedEphemeris.load(path)
    t = T0 + 7.77e5
    np.testing.assert_array_equal(loaded.state("SUN", "EARTH", t), CACHE.state("SUN", "EARTH", t))
    np.testing.assert_array_equal(loaded.pole("MOON", t), CACHE.pole("MOON", t))
    assert loaded.source == BASE.name and loaded.name == f"cached({BASE.name})"


def test_out_of_window_and_unknown_body():
    assert _raises(ValueError, lambda: CACHE.position("MOON", "EARTH", CACHE.t1 + 1.0))
    assert _raises(ValueError, lambda: CACHE.pole("MOON", CACHE.t0 - 1.0))
    assert _raises(KeyError, lambda: CACHE.position("MARS", "EARTH", T0 + 10.0))
    assert CACHE.covers(T0, T0 + 86_400) and not CACHE.covers(T0 - 1, T0 + 86_400)


def test_transfer_unchanged_by_cache():
    spec = TransferSpec(utc_to_tdb(datetime(2026, 1, 10, tzinfo=timezone.utc)), tof_days=5.0)
    a = design_transfer(BASE, spec).metrics
    b = design_transfer(CACHE, spec).metrics
    assert abs(a["loi_dv_ms"] - b["loi_dv_ms"]) < 0.05   # m/s
    assert abs(a["tli_dv_ms"] - b["tli_dv_ms"]) < 0.05
    assert abs(a["raan_moon_sun_deg"] - b["raan_moon_sun_deg"]) < 0.01


def test_cache_against_spice_if_available():
    """Runs only where spiceypy and the DE440 kernels are installed; skipped otherwise."""
    try:
        from engine.ephemeris.factory import base_ephemeris
        spice = base_ephemeris(use_spice=True)
    except (ImportError, FileNotFoundError) as exc:
        raise unittest.SkipTest(f"SPICE not available: {exc}")
    cache = CachedEphemeris.build(spice, T0, T0 + 30 * 86_400.0)
    err = cache.validate_against(spice, n_samples=300)
    # Real Moon motion (eccentric, perturbed) is rougher than the analytic
    # model, but a 1 h Hermite grid must still be far below 1 m.
    assert err["MOON"]["max_pos_err_km"] < 1e-3
    assert err["SUN"]["max_pos_err_km"] < 1e-2
    assert err["MOON_pole"]["max_angle_err_deg"] < 1e-4
