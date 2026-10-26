"""Retrodiction of flown missions and the NASA comparison helpers."""

import numpy as np

from engine.ephemeris import AnalyticEphemeris, CachedEphemeris
from engine.mission import TransferSpec, design_transfer
from engine.surface import intervals
from engine.validation.missions import IM1, IM2, MISSIONS
from engine.validation.nasa_reference import REFERENCE, compare
from engine.validation.retrodiction import (
    MISSION_CONSTRAINTS, launch_windows, lighting, mission_constraints, reconstruct, reconstruction_jobs, scan_jobs, utc_epoch,
    window_span,
)

DAY = 86_400.0


def test_mission_records_are_consistent():
    for m in MISSIONS:
        tli, loi, land = utc_epoch(m.tli_utc), utc_epoch(m.loi_utc), utc_epoch(m.landing_utc)
        assert utc_epoch(m.launch_utc) < tli < loi < land
        assert 3.0 < (loi - tli) / DAY < 8.0          # direct transfers
        # the time in lunar orbit fits the wait the retrodiction allows (IM-1/IM-2: under 4 days; Blue Ghost 1: its
        # published 16-day checkout, under the 20 days it is given)
        assert 0.5 < (land - loi) / DAY < mission_constraints(m).max_wait_days
        assert m.polar == (m.region == "South polar")
        assert m.sun_min_deg < m.sun_max_deg
        if m.sunset_utc:
            assert land < utc_epoch(m.sunset_utc) < utc_epoch(m.surface_end_utc)
        assert m.sources and all(u.startswith("https://") for _, u in m.sources)
        for first, last, _ in m.launch_windows:
            assert first <= last
    jobs = reconstruction_jobs(IM1)
    assert len(jobs) == 2 * 21 and {j["family"] for j in jobs} == {1, -1}
    assert abs(jobs[0]["tof_days"] - 6.354) < 0.01
    assert len(scan_jobs(IM2, 2, 3, tofs=(4.0, 5.0), incs=(90.0,))) == 6 * 2


def test_intervals_and_windows():
    ts = np.arange(10.0)
    mask = np.array([0, 1, 1, 0, 0, 1, 0, 1, 1, 1], bool)
    assert intervals(ts, mask) == [(1.0, 2.0), (5.0, 5.0), (7.0, 9.0)]
    assert intervals(ts, np.zeros(10, bool)) == []
    days = ["2024-02-10", "2024-02-11", "2024-02-12", "2024-02-14", "2024-02-15"]
    w = launch_windows(days, [True, True, False, True, True])
    assert w == [{"first": "2024-02-10", "last": "2024-02-11", "days": 2},
                 {"first": "2024-02-14", "last": "2024-02-15", "days": 2}]
    # a missing calendar day breaks a run even when both neighbours qualify
    assert len(launch_windows(["2024-02-10", "2024-02-12"], [True, True])) == 2


def test_lighting_at_the_real_touchdowns():
    """Both IM landers came down with the Sun low and rising, Earth in view."""
    for m, (lo, hi) in ((IM1, (8.0, 12.0)), (IM2, (1.0, 4.0))):
        land = utc_epoch(m.landing_utc)
        cache = CachedEphemeris.build(AnalyticEphemeris(), land - 22 * DAY, land + 22 * DAY, 3600.0)
        li = lighting(cache, m.site(), land)
        assert lo < li["sun_elev_deg"] < hi, li
        assert li["sun_rising"] and li["earth_elev_deg"] > 2.0
        assert li["sunrise_utc"] < m.landing_utc < li["sunset_utc"]
        assert li["daylight_left_days"] > 5.0


def test_im2_reconstruction_lands_at_the_real_time():
    """IM-2: the arrival designed from the real TLI and transit time can land at
    Mons Mouton at the real touchdown instant with a small plane change."""
    job = [j for j in reconstruction_jobs(IM2, incs=(90.0,)) if j["family"] == 1]
    span = window_span(job, MISSION_CONSTRAINTS)
    cache = CachedEphemeris.build(AnalyticEphemeris(), *span, 3600.0)
    row = design_transfer(cache, TransferSpec(**job[0])).to_row()
    row["converged"] = str(row["converged"])
    out = reconstruct(cache, IM2, [row])
    assert out["designs"] == 1 and out["failed"] == 0
    d = out["polar"][0]
    assert 780 < d["loi_dv_ms"] < 860
    assert d["real_landing_landable"], d["at_real_landing"]
    assert d["at_real_landing"]["plane_change_ms"] < MISSION_CONSTRAINTS.max_plane_change_ms


def test_nasa_compare():
    rows = []
    for day, v in (("2025-12-11", 801.0), ("2025-12-14", 830.0), ("2026-01-09", 799.0), ("2026-02-05", 990.0)):
        rows.append({"converged": "True", "tli_utc": f"{day}T00:00:00+00:00", "loi_dv_ms": str(v),
                     "spec_tof_days": "6.0", "ephemeris": "spice"})
    rows.append({"converged": "False", "tli_utc": "2026-03-01T00:00:00+00:00"})
    out = compare(rows)
    assert out["count"] == 4 and out["requested"] == 5
    assert out["band_ms"] == [799.0, 990.0]
    assert out["band_error_ms"] == [799.0 - REFERENCE["loi_min_ms"], 990.0 - REFERENCE["loi_max_ms"]]
    by = {m["month"]: m for m in out["minima"]}
    assert by["2025-12"]["our_date"] == "2025-12-11" and by["2025-12"]["days_apart"] == 0
    assert by["2026-01"]["days_apart"] == 1
    assert "2026-03" not in by
