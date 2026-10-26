"""3D journey: one transfer designed with the analytic ephemeris, followed through
the wait in lunar orbit to a schematic touchdown."""

from datetime import datetime, timezone

import numpy as np

from engine.core.constants import BODIES
from engine.core.time import utc_to_tdb
from engine.database.webexport import controls_from_row, spec_from_row
from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.mission.journey import build_journey, quat_from_matrix
from engine.mission.transfer import TransferDesigner, TransferSpec, design_transfer
from engine.surface import LandingConstraints, SiteTimeline, analyze, arrival_from_row, get_site
from engine.surface.geometry import site_inertial
from engine.surface.sites import MOON_MEAN_RADIUS_KM

DAY = 86_400.0
MOON = BODIES["MOON"]
_CACHE: dict = {}


def _journey():
    if "j" in _CACHE:
        return _CACHE["j"]
    t0 = utc_to_tdb(datetime(2026, 1, 11, tzinfo=timezone.utc))
    cache = CachedEphemeris.build(AnalyticEphemeris(), t0 - 2 * DAY, t0 + 60 * DAY, 3600.0)
    row = design_transfer(cache, TransferSpec(t0, tof_days=5.0, family=+1)).to_row()
    site = get_site("mons-mouton")
    c = LandingConstraints(max_wait_days=30.0, use_terrain=False)
    arr = arrival_from_row(row)
    tl = SiteTimeline.build(cache, site, arr.arrival_epoch + DAY - 3600, arr.arrival_epoch + 47 * DAY, c)
    res = analyze(arr, tl, c, cache.pole("MOON", arr.arrival_epoch))
    assert res.feasible
    j = build_journey(cache, TransferDesigner(cache, spec_from_row(row)), controls_from_row(row), arr, site,
                      1200.0, res.landing_epoch, c)
    _CACHE["j"] = (j, res, cache, site, arr)
    return _CACHE["j"]


def test_journey_is_continuous_and_ordered():
    j, *_ = _journey()
    t, mci, phase = np.array(j["t"]), np.array(j["mci"]), np.array(j["phase"])
    assert np.all(np.diff(t) > 0) and list(np.unique(phase)) == [0, 1, 2, 3]
    assert np.all(np.diff(phase) >= 0)                              # phases in order
    speed = np.linalg.norm(np.diff(mci, axis=0), axis=1) / np.diff(t)
    assert speed.max() < 12.0                                       # no jumps (km/s, Moon-centred)
    ev = [e["t"] for e in j["events"]]
    assert ev == sorted(ev) and j["events"][1]["id"] == "tli" and j["events"][1]["t"] == 0.0
    assert set(np.unique(j["dsn"])) <= set(range(8))


def test_lunar_orbit_follows_the_analysis_model():
    j, res, *_ = _journey()
    mci, phase, t = np.array(j["mci"]), np.array(j["phase"]), np.array(j["t"])
    orbit = mci[phase == 2]
    r = np.linalg.norm(orbit, axis=1)
    assert np.allclose(r, MOON.radius + j["orbit"]["alt_km"], atol=1e-2)
    # the plane turned at the end is the analysis's plane change
    assert abs(j["orbit"]["plane_turn_deg"] - res.plane_change_deg) < 0.02
    assert abs(j["orbit"]["plane_turn_ms"] - res.plane_change_ms) < 1.0
    assert j["orbit"]["phase_adjust_pct_of_motion"] < 5.0          # the phasing fix is small
    # first orbit sample sits at the LOI periselene (end of the coast)
    k = int(np.flatnonzero(phase == 2)[0])
    assert np.linalg.norm(mci[k] - mci[k - 1]) < 2.0 * (t[k] - t[k - 1])


def test_touchdown_at_the_site():
    j, res, cache, site, _ = _journey()
    t, mci, phase = np.array(j["t"]), np.array(j["mci"]), np.array(j["phase"])
    assert abs(j["tli_epoch"] + t[-1] - res.landing_epoch) < 1e-3
    up = site_inertial(cache, site, np.array([res.landing_epoch]))[0]
    assert np.linalg.norm(mci[-1] - up * (MOON_MEAN_RADIUS_KM + 1.2)) < 1e-3       # km
    r = np.linalg.norm(mci[phase == 3], axis=1)
    assert np.all(np.diff(r) <= 2e-3) and abs(r[-1] - (MOON_MEAN_RADIUS_KM + 1.2)) < 2e-3   # stored to 1 m


def test_orientation_quaternions():
    j, res, cache, site, _ = _journey()
    h = j["hourly"]
    k = h["n"] // 2
    ts = j["tli_epoch"] + h["t0"] + k * h["step"]
    x, y, z, w = h["q_moon"][k]
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    up = site_inertial(cache, site, np.array([ts]))[0]
    assert np.linalg.norm(R @ site.unit_fixed() - up) < 1e-6
    # sign-continuous series (for interpolation in the browser)
    q = np.array(h["q_moon"])
    assert np.all(np.sum(q[1:] * q[:-1], axis=1) > 0)
    m = np.array([[0.0, -1, 0], [1, 0, 0], [0, 0, 1]])
    assert np.allclose(np.abs(quat_from_matrix(m[None])[0]), [0, 0, np.sqrt(0.5), np.sqrt(0.5)])
