"""Work the API hands to its worker processes.

Each worker builds its own base ephemeris once (SPICE kernels are per-process),
then tabulates a short CachedEphemeris window per request, which keeps every
request independent and fast.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from engine.core.time import tdb_to_utc, utc_to_tdb
from engine.database import landing_entry, table_entry, trajectory_payload
from engine.ephemeris import CachedEphemeris
from engine.mission import TransferDesigner, TransferSpec, design_transfer
from engine.mission.transfer import CONTROL_KEYS
from engine.surface import SITES, LandingConstraints, analyze_many, arrival_from_row

DAY = 86_400.0
_BASE = None          # base provider (SPICE or analytic), or a loaded CachedEphemeris
_FIXED_CACHE = None   # set when the server runs from a saved .npz table


class RequestError(ValueError):
    """Invalid request parameters (HTTP 400)."""


def init_worker(use_spice: bool, ephem_cache: str | None) -> None:
    global _BASE, _FIXED_CACHE
    if ephem_cache:
        _FIXED_CACHE = CachedEphemeris.load(ephem_cache)
        _BASE = _FIXED_CACHE
    else:
        from engine.ephemeris.factory import base_ephemeris
        _BASE = base_ephemeris(use_spice)


def _window_cache(start: float, end: float) -> CachedEphemeris:
    if _FIXED_CACHE is not None:
        if not _FIXED_CACHE.covers(start, end):
            raise RequestError(
                f"The loaded ephemeris table covers {tdb_to_utc(_FIXED_CACHE.t0):%Y-%m-%d} to "
                f"{tdb_to_utc(_FIXED_CACHE.t1):%Y-%m-%d}; pick a date inside it"
            )
        return _FIXED_CACHE
    return CachedEphemeris.build(_BASE, start, end)


# --- parameter handling ---------------------------------------------------------------
def _number(params: dict, key: str, default=None, lo=None, hi=None) -> float:
    value = params.get(key, default)
    if value is None:
        raise RequestError(f"'{key}' is required")
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise RequestError(f"'{key}' must be a number") from None
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise RequestError(f"'{key}' must be between {lo} and {hi}")
    return value


def _tli_epoch(params: dict) -> float:
    if params.get("tli_epoch") is not None:
        return _number(params, "tli_epoch")
    text = params.get("tli_utc")
    if not text:
        raise RequestError("'tli_utc' is required, e.g. 2026-01-10T00:00")
    try:
        dt = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        raise RequestError(f"'tli_utc' is not an ISO date-time: {text!r}") from None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    if not 1950 <= dt.year <= 2149:
        raise RequestError("'tli_utc' must be between 1950 and 2149 (DE440 coverage)")
    return utc_to_tdb(dt)


def spec_from_params(params: dict) -> TransferSpec:
    family = int(_number(params, "family", 1))
    if family not in (1, -1):
        raise RequestError("'family' must be 1 (south pass) or -1 (north pass)")
    return TransferSpec(
        tli_epoch=_tli_epoch(params),
        tof_days=_number(params, "tof_days", None, 3.0, 14.0),
        family=family,
        lunar_inc_deg=_number(params, "lunar_inc_deg", 90.0, 0.0, 180.0),
        periselene_alt_km=_number(params, "periselene_alt_km", params.get("target_alt_km", 100.0), 15.0, 5000.0),
    )


def constraints_from_params(params: dict) -> LandingConstraints:
    return LandingConstraints(
        max_wait_days=_number(params, "max_wait_days", 30.0, 1.0, 60.0),
        max_plane_change_ms=_number(params, "max_plane_change_ms", 150.0, 0.0, 2000.0),
    )


# --- jobs ---------------------------------------------------------------------------
def design(params: dict) -> dict:
    """Design one transfer and analyse landings at every catalogue site."""
    tic = time.perf_counter()
    spec = spec_from_params(params)
    c = constraints_from_params(params)
    end = spec.tli_epoch + (spec.tof_days + c.max_wait_days + c.daylight_horizon_days + 4) * DAY
    cache = _window_cache(spec.tli_epoch - 16 * DAY, end)
    sol = design_transfer(cache, spec)
    row = sol.to_row()
    stamp = row["tli_utc"][:16].replace("-", "").replace(":", "")
    tid = f"live-{stamp}_t{spec.tof_days:05.2f}_{'p' if spec.family > 0 else 'm'}_i{spec.lunar_inc_deg:g}".replace(".", "")
    out = {
        "converged": sol.converged,
        "ephemeris": cache.name,
        "residuals": (sol.stage_b or sol.stage_a).residuals,
    }
    if not sol.converged:
        out["message"] = ("The targeting did not converge for this date and transit time. "
                          "Try a transit time between 4 and 8 days or the other approach.")
        out["solve_seconds"] = round(time.perf_counter() - tic, 2)
        return out

    entry = table_entry(row, tid)
    traj = trajectory_payload(TransferDesigner(cache, spec), {k: row[k] for k in CONTROL_KEYS}, cache)
    traj["id"] = tid
    entry["has_trajectory"] = True
    results, timelines = analyze_many(cache, [arrival_from_row(row)], SITES, c)
    out.update(
        row=entry,
        trajectory=traj,
        landings={sid: landing_entry(lst[0]) for sid, lst in results.items()},
        landing_details={sid: lst[0].to_dict() for sid, lst in results.items()},
        series={sid: tl.sun_series(every=12) for sid, tl in timelines.items()},
        solve_seconds=round(time.perf_counter() - tic, 2),
    )
    return out


def trajectory(params: dict) -> dict:
    """Re-propagate a stored transfer from its controls (for paths not exported)."""
    spec = spec_from_params(params)
    controls = params.get("controls")
    if not isinstance(controls, list) or len(controls) != len(CONTROL_KEYS):
        raise RequestError(f"'controls' must be a list of {len(CONTROL_KEYS)} numbers {list(CONTROL_KEYS)}")
    cache = _window_cache(spec.tli_epoch - 16 * DAY, spec.tli_epoch + (spec.tof_days + 17) * DAY)
    payload = trajectory_payload(TransferDesigner(cache, spec), dict(zip(CONTROL_KEYS, map(float, controls))), cache)
    payload["id"] = params.get("id", "")
    return payload
