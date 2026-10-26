"""Light and heat from the surrounding terrain.

A point on the Moon receives, besides direct sunlight, sunlight reflected by the
terrain it can see and the infrared that terrain emits. In polar shadows this is
the only heat input. Two tools:

1. A facet radiosity solver (`equilibrium`): view factors between surface facets
   (Lambertian, midpoint rule: F_ij = cos(t_i) cos(t_j) A_j / (pi r^2)) and the
   radiative equilibrium with every bounce, visible and infrared:

       B   = alpha (E + F B)                        reflected sunlight leaving each facet
       W   = (1 - alpha)(E + F B) + eps F W         W = eps sigma T^4, emitted infrared

   It reproduces the closed-form temperature in the shadow of a spherical bowl
   crater (Ingersoll, Svitek & Murray 1992, `ingersoll_shadow`), which is how it is
   tested.

2. Directional sampling for a single point (`sky_samples`, `first_hits`): the
   directions in which the point sees terrain (below its LOLA horizon, above the
   plane of its own tilted surface), the terrain each direction hits, and the
   weights w = cos(t) dOmega / pi, so that the irradiance from terrain of
   radiosity B is sum(w B). The build script gives each hit its own sunlight and
   temperature and adds the light and heat they send to the point. This is one
   bounce: light the terrain itself receives from other terrain is left out. For
   a point that sees a fraction f of terrain the missing part is of order alpha f
   and the infrared of shadowed terrain; `single_bounce_ratio` gives its size for
   a bowl of the same f.
"""

from __future__ import annotations

import numpy as np

from .scene3d import MOON_R_KM, SceneGrid, plane_from_fixed, sample_grids
from .thermal import SIGMA, Regolith, albedo

INGERSOLL1992 = "https://resolver.caltech.edu/CaltechAUTHORS:20121205-153626186"   # Icarus 100, 40-47


# --- 1. facets ---------------------------------------------------------------------------
def view_factors(centers: np.ndarray, normals: np.ndarray, areas: np.ndarray) -> np.ndarray:
    """F[i, j], the view factor from facet i to facet j: the irradiance at i per unit
    radiosity of j (Lambertian, midpoint rule). Facets behind each other's tangent
    planes get 0; no other occlusion test (meant for concave enclosures such as a
    bowl, where every facet sees every other)."""
    d = centers[None, :, :] - centers[:, None, :]
    r2 = np.einsum("ijk,ijk->ij", d, d)
    np.fill_diagonal(r2, np.inf)
    ci = np.einsum("ik,ijk->ij", normals, d)
    cj = -np.einsum("jk,ijk->ij", normals, d)
    F = np.where((ci > 0) & (cj > 0), ci * cj / (np.pi * r2 * r2), 0.0) * areas[None, :]
    np.fill_diagonal(F, 0.0)
    return F


def equilibrium(F: np.ndarray, E: np.ndarray, alpha: float, eps: float) -> tuple[np.ndarray, np.ndarray]:
    """Radiative equilibrium with all bounces (no conduction). E: direct sunlight on
    each facet (W m^-2). Returns (B, W): reflected sunlight leaving each facet and
    W = eps sigma T^4."""
    n = len(E)
    I = np.eye(n)
    B = np.linalg.solve(I - alpha * F, alpha * E)
    W = np.linalg.solve(I - eps * F, (1 - alpha) * (E + F @ B))
    return B, W


def ingersoll_f(depth_to_diameter: float) -> float:
    """View factor of a spherical bowl from a point on it: 1/f = 1 + (D/d)^2 / 4."""
    return 1.0 / (1.0 + 0.25 / depth_to_diameter ** 2)


def ingersoll_shadow(depth_to_diameter: float, sun_el_deg: float, S: float, alpha: float, eps: float) -> float:
    """Temperature (K) in the shadowed part of a spherical bowl crater in radiative
    equilibrium (Ingersoll et al. 1992; as written in Potter et al. 2022, eqs. 32-35):
    eps sigma T^4 = (1 - alpha) S sin(e) f (eps + alpha (1 - f)) / (1 - alpha f)."""
    f = ingersoll_f(depth_to_diameter)
    q = (1 - alpha) * S * np.sin(np.radians(sun_el_deg)) * f * (eps + alpha * (1 - f)) / (1 - alpha * f)
    return float((q / (eps * SIGMA)) ** 0.25)


def single_bounce_ratio(f: float, alpha: float, eps: float) -> float:
    """In a bowl of view factor f: flux into the shadow counting one bounce from the
    sunlit part only, divided by the full (Ingersoll) flux. 1 - this is what the
    one-bounce sampling leaves out at that f."""
    return (alpha + eps) * (1 - f) * (1 - alpha * f) / (eps + alpha * (1 - f))


def diffuse_albedo(r: Regolith = Regolith(), n: int = 2000) -> float:
    """Albedo for light arriving from all directions of a hemisphere (cosine-weighted
    mean of the incidence-angle law)."""
    i = (np.arange(n) + 0.5) / n * np.pi / 2
    w = np.cos(i) * np.sin(i)
    return float(np.sum(albedo(i, r) * w) / np.sum(w))


# --- 2. directions from one point ----------------------------------------------------------
def local_axes(up: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    east = np.cross([0.0, 0.0, 1.0], up)
    east /= np.linalg.norm(east)
    return east, np.cross(up, east)


def sky_samples(up: np.ndarray, normal: np.ndarray, horizon_el_deg, az_step_deg: float = 4.0,
                bands: int = 3) -> tuple[np.ndarray, np.ndarray]:
    """Directions (Moon-fixed unit vectors) in which a point sees terrain, and their
    weights cos(t) dOmega / pi. Terrain: below the horizon elevation of that azimuth
    (`horizon_el_deg(az)`), above the plane of the point's own surface (normal)."""
    east, north = local_axes(up)
    dirs, w = [], []
    daz = np.radians(az_step_deg)
    for az in np.arange(0.0, 360.0, az_step_deg) + az_step_deg / 2:
        a = np.radians(az)
        h = east * np.sin(a) + north * np.cos(a)
        ca, cb = float(h @ normal), float(up @ normal)
        el_cut = np.arctan2(-ca, cb)                         # where the direction grazes the surface
        el_top = np.radians(float(horizon_el_deg(az)))
        lo, hi = max(el_cut, np.radians(-80.0)), el_top
        if hi <= lo:
            continue
        edges = np.linspace(lo, hi, bands + 1)
        for e0, e1 in zip(edges[:-1], edges[1:]):
            el = 0.5 * (e0 + e1)
            d = np.cos(el) * h + np.sin(el) * up
            cos_t = float(d @ normal)
            if cos_t <= 0:
                continue
            # solid angle of the cell: cos(el) d(el) d(az), exact over the band
            dom = (np.sin(e1) - np.sin(e0)) * daz
            dirs.append(d)
            w.append(cos_t * dom / np.pi)
    return np.array(dirs).reshape(-1, 3), np.array(w)


def first_hits(grids: list[SceneGrid], hs: list[np.ndarray], origin: np.ndarray, dirs: np.ndarray,
               t0_km: float = 0.03, grow: float = 0.02, max_step_km: float = 0.6,
               max_km: float = 250.0) -> tuple[np.ndarray, np.ndarray]:
    """Where rays from `origin` (Moon-fixed km) along `dirs` first meet the terrain.
    Returns (points, ok); refined by bisection to a few metres."""
    n = len(dirs)
    def below(t):
        Q = origin + t[:, None] * dirs
        X, Y = plane_from_fixed(Q)
        h = sample_grids(grids, hs, X, Y)
        return np.linalg.norm(Q, axis=1) <= MOON_R_KM + h, np.isfinite(h)
    lo = np.zeros(n)
    hi = np.full(n, np.nan)
    t = t0_km
    open_ = np.ones(n, bool)
    while t <= max_km and open_.any():
        tt = np.full(n, t)
        b, ok = below(tt)
        hit = open_ & b
        hi[hit] = t
        open_ &= ~hit & ok
        lo[open_] = t
        t += min(max_step_km, max(t0_km, grow * t))
    found = np.isfinite(hi)
    for _ in range(14):
        mid = 0.5 * (lo + np.where(found, hi, lo))
        b, _ = below(mid)
        hi = np.where(found & b, mid, hi)
        lo = np.where(found & ~b, mid, lo)
    pts = origin + np.where(found, hi, 0.0)[:, None] * dirs
    return pts, found


def surface_normals(grids: list[SceneGrid], hs: list[np.ndarray], pts: np.ndarray) -> np.ndarray:
    """Outward normals of the terrain at Moon-fixed points (central differences on the
    map plane over the local grid step)."""
    from .scene3d import latlon_from_plane, unit
    X, Y = plane_from_fixed(pts)
    step = np.full(len(pts), grids[-1].step_km)
    for g in reversed(grids):
        inside = np.isfinite(g.sample(X, Y))
        step = np.where(inside, g.step_km, step)

    def p(dx, dy):
        lat, lon = latlon_from_plane(X + dx, Y + dy)
        h = sample_grids(grids, hs, X + dx, Y + dy)
        return unit(lat, lon) * (MOON_R_KM + h)[:, None]

    a = p(step, 0) - p(-step, 0)
    b = p(0, step) - p(0, -step)
    n = np.cross(a, b)
    n /= np.linalg.norm(n, axis=1, keepdims=True)
    up = pts / np.linalg.norm(pts, axis=1, keepdims=True)
    return np.where((np.sum(n * up, axis=1) < 0)[:, None], -n, n)


# --- the bowl checks (shown on the Validation page) ------------------------------------------
def bowl_check(gamma: float = 0.2, sun_el_deg: float = 15.0, D_km: float = 20.0, S: float = 1361.0,
               alpha: float = 0.12, eps: float = 0.95) -> dict:
    """Both tools on a spherical bowl crater (depth/diameter `gamma`, Sun `sun_el_deg`
    above the rim plane) against Ingersoll et al. (1992):
      * facet radiosity: temperature in the shadow, all bounces;
      * one-point directional sampling on a 120 m map of the same bowl: terrain
        irradiance on the shadowed floor against the one-bounce closed form."""
    from pathlib import Path
    from .scene3d import crop_rings, disc_fraction, latlon_from_plane, march_sun_clear, unit
    from .terrain import PolarGrid, compute_horizon

    # facets
    n_t, n_p = 24, 48
    d = gamma * D_km
    Rs = (D_km ** 2 / 4 + d * d) / (2 * d)
    th_max = np.arccos((Rs - d) / Rs)
    th = (np.arange(n_t) + 0.5) / n_t * th_max
    ph = (np.arange(n_p) + 0.5) / n_p * 2 * np.pi
    T, P = np.meshgrid(th, ph, indexing="ij")
    C = np.array([0.0, 0.0, Rs - d])
    p = C + Rs * np.stack([np.sin(T) * np.cos(P), np.sin(T) * np.sin(P), -np.cos(T)], -1).reshape(-1, 3)
    nrm = (C - p) / Rs
    area = (Rs * Rs * np.sin(T) * (th_max / n_t) * (2 * np.pi / n_p)).ravel()
    s = np.array([np.cos(np.radians(sun_el_deg)), 0.0, np.sin(np.radians(sun_el_deg))])
    lit = (nrm @ s > 0) & (p[:, 2] + 2 * Rs * (nrm @ s) * s[2] > 0)
    E = np.where(lit, S * (nrm @ s), 0.0)
    F = view_factors(p, nrm, area)
    _, W = equilibrium(F, E, alpha, eps)
    t_facets = float(np.median((W[~lit] / (eps * SIGMA)) ** 0.25))
    t_ref = ingersoll_shadow(gamma, sun_el_deg, S, alpha, eps)

    # directional sampling on a map of the bowl centred on the pole
    n, scale = 401, 120.0
    off = (n - 1) / 2
    jj, ii = np.mgrid[0:n, 0:n]
    rr = np.hypot((ii - off) * scale, (jj - off) * scale) / 1000.0           # km on the map plane ~ on the ground
    z = np.where(rr < D_km / 2, (Rs - d) - np.sqrt(np.maximum(Rs * Rs - rr * rr, 0)), 0.0)
    dem = PolarGrid(Path("bowl"), n, n, scale, off, off, 1737400.0, 0.5, 1737400.0,
                    np.round(z * 1000 / 0.5).astype(np.int16), name="BOWL")
    grids, _ = crop_rings(dem, -90.0, 0.0, 23.0, rings=((1, None),))
    hs = [g.heights_km() for g in grids]
    up = unit(-90.0, 0.0)
    site_r = MOON_R_KM + float(dem.value(-90.0, 0.0)[0] - dem.radius_m) / 1000.0
    mask = compute_horizon(dem, -90.0, 0.0, observer_m=0.0, az_step_deg=1.0, max_dist_km=20.0)
    dirs, w = sky_samples(up, up, mask.elevation, az_step_deg=3.0, bands=4)
    pts, ok = first_hits(grids, hs, up * (site_r + 0.001), dirs)
    pts, w = pts[ok], w[ok]
    nh = surface_normals(grids, hs, pts)
    east = np.cross([0.0, 0.0, 1.0], up)
    east /= np.linalg.norm(east)
    sun = np.cos(np.radians(sun_el_deg)) * east + np.sin(np.radians(sun_el_deg)) * up
    lat, lon = latlon_from_plane(*plane_from_fixed(pts))
    f_sun = np.array([float(disc_fraction(march_sun_clear(grids, la, lo, sun[None, :], observer_m=0.0, heights=hs))[0])
                      for la, lo in zip(lat, lon)])
    Eh = S * np.clip(nh @ sun, 0, None) * f_sun
    q = (1 - alpha) * np.sum(w * alpha * Eh) + eps * np.sum(w * (1 - alpha) * Eh)
    f = ingersoll_f(gamma)
    q_ref = (alpha + eps) * (1 - alpha) * f * (1 - f) * S * np.sin(np.radians(sun_el_deg))
    return {
        "depth_to_diameter": gamma, "sun_el_deg": sun_el_deg, "albedo": alpha, "emissivity": eps, "f": round(f, 4),
        "facets": {"n": int(len(p)), "shadow_t_k": round(t_facets, 2), "ingersoll_t_k": round(t_ref, 2),
                   "diff_pct": round(100 * (t_facets / t_ref - 1), 3)},
        "sampling": {"directions": int(len(w)), "view_factor": round(float(w.sum()), 4),
                     "flux_w_m2": round(float(q), 3), "one_bounce_w_m2": round(float(q_ref), 3),
                     "diff_pct": round(float(100 * (q / q_ref - 1)), 2)},
        "source": INGERSOLL1992,
    }
