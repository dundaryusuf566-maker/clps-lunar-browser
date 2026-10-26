from datetime import datetime, timezone

import numpy as np

from engine.core.constants import AU_KM, BODIES
from engine.core.time import tdb_to_utc, utc_to_tdb
from engine.ephemeris import AnalyticEphemeris, change_center
from engine.core.state import State
from engine.orbits import Elements, cartesian_to_elements, elements_to_cartesian


def test_time_j2000_offset():
    # 2000-01-01 12:00 UTC is 64.184 s (+ ~1 ms periodic term) of TDB after J2000.
    tdb = utc_to_tdb(datetime(2000, 1, 1, 12, tzinfo=timezone.utc))
    assert abs(tdb - 64.184) < 0.002


def test_time_roundtrip():
    dt = datetime(2026, 11, 14, 9, 30, 15, tzinfo=timezone.utc)
    back = tdb_to_utc(utc_to_tdb(dt))
    assert abs((back - dt).total_seconds()) < 1e-3


def test_elements_roundtrip():
    gm = BODIES["MOON"].gm
    for el in [
        Elements(1838.0 + 500, 0.1, np.radians(85), np.radians(30), np.radians(90), np.radians(10)),
        Elements(4000.0, 0.6, np.radians(57), np.radians(300), np.radians(270), np.radians(200)),
        Elements(1938.0, 0.3, np.radians(120), np.radians(10), np.radians(45), np.radians(359)),
    ]:
        y = elements_to_cartesian(el, gm)
        back = cartesian_to_elements(y[:3], y[3:], gm)
        np.testing.assert_allclose(
            [back.sma, back.ecc, back.inc, back.raan, back.argp, back.nu],
            [el.sma, el.ecc, el.inc, el.raan, el.argp, el.nu], rtol=1e-9, atol=1e-9,
        )


def test_analytic_ephemeris_distances():
    eph = AnalyticEphemeris()
    for t in np.linspace(0, 3e8, 7):
        assert abs(np.linalg.norm(eph.position("MOON", "EARTH", t)) - 384_400) < 1.0
        assert abs(np.linalg.norm(eph.position("SUN", "EARTH", t)) / AU_KM - 1) < 0.02
    # Moon orbital speed ~1.02 km/s
    v = np.linalg.norm(eph.state("MOON", "EARTH", 1e7)[3:])
    assert abs(v - 1.023) < 0.01


def test_change_center_roundtrip():
    eph = AnalyticEphemeris()
    s = State(5e8, [7000, 100, -200, 0.1, 7.5, 0.3], "EARTH")
    s2 = change_center(change_center(s, "MOON", eph), "EARTH", eph)
    np.testing.assert_allclose(s2.vector, s.vector, atol=1e-9)
