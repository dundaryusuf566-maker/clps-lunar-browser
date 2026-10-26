"""The fast horizon used for the website's polar horizon grid, against compute_horizon."""

import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from engine.surface.horizon_grid import Pyramid, block_means, fast_horizon, grid_nodes, latlon_of_plane
from engine.surface.terrain import compute_horizon

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_scene3d import _grid_with_mountain  # noqa: E402


def test_fast_horizon_matches_compute_horizon():
    """Same geometry, coarser steps and block means far out: within a few hundredths of a degree."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with _grid_with_mountain(Path(tmp), n=1201, scale=120.0) as g:
            pyr = Pyramid(g, levels=((1, 15.0), (3, 30.0), (10, 250.0)))
            diffs, t_fast, t_full, peak = [], 0.0, 0.0, 0.0
            for lat, lon in ((-89.2, 40.0), (-89.4, 100.0), (-88.9, 10.0), (-89.6, 250.0), (-89.05, 75.0)):
                t = time.perf_counter()
                el, dist, reach = fast_horizon(pyr, lat, lon, az_step_deg=1.0)
                t_fast += time.perf_counter() - t
                t = time.perf_counter()
                ref = compute_horizon(g, lat, lon, observer_m=2.0, az_step_deg=1.0, max_dist_km=250.0)
                t_full += time.perf_counter() - t
                diffs.append(el - ref.elev_deg)
                peak = max(peak, float(ref.elev_deg.max()))
                assert reach > 20.0
            d = np.abs(np.concatenate(diffs))
            assert np.median(d) < 0.03 and np.percentile(d, 95) < 0.15, (np.median(d), np.percentile(d, 95))
            assert peak > 4.0                                       # the mountain is in view
            assert t_fast < t_full, (t_fast, t_full)


def test_block_means_and_grid_nodes():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with _grid_with_mountain(Path(tmp), n=301, scale=240.0) as g:
            m = block_means(g, 3, rows_per_chunk=31)                # strips of an awkward size
            raw = np.asarray(g.data, float)
            assert m.shape == (100, 100)
            assert abs(m[10, 20] - raw[30:33, 60:63].mean()) <= 0.5
            X, Y, n, x0 = grid_nodes(g, 5.0, min_abs_lat=89.0)
            lat, lon = latlon_of_plane(g, X, Y)
            li, si = g.pixel(lat, lon)
            # the plane coordinates and the map's own projection agree
            assert np.allclose((si - g.sample_offset) * g.map_scale_m / 1000.0, X, atol=1e-6)
            assert np.allclose((li - g.line_offset) * g.map_scale_m / 1000.0, Y, atol=1e-6)
