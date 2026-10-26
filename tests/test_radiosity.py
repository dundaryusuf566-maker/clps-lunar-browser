"""Terrain radiation: facet radiosity against Ingersoll et al. (1992), and the
one-point directional sampling against the one-bounce bowl result."""

import sys
import tempfile
from pathlib import Path

import numpy as np

from engine.surface.radiosity import (
    diffuse_albedo, equilibrium, first_hits, ingersoll_f, ingersoll_shadow, single_bounce_ratio, sky_samples,
    surface_normals, view_factors,
)
from engine.surface.scene3d import crop_rings, disc_fraction, march_sun_clear, unit
from engine.surface.terrain import compute_horizon
from engine.surface.thermal import SIGMA, Regolith

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_terrain import empty_grid, write_grid  # noqa: E402

S, ALPHA = 1361.0, 0.12
GAMMA = 0.2                      # depth / diameter
SUN_EL = 15.0


def _bowl_mesh(n_t=24, n_p=48, D=20.0):
    d = GAMMA * D
    Rs = (D * D / 4 + d * d) / (2 * d)
    th_max = np.arccos((Rs - d) / Rs)
    th = (np.arange(n_t) + 0.5) / n_t * th_max
    ph = (np.arange(n_p) + 0.5) / n_p * 2 * np.pi
    T, P = np.meshgrid(th, ph, indexing="ij")
    C = np.array([0.0, 0.0, Rs - d])                       # sphere centre; rim plane z = 0, bottom z = -d
    p = C + Rs * np.stack([np.sin(T) * np.cos(P), np.sin(T) * np.sin(P), -np.cos(T)], -1).reshape(-1, 3)
    nrm = (C - p) / Rs
    area = (Rs * Rs * np.sin(T) * (th_max / n_t) * (2 * np.pi / n_p)).ravel()
    s = np.array([np.cos(np.radians(SUN_EL)), 0.0, np.sin(np.radians(SUN_EL))])
    t2 = 2 * Rs * (nrm @ s)
    exit_z = p[:, 2] + t2 * s[2]
    lit = (nrm @ s > 0) & (exit_z > 0)
    E = np.where(lit, S * (nrm @ s), 0.0)
    return p, nrm, area, E, lit, D


def test_bowl_mesh_catches_all_sunlight():
    p, n, a, E, lit, D = _bowl_mesh()
    assert abs(np.sum(a * E) / (S * np.sin(np.radians(SUN_EL)) * np.pi * D * D / 4) - 1) < 0.01
    assert (~lit).sum() > 50


def test_facet_radiosity_matches_ingersoll():
    p, n, a, E, lit, _ = _bowl_mesh()
    F = view_factors(p, n, a)
    assert abs(F.sum(axis=1).mean() - ingersoll_f(GAMMA)) < 0.005           # sphere: every point sees f
    for eps, tol in ((1.0, 0.005), (0.95, 0.01)):
        B, W = equilibrium(F, E, ALPHA, eps)
        T = (W[~lit] / (eps * SIGMA)) ** 0.25
        ref = ingersoll_shadow(GAMMA, SUN_EL, S, ALPHA, eps)
        assert abs(np.median(T) / ref - 1) < tol, (eps, np.median(T), ref)
        assert np.ptp(T) / ref < 0.03                                         # uniform in the shadow


def _dem_bowl(folder):
    """Spherical bowl (D = 20 km, d/D = 0.2) centred on the pole of a 120 m grid."""
    n, scale = 401, 120.0
    lats, lons = empty_grid(n, scale)
    D, d = 20.0, GAMMA * 20.0
    Rs = (D * D / 4 + d * d) / (2 * d)
    rr = (90 + lats) * np.pi / 180 * 1737.4                             # km from the pole
    z = np.where(rr < D / 2, (Rs - d) - np.sqrt(np.maximum(Rs * Rs - rr * rr, 0)), 0.0)
    return write_grid(folder, z * 1000, scale)


def test_one_bounce_sampling_matches_the_bowl():
    """From the shadowed floor, the sampled terrain irradiance (sunlit walls only,
    each in equilibrium with the Sun) equals (alpha + eps) (1 - alpha) f (1 - f) S sin(e)."""
    eps = 0.95
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with _dem_bowl(Path(tmp)) as g:
            grids, _ = crop_rings(g, -90.0, 0.0, 23.0, rings=((1, None),))
            hs = [x.heights_km() for x in grids]
            up = unit(-90.0, 0.0)
            site_r = 1737.4 + float(g.value(-90.0, 0.0)[0] - g.radius_m) / 1000.0
            mask = compute_horizon(g, -90.0, 0.0, observer_m=0.0, az_step_deg=1.0, max_dist_km=20.0)
            dirs, w = sky_samples(up, up, mask.elevation, az_step_deg=3.0, bands=4)
            assert abs(w.sum() - ingersoll_f(GAMMA)) < 0.01                  # the bowl seen from its floor
            pts, ok = first_hits(grids, hs, up * (site_r + 0.001), dirs)
            assert ok.all()
            nh = surface_normals(grids, hs, pts)
            east = np.cross([0.0, 0.0, 1.0], up)
            east /= np.linalg.norm(east)
            sun = np.cos(np.radians(SUN_EL)) * east + np.sin(np.radians(SUN_EL)) * up
            from engine.surface.scene3d import latlon_from_plane, plane_from_fixed
            lat, lon = latlon_from_plane(*plane_from_fixed(pts))
            f_sun = np.array([float(disc_fraction(march_sun_clear(grids, la, lo, sun[None, :], observer_m=0.0,
                                                                  heights=hs))[0]) for la, lo in zip(lat, lon)])
            E = S * np.clip(nh @ sun, 0, None) * f_sun
            site_sun = float(disc_fraction(march_sun_clear(grids, -90.0, 0.0, sun[None, :], observer_m=0.0, heights=hs))[0])
            assert site_sun == 0.0                                               # the floor is in shadow
            q = (1 - ALPHA) * np.sum(w * ALPHA * E) + eps * np.sum(w * (1 - ALPHA) * E)
            f = ingersoll_f(GAMMA)
            expected = (ALPHA + eps) * (1 - ALPHA) * f * (1 - f) * S * np.sin(np.radians(SUN_EL))
            assert abs(q / expected - 1) < 0.06, (q, expected)
            # and the one-bounce shortfall against the full solution is what single_bounce_ratio says
            full = (1 - ALPHA) * S * np.sin(np.radians(SUN_EL)) * f * (eps + ALPHA * (1 - f)) / (1 - ALPHA * f)
            assert abs(expected / full - single_bounce_ratio(f, ALPHA, eps)) < 1e-12


def test_diffuse_albedo():
    a = diffuse_albedo(Regolith())
    assert 0.12 < a < 0.25
    assert abs(diffuse_albedo(Regolith(a=0.0, b=0.0)) - 0.12) < 1e-9
