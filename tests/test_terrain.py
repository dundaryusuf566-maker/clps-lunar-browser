"""Terrain: LOLA grid reader, horizon masks, terrain-aware lighting.

Real LOLA files are not needed: the tests write small synthetic grids in the
same PDS3 format (label + little-endian int16 image) with known relief."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from engine.core.time import utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.surface import LandingConstraints, SiteTimeline, custom_site
from engine.surface import terrain
from engine.surface.geometry import local_frame, sun_az_el_deg
from engine.surface.terrain import HorizonMask, PolarGrid, compute_horizon, parse_pds3_label
from engine.validation.illumination import average_illumination, az_el_fixed, sun_directions_fixed

R = 1_737_400.0
DAY = 86_400.0
T0 = utc_to_tdb(datetime(2026, 1, 1, tzinfo=timezone.utc))

LABEL = """PDS_VERSION_ID = PDS3
RECORD_TYPE = FIXED_LENGTH
RECORD_BYTES = {rb}
FILE_RECORDS = {n}
^IMAGE = "{name}.IMG"
OBJECT = IMAGE
  LINES = {n}
  LINE_SAMPLES = {n}
  SAMPLE_TYPE = LSB_INTEGER
  SAMPLE_BITS = 16
  UNIT = METER
  SCALING_FACTOR = 0.5
  OFFSET = 1737400.
END_OBJECT = IMAGE
OBJECT = IMAGE_MAP_PROJECTION
  MAP_PROJECTION_TYPE = "POLAR STEREOGRAPHIC"
  A_AXIS_RADIUS = 1737.4 <KM>
  CENTER_LATITUDE = -90.0 <DEG>
  CENTER_LONGITUDE = 0.0 <DEG>
  LINE_PROJECTION_OFFSET = {off} <PIXEL>
  SAMPLE_PROJECTION_OFFSET = {off} <PIXEL>
  MAP_SCALE = {scale} <METERS/PIXEL>
END_OBJECT = IMAGE_MAP_PROJECTION
END
"""


def write_grid(folder: Path, heights_m: np.ndarray, scale_m: float, name: str = "SYNTH") -> PolarGrid:
    n = heights_m.shape[0]
    (folder / f"{name}.LBL").write_text(LABEL.format(rb=2 * n, n=n, name=name, off=(n - 1) / 2, scale=scale_m))
    np.round(heights_m / 0.5).astype("<i2").tofile(folder / f"{name}.IMG")
    return PolarGrid.load(folder / f"{name}.IMG")


def empty_grid(n: int, scale_m: float):
    """Pixel-centre lat / lon of an n x n grid (same convention as PolarGrid)."""
    g = PolarGrid(Path("x"), n, n, scale_m, (n - 1) / 2, (n - 1) / 2, R, 1.0, 0.0, np.zeros((1, 1)))
    lines, samples = np.mgrid[0:n, 0:n]
    return g.latlon(lines, samples)


def destination(lat, lon, az, dist_m):
    p, l, a, d = np.radians(lat), np.radians(lon), np.radians(az), dist_m / R
    p2 = np.arcsin(np.sin(p) * np.cos(d) + np.cos(p) * np.sin(d) * np.cos(a))
    l2 = l + np.arctan2(np.sin(a) * np.sin(d) * np.cos(p), np.cos(d) - np.sin(p) * np.sin(p2))
    return np.degrees(p2), np.degrees(l2)


def gc_dist(lat1, lon1, lat2, lon2):
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dl = np.radians(lon2 - lon1)
    c = np.sin(p1) * np.sin(p2) + np.cos(p1) * np.cos(p2) * np.cos(dl)
    return R * np.arccos(np.clip(c, -1, 1))


def test_label_and_projection():
    kv = parse_pds3_label(LABEL.format(rb=10, n=5, name="A", off=2, scale=120))
    assert kv["MAP_PROJECTION_TYPE"] == '"POLAR STEREOGRAPHIC"' and kv["SAMPLE_BITS"] == "16"
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with write_grid(Path(tmp), np.zeros((101, 101)), 300.0) as g:
            assert g.map_scale_m == 300.0 and g.radius_m == R and g.offset == R
            # round trip pixel <-> lat/lon
            lat, lon = g.latlon(np.array([3.0, 50.0, 97.5]), np.array([10.0, 50.0, 80.25]))
            li, si = g.pixel(lat[[0, 2]], lon[[0, 2]])
            assert np.allclose(li, [3.0, 97.5]) and np.allclose(si, [10.0, 80.25])
            # orientation: 0 deg meridian towards the top of the image, 90 E to the right
            l0, s0 = g.pixel(-89.9, 0.0)
            assert l0 < g.line_offset - 5 and abs(s0 - g.sample_offset) < 1e-6
            l90, s90 = g.pixel(-89.9, 90.0)
            assert s90 > g.sample_offset + 5 and abs(l90 - g.line_offset) < 1e-6
            # the pole is the centre of the grid
            lp, sp = g.pixel(-90.0, 123.0)
            assert abs(lp - 50) < 1e-9 and abs(sp - 50) < 1e-9
        assert g.data is None                     # closed: the file can be deleted on Windows too


def test_flat_sphere_horizon_is_the_dip():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with write_grid(Path(tmp), np.zeros((401, 401)), 300.0) as g:
            m = compute_horizon(g, -89.5, 40.0, observer_m=2.0, az_step_deg=5.0, max_dist_km=40.0, step_m=50.0)
        dip = np.degrees(np.arccos(R / (R + 2.0)))
        assert np.allclose(m.elev_deg, -dip, atol=0.01), (m.elev_deg.min(), m.elev_deg.max(), dip)
        assert abs(m.site_height_m) < 1e-6 and m.coverage_km > 20


def test_mountain_appears_in_the_right_direction():
    """A flat-topped 3 km mountain 15 km away at azimuth 60 deg: the horizon is set by
    the near edge of its summit plateau, at atan((H - d^2/2R - h)/d)."""
    site_lat, site_lon, az, D, H = -89.0, 30.0, 60.0, 15_000.0, 3000.0
    top, foot = 1500.0, 4000.0                      # plateau radius, base radius
    lats, lons = empty_grid(801, 300.0)
    plat, plon = destination(site_lat, site_lon, az, D)
    r = gc_dist(plat, plon, lats, lons)
    heights = H * np.clip((foot - r) / (foot - top), 0, 1)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        with write_grid(Path(tmp), heights, 300.0) as g:
            m = compute_horizon(g, site_lat, site_lon, observer_m=2.0, az_step_deg=1.0, max_dist_km=60.0, step_m=50.0)
    d = D - top
    expected = np.degrees(np.arctan((H - d**2 / (2 * R) - 2.0) / d))
    got = float(m.elevation(az))
    assert abs(got - expected) < 0.3, (got, expected)
    assert abs(float(m.dist_km[int(az)]) - d / 1000) < 0.5
    assert m.elevation(az + 180.0) < 0.0                     # nothing behind
    assert m.elevation(az + 90.0) < 0.0
    i = int(np.argmax(m.elev_deg))
    assert abs(m.az_deg[i] - az) <= 2.0


def test_mask_roundtrip_and_interpolation():
    az = np.arange(0, 360, 90.0)
    m = HorizonMask("x", -85.0, 10.0, az, np.array([0.0, 1.0, 2.0, 1.0]), np.ones(4), 2.0, 100.0, 250.0, 250.0,
                    "TEST", 120.0)
    assert np.allclose(m.elevation([45, 315, 360, -90]), [0.5, 0.5, 0.0, 1.0])
    m2 = HorizonMask.from_dict(m.to_dict())
    assert np.allclose(m2.az_deg, az) and np.allclose(m2.elev_deg, m.elev_deg) and m2.source == "TEST"


def test_two_azimuth_paths_agree():
    """Landing analysis (inertial frame) and illumination check (body-fixed frame)
    must see the Sun in the same direction."""
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 30 * DAY, 3600.0)
    site = custom_site(-84.79, 29.2)
    ts = T0 + np.arange(1, 29) * DAY
    az1, el1 = sun_az_el_deg(cache, site, ts, local_frame(cache, site, ts))
    _, dirs = sun_directions_fixed(cache, T0 + DAY, T0 + 29 * DAY, DAY)
    az2, el2 = az_el_fixed(site.lat_deg, site.lon_deg, dirs[: len(ts)])
    assert np.allclose(el1, el2, atol=0.02)
    assert np.allclose((az1 - az2 + 180) % 360 - 180, 0, atol=0.2)


def test_terrain_delays_sunrise_and_shortens_daylight():
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 60 * DAY, 3600.0)
    old_dir = terrain.HORIZON_DIR
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        terrain.HORIZON_DIR = Path(tmp)
        terrain.load_horizon.cache_clear()
        try:
            az = np.arange(0, 360, 1.0)
            HorizonMask("wall", -84.79, 29.2, az, np.full(360, 2.0), np.ones(360), 2.0, 0.0, 250.0, 250.0,
                        "TEST", 120.0).save()
            c = LandingConstraints()
            flat = custom_site(-84.79, 29.2, sun_min_deg=0.5, sun_max_deg=90.0)
            walled = custom_site(-84.79, 29.2, sun_min_deg=0.5, sun_max_deg=90.0, horizon="wall")
            a = SiteTimeline.build(cache, flat, T0, T0 + 59 * DAY, c)
            b = SiteTimeline.build(cache, walled, T0, T0 + 59 * DAY, c)
            assert a.terrain is None and b.terrain == "TEST"
            assert np.allclose(b.sun_hz, 2.0) and np.allclose(a.sun_hz, 0.0)
            assert b.sun_ok.sum() < a.sun_ok.sum()                       # less of the month is landable
            assert not np.any(b.sun_ok & ~a.sun_ok)                     # terrain never adds light
            k = int(np.flatnonzero((a.sun_el[:-1] < 0) & (a.sun_el[1:] >= 0))[0]) + 1   # a flat-horizon sunrise
            first_a = k + int(np.argmax(a.sun_ok[k:]))
            first_b = k + int(np.argmax(b.sun_ok[k:]))
            assert first_b > first_a                                     # the Sun clears the wall later
            assert (b.sun_clear > 0).sum() < (a.sun_clear > 0).sum()     # shorter daylight
            assert "horizon_deg" in b.sun_series() and "horizon_deg" not in a.sun_series()
            c_off = LandingConstraints(use_terrain=False)
            assert SiteTimeline.build(cache, walled, T0, T0 + 10 * DAY, c_off).terrain is None
        finally:
            terrain.HORIZON_DIR = old_dir
            terrain.load_horizon.cache_clear()


def test_average_illumination_limits():
    cache = CachedEphemeris.build(AnalyticEphemeris(), T0, T0 + 60 * DAY, 3600.0)
    _, dirs = sun_directions_fixed(cache, T0, T0 + 59 * DAY)
    az = np.arange(0, 360, 1.0)
    mk = lambda e: HorizonMask("x", -85.0, 0.0, az, np.full(360, e), np.ones(360), 0.0, 0.0, 1.0, 1.0, "T", 1.0)  # noqa: E731
    assert average_illumination(mk(-90.0), dirs) == 1.0
    assert average_illumination(mk(90.0), dirs) == 0.0
    flat = average_illumination(mk(0.0), dirs)
    assert 0.3 < flat < 0.7                     # near the pole the Sun is up about half the time
    assert average_illumination(mk(1.0), dirs) < flat < average_illumination(mk(-1.0), dirs)
