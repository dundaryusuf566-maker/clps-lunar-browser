"""Independent check of the terrain horizon: average solar illumination.

NASA Goddard's polar illumination maps (Mazarico et al. 2011, Icarus 211,
1066-1081; PDS LOLA extras, AVGVISIB_75S_120M_201608) give, for every pixel of
LDEM_75S_120M, the fraction of hourly time steps over an 18.6-year cycle in
which any part of the solar disc is above the terrain. We compute the same
quantity from our own horizon masks and ephemeris at the landing sites and at a
grid of pixels around them, and compare.

The comparison tests reading the DEM, the horizon ray-marching with curvature, the
Sun azimuth / elevation in the local frame and the Moon's orientation, at the right
distance from the pole. It does NOT test which way round the map is read: averaged over
18.6 years the Sun goes round the sky evenly, so a mirrored or rotated map gives the same
averages (a synthetic test shows all four readings passing). The map's orientation is
checked against named craters instead (scripts/check_polar_orientation.py). It shares
nothing with the IM-1 / IM-2 retrodiction.

Pass criteria, fixed before the comparison was first run against real data:
per site, median |difference| <= 0.03 and max |difference| <= 0.08 (fractions
of time, i.e. 3 and 8 percentage points).
"""

from __future__ import annotations

import numpy as np

from ..ephemeris.cached import CachedEphemeris
from ..surface.terrain import SOLAR_SEMI_DIAMETER_DEG, HorizonMask, PolarGrid, compute_horizon

TOL_MEDIAN = 0.03
TOL_MAX = 0.08
DAY = 86_400.0
CYCLE_DAYS = 18.6 * 365.25


def sun_directions_fixed(cache: CachedEphemeris, start: float, end: float, step_s: float = 3600.0):
    """Unit vectors Moon -> Sun in the lunar body-fixed frame on an hourly grid."""
    ts = np.arange(start, end, step_s)
    sun = cache.position_many("SUN", "MOON", ts)
    rot = cache.rotation_many("MOON", ts)                  # J2000 -> fixed
    s = np.einsum("nij,nj->ni", rot, sun)
    return ts, s / np.linalg.norm(s, axis=1, keepdims=True)


def az_el_fixed(lat_deg: float, lon_deg: float, dirs_fixed: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Azimuth (from north, clockwise) and elevation of body-fixed directions at a site."""
    p, l = np.radians(lat_deg), np.radians(lon_deg)
    up = np.array([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)])
    north = np.array([-np.sin(p) * np.cos(l), -np.sin(p) * np.sin(l), np.cos(p)])
    east = np.array([-np.sin(l), np.cos(l), 0.0])
    el = np.degrees(np.arcsin(np.clip(dirs_fixed @ up, -1, 1)))
    az = np.degrees(np.arctan2(dirs_fixed @ east, dirs_fixed @ north)) % 360.0
    return az, el


def average_illumination(mask: HorizonMask, dirs_fixed: np.ndarray,
                         margin_deg: float = -SOLAR_SEMI_DIAMETER_DEG) -> float:
    """Fraction of samples in which the Sun's upper limb clears the terrain."""
    az, el = az_el_fixed(mask.lat_deg, mask.lon_deg, dirs_fixed)
    return float(np.mean(el - mask.elevation(az) > margin_deg))


def pixels_around(grid: PolarGrid, lat_deg: float, lon_deg: float, half: int = 2, spacing: int = 8):
    """Pixel centres on a (2*half+1)^2 grid around a site, `spacing` pixels apart."""
    li, si = grid.pixel(lat_deg, lon_deg)
    l0, s0 = int(round(float(li))), int(round(float(si)))
    out = []
    for dl in range(-half, half + 1):
        for ds in range(-half, half + 1):
            line, sample = l0 + dl * spacing, s0 + ds * spacing
            lat, lon = grid.latlon(line, sample)
            out.append((line, sample, float(lat), float(lon)))
    return out


def compare_site(dem: PolarGrid, avg: PolarGrid, dirs_fixed: np.ndarray, site_id: str, lat_deg: float,
                 lon_deg: float, half: int = 2, spacing: int = 8, az_step_deg: float = 0.5,
                 max_dist_km: float = 250.0, log=print) -> dict:
    """Our average illumination vs the NASA map at the pixels around one site."""
    pts = []
    for line, sample, lat, lon in pixels_around(dem, lat_deg, lon_deg, half, spacing):
        mask = compute_horizon(dem, lat, lon, site=site_id, observer_m=0.0, az_step_deg=az_step_deg,
                               max_dist_km=max_dist_km)
        ours = average_illumination(mask, dirs_fixed)
        nasa = float(avg.data[line, sample]) * avg.scale + avg.offset
        pts.append({"lat": round(lat, 5), "lon": round(lon, 5), "ours": round(ours, 4), "nasa": round(nasa, 4),
                    "diff": round(ours - nasa, 4)})
    d = np.array([p["diff"] for p in pts])
    ours, nasa = np.array([p["ours"] for p in pts]), np.array([p["nasa"] for p in pts])
    corr = float(np.corrcoef(ours, nasa)[0, 1]) if ours.std() > 0 and nasa.std() > 0 else None
    res = {
        "site": site_id, "lat_deg": lat_deg, "lon_deg": lon_deg, "points": pts, "n": len(pts),
        "spacing_m": spacing * dem.map_scale_m,
        "median_abs_diff": round(float(np.median(np.abs(d))), 4), "max_abs_diff": round(float(np.abs(d).max()), 4),
        "mean_diff": round(float(d.mean()), 4), "correlation": None if corr is None else round(corr, 3),
        "nasa_range": [round(float(nasa.min()), 3), round(float(nasa.max()), 3)],
    }
    res["pass"] = res["median_abs_diff"] <= TOL_MEDIAN and res["max_abs_diff"] <= TOL_MAX
    log(f"  {site_id}: {len(pts)} pixels, NASA {res['nasa_range'][0]:.2f}-{res['nasa_range'][1]:.2f}, "
        f"median |diff| {res['median_abs_diff']:.3f}, max {res['max_abs_diff']:.3f}, bias {res['mean_diff']:+.3f}, "
        f"r {res['correlation']}  -> {'PASS' if res['pass'] else 'FAIL'}")
    return res
