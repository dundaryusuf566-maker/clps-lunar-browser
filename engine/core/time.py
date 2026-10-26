"""Time systems.

The engine's internal time scale is TDB seconds past J2000. Conversions here are
accurate to ~2 ms (the periodic TDB-TT term is included), which is plenty for
mission design. When SPICE is available, prefer its conversions.
"""

from __future__ import annotations

import math
from datetime import datetime, timezone

from .constants import SECONDS_PER_DAY

J2000_UTC = datetime(2000, 1, 1, 11, 58, 55, 816000, tzinfo=timezone.utc)  # = 12:00 TT
TT_MINUS_TAI = 32.184

# (UTC datetime from which it applies, TAI-UTC seconds). Only post-1999 entries.
_LEAP_SECONDS = [
    (datetime(1999, 1, 1, tzinfo=timezone.utc), 32.0),
    (datetime(2006, 1, 1, tzinfo=timezone.utc), 33.0),
    (datetime(2009, 1, 1, tzinfo=timezone.utc), 34.0),
    (datetime(2012, 7, 1, tzinfo=timezone.utc), 35.0),
    (datetime(2015, 7, 1, tzinfo=timezone.utc), 36.0),
    (datetime(2017, 1, 1, tzinfo=timezone.utc), 37.0),
]


def tai_minus_utc(dt: datetime) -> float:
    value = _LEAP_SECONDS[0][1]
    for start, offset in _LEAP_SECONDS:
        if dt >= start:
            value = offset
    return value


def _tdb_minus_tt(tt_seconds: float) -> float:
    g = math.radians(357.53 + 0.98560028 * (tt_seconds / SECONDS_PER_DAY))
    return 0.001657 * math.sin(g + 0.01671 * math.sin(g))


def utc_to_tdb(dt: datetime) -> float:
    """UTC datetime -> TDB seconds past J2000."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    epoch_2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    utc_seconds = (dt - epoch_2000).total_seconds()
    tt = utc_seconds + tai_minus_utc(dt) + TT_MINUS_TAI
    return tt + _tdb_minus_tt(tt)


def tdb_to_utc(tdb: float) -> datetime:
    """TDB seconds past J2000 -> UTC datetime (inverse of utc_to_tdb)."""
    from datetime import timedelta

    epoch_2000 = datetime(2000, 1, 1, 12, tzinfo=timezone.utc)
    guess = epoch_2000 + timedelta(seconds=tdb - 69.184)
    for _ in range(3):
        guess = guess + timedelta(seconds=tdb - utc_to_tdb(guess))
    return guess


def days(n: float) -> float:
    return n * SECONDS_PER_DAY
