"""3D scene export: map crops, projection helpers, and the shader's ray march
(run here in numpy) against the engine's horizon masks."""

import sys
import tempfile
from pathlib import Path

import numpy as np

from engine.surface.scene3d import (
    INVALID_DN, MOON_R_KM, agreement, crop_rings, disc_fraction, engine_sun_clear, enu_basis, latlon_from_plane,
    march_steps, march_sun_clear, plane_from_fixed, unit,
)
from engine.surface.terrain import SOLAR_SEMI_DIAMETER_DEG

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_terrain import destination, empty_grid, write_grid  # noqa: E402

LAT, LON = -89.2, 40.0          # test site (the synthetic grids are centred on the pole)


def _grid_with_mountain(folder, n=601, scale=240.0):
    lats, lons = empty_grid(n, scale)
    la, lo = destination(LAT, LON, 60.0, 20e3)
    p1, p2 = np.radians(la), np.radians(lats)
    d = MOON_R_KM * 1e3 * np.arccos(np.clip(np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2)
                                            * np.cos(np.radians(lons - lo)), -1, 1))
    h = 2500.0 * np.exp(-(d / 6e3) ** 2) + 300.0 * np.sin(lats * 7) * np.cos(np.radians(lons) * 3)
    return write_grid(folder, h, scale)


def _sun_dirs(lat, lon, n=600, seed=3):
    rng = np.random.default_rng(seed)
    az, el = np.radians(rng.uniform(0, 360, n)), np.radians(rng.uniform(-1.0, 5.0, n))
    e, nth, up = enu_basis(lat, lon)
    v = (np.cos(el) * np.sin(az))[:, None] * e + (np.cos(el) * np.cos(az))[:, None] * nth + np.sin(el)[:, None] * up
    return v / np.linalg.norm(v, axis=1, keepdims=True)


def test_plane_projection_matches_the_map():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with write_grid(Path(tmp), np.zeros((101, 101)), 120.0) as g:
            for lat, lon in [(-89.0, 10.0), (-85.0, 200.0), (-80.5, -45.0)]:
                li, si = g.pixel(lat, lon)
                X, Y = plane_from_fixed(unit(lat, lon) * (MOON_R_KM + 3.7))      # any radius: same map point
                assert abs(X - (si - g.sample_offset) * 0.12) < 1e-9 and abs(Y - (li - g.line_offset) * 0.12) < 1e-9
                la2, lo2 = latlon_from_plane(X, Y)
                assert abs(la2 - lat) < 1e-9 and abs((lo2 - lon + 180) % 360 - 180) < 1e-9


def test_crops_keep_the_map_values():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        h = np.random.default_rng(0).uniform(-2000, 4000, (401, 401))
        with write_grid(Path(tmp), h, 120.0) as g:
            (inner, mid, outer), (lc, sc) = crop_rings(g, LAT, LON, 3.0, rings=((1, None), (3, 10.0), (10, 40.0)))
            assert inner.shape == (51, 51)
            # inner: every map pixel; bilinear sampling equals the map's own interpolation
            for lat, lon in [(LAT, LON), (LAT + 0.01, LON + 1.0)]:
                X, Y = plane_from_fixed(unit(lat, lon))
                assert abs(inner.sample(X, Y)[()] * 1000 - (g.value(lat, lon)[0] - g.radius_m)) < 1e-6
            # outer: block means, centred where the metadata says; blocks past the map are invalid
            hk = outer.heights_km()
            j, i = outer.shape[0] // 2, outer.shape[1] // 2
            raw = (np.asarray(g.data[lc - 5:lc + 5, sc - 5:sc + 5], float) * 0.5).mean() / 1000
            assert abs(hk[j, i] - raw) < 0.5e-3 / 2 + 1e-9
            Xc, Yc = outer.x0_km + i * outer.step_km, outer.y0_km + j * outer.step_km
            assert abs(Xc - ((sc - 0.5) - g.sample_offset) * 0.12) < 1e-9
            assert abs(Yc - ((lc - 0.5) - g.line_offset) * 0.12) < 1e-9
            assert (outer.dn == INVALID_DN).any() and np.isfinite(hk).sum() > 0
            # odd blocks are centred on their pixel
            jm, im = mid.shape[0] // 2, mid.shape[1] // 2
            assert abs(mid.x0_km + im * mid.step_km - (sc - g.sample_offset) * 0.12) < 1e-9
            raw3 = (np.asarray(g.data[lc - 1:lc + 2, sc - 1:sc + 2], float) * 0.5).mean() / 1000
            assert abs(mid.heights_km()[jm, im] - raw3) < 0.5e-3 / 2 + 1e-9


def test_march_schedule():
    t = march_steps()
    d = np.diff(t)
    assert abs(t[0] - 0.18) < 1e-12 and t[-1] <= 250.0 and 250.0 - t[-1] <= 1.2
    assert d.min() >= 0.12 - 1e-12 and d.max() <= 1.2 + 1e-12
    assert len(t) < 400                                   # cheap enough for the GPU


def test_disc_fraction():
    s = SOLAR_SEMI_DIAMETER_DEG
    assert disc_fraction(s + 0.01) == 1.0 and disc_fraction(-s - 0.01) == 0.0
    assert abs(disc_fraction(0.0) - 0.5) < 1e-12
    assert 0.5 < disc_fraction(0.1) < 1.0


def test_march_agrees_with_compute_horizon():
    """Full resolution everywhere: the shader's algorithm must reproduce the engine."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with _grid_with_mountain(Path(tmp)) as g:
            grids, _ = crop_rings(g, LAT, LON, 72.0, rings=((1, None),))
            sun = _sun_dirs(LAT, LON)
            ours = march_sun_clear(grids, LAT, LON, sun)
            eng, mask = engine_sun_clear(g, LAT, LON, sun, max_dist_km=250.0)
            a = agreement(ours, eng)
            assert mask.elev_deg.max() > 4.0                       # the mountain is there
            assert a["median_abs_deg"] < 0.01 and a["p95_abs_deg"] < 0.05, a
            assert a["lit_agree_pct"] >= 99.0, a
            # the early exit only shortens rays that already cleared all terrain
            full = march_sun_clear(grids, LAT, LON, sun, early_exit=False)
            hidden = full < 0
            assert np.allclose(ours[hidden], full[hidden], atol=1e-9)
            assert np.all(ours[~hidden] >= full[~hidden] - 1e-9)


def test_coarse_outer_grid_still_agrees():
    """Beyond the inner square the scene uses 3- and 10-pixel block means; shadows must hold up."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with _grid_with_mountain(Path(tmp), n=1201, scale=120.0) as g:
            grids, _ = crop_rings(g, LAT, LON, 8.0, rings=((1, None), (3, 30.0), (10, 72.0)))
            sun = _sun_dirs(LAT, LON, seed=5)
            a = agreement(march_sun_clear(grids, LAT, LON, sun), engine_sun_clear(g, LAT, LON, sun)[0])
            assert a["median_abs_deg"] < 0.03 and a["p95_abs_deg"] < 0.15 and a["lit_agree_pct"] >= 97.0, a


def test_agreement_summary():
    a = agreement(np.array([0.5, -0.5, 2.0, 0.1]), np.array([0.5, -0.4, 5.0, -0.1]))
    assert a["n"] == 4 and a["near_horizon"] == 3                 # 2 vs 5: both fully lit, not counted
    assert a["median_abs_deg"] == 0.1
    assert a["lit_compared"] == 3 and a["lit_agree_pct"] == 100.0
