"""Ground stations on Earth: can NASA's Deep Space Network see the lander?

The Moon (the landing site itself, not the Moon's centre) is in view of a
station when it stands above the station's elevation mask. Earth orientation:
IAU 1976 precession from J2000 to the mean equator of date, then Greenwich mean
sidereal time (IAU 1982, Meeus 12.4). Nutation (< 20 arcsec) and polar motion are
ignored, and UT1 is taken as UTC = TT - 69.184 s (true since 2017). The error in
the Moon's elevation is a few hundredths of a degree, far below any mask.

Station coordinates: the three DSN complexes (Wikipedia, "NASA Deep Space
Network"). The 10 degree mask is our assumption, not a published DSN limit.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..ephemeris.cached import CachedEphemeris

ARCSEC = np.pi / (180 * 3600)
TT_MINUS_UTC_S = 69.184
WGS84_A, WGS84_F = 6378.137, 1 / 298.257223563


@dataclass(frozen=True)
class Station:
    id: str
    name: str
    lat_deg: float
    lon_deg: float
    bit: int


DSN = (
    Station("goldstone", "Goldstone", 35.42667, -116.89000, 1),
    Station("madrid", "Madrid", 40.43139, -4.24806, 2),
    Station("canberra", "Canberra", -35.40139, 148.98167, 4),
)
DSN_MIN_ELEV_DEG = 10.0
DSN_SOURCE = "https://en.wikipedia.org/wiki/NASA_Deep_Space_Network"


def station_names(mask: int) -> list[str]:
    return [s.name for s in DSN if int(mask) & s.bit]


def _rz(a: np.ndarray) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    o, z = np.ones_like(a), np.zeros_like(a)
    return np.stack([np.stack([c, s, z], -1), np.stack([-s, c, z], -1), np.stack([z, z, o], -1)], -2)


def _ry(a: np.ndarray) -> np.ndarray:
    c, s = np.cos(a), np.sin(a)
    o, z = np.ones_like(a), np.zeros_like(a)
    return np.stack([np.stack([c, z, -s], -1), np.stack([z, o, z], -1), np.stack([s, z, c], -1)], -2)


def j2000_to_earth_fixed(ts) -> np.ndarray:
    """(N, 3, 3) rotations J2000 -> Earth-fixed (precession + GMST) at TDB epochs `ts`."""
    ts = np.atleast_1d(np.asarray(ts, float))
    t = ts / (86400.0 * 36525.0)                                   # Julian centuries TT
    zeta = (2306.2181 * t + 0.30188 * t**2 + 0.017998 * t**3) * ARCSEC
    zz = (2306.2181 * t + 1.09468 * t**2 + 0.018203 * t**3) * ARCSEC
    theta = (2004.3109 * t - 0.42665 * t**2 - 0.041833 * t**3) * ARCSEC
    prec = _rz(-zz) @ _ry(theta) @ _rz(-zeta)                      # rotation matrices act on column vectors
    d_ut1 = (ts - TT_MINUS_UTC_S) / 86400.0                        # days of UT1 past J2000
    tu = d_ut1 / 36525.0
    gmst = np.radians((280.46061837 + 360.98564736629 * d_ut1 + 0.000387933 * tu**2 - tu**3 / 38710000.0) % 360.0)
    return _rz(gmst) @ prec


def station_ecef_km(s: Station) -> tuple[np.ndarray, np.ndarray]:
    """Position (km, WGS84, sea level) and geodetic up vector of a station."""
    p, l = np.radians(s.lat_deg), np.radians(s.lon_deg)
    e2 = WGS84_F * (2 - WGS84_F)
    n = WGS84_A / np.sqrt(1 - e2 * np.sin(p) ** 2)
    pos = np.array([n * np.cos(p) * np.cos(l), n * np.cos(p) * np.sin(l), n * (1 - e2) * np.sin(p)])
    up = np.array([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)])
    return pos, up


def station_elevations_deg(ts, target_j2000_km: np.ndarray) -> dict[str, np.ndarray]:
    """Elevation of a target (Earth-centred J2000 km, one row per epoch) at every DSN station."""
    rot = j2000_to_earth_fixed(ts)
    r = np.einsum("nij,nj->ni", rot, np.atleast_2d(target_j2000_km))
    out = {}
    for s in DSN:
        pos, up = station_ecef_km(s)
        v = r - pos
        out[s.id] = np.degrees(np.arcsin(np.clip(v @ up / np.linalg.norm(v, axis=1), -1, 1)))
    return out


def dsn_mask(ts, target_j2000_km: np.ndarray, min_elev_deg: float = DSN_MIN_ELEV_DEG) -> np.ndarray:
    """Bitmask per epoch of the stations that see the target (1 Goldstone, 2 Madrid, 4 Canberra)."""
    el = station_elevations_deg(ts, target_j2000_km)
    m = np.zeros(len(np.atleast_1d(ts)), dtype=np.int8)
    for s in DSN:
        m |= np.where(el[s.id] >= min_elev_deg, s.bit, 0).astype(np.int8)
    return m


def site_from_earth_km(cache: CachedEphemeris, ts, up_j2000: np.ndarray, radius_km: float = 1737.4) -> np.ndarray:
    """Earth-centred J2000 position of a lunar surface site (its unit vectors `up_j2000`)."""
    return cache.position_many("MOON", "EARTH", ts) + radius_km * up_j2000
