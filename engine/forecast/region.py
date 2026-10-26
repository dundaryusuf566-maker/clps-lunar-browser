"""Where: a suitability scan of a landing region.

A grid of points over the region; for each one, from the LOLA terrain and the
ephemeris, the three things NASA weighed when it chose VIPER's site on Mons
Mouton (illumination, Earth visibility, slopes; SpaceNews, 2021):

    * landing slots: instants in the landing period when the Sun is 0.5 deg
      above the terrain horizon and rising, Earth 2 deg above it, and the Sun
      then stays up for the mission's required days (the same rule as the time
      forecast and the IM-1 / IM-2 tests);
    * sunlight: the share of the period the Sun is above the terrain, and the
      longest stretch of sunlight that starts with a landing slot;
    * Earth: the share of the sunlit time with Earth above the terrain
      (direct-to-Earth link while the lander works);
    * slope of the surface over a 240 m baseline (two map pixels);
    * energy: the share of the solar disc above the terrain over one lunar day
      (14 days) after the best landing slot (100 % = the full Sun all the time),
      and the longest stretch with the Sun hidden in that time. Over the
      required days alone it would always be ~100 %, since a slot already
      demands continuous sunlight for them.

This ranks places by how well they meet these criteria. It is not a prediction
of the operator's choice, which also depends on metre-scale hazards (rocks,
small craters), payload goals and the lander's own rules that a 120 m map
cannot see.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..surface.terrain import SOLAR_SEMI_DIAMETER_DEG, PolarGrid, compute_horizon
from ..validation.illumination import az_el_fixed

DAY = 86_400.0
MOON_RADIUS_KM = 1737.4

REGION_RULES = {
    "sun_min_deg": 0.5,        # above the terrain horizon, rising (as in the landing analysis)
    "earth_min_deg": 2.0,      # above the terrain horizon
    "observer_m": 2.0,         # lander camera / solar panels
    "az_step_deg": 1.0,
    "max_dist_km": 200.0,
    "energy_window_days": 14.0,  # one lunar day: what a longer mission could collect after the required days
}


@dataclass(frozen=True)
class RegionGrid:
    """A square of points on the polar stereographic map plane, centred on a site."""
    center_lat: float
    center_lon: float
    half_km: float
    step_km: float

    def points(self, grid: PolarGrid) -> list[dict]:
        lc, sc = grid.pixel(self.center_lat, self.center_lon)
        x0 = (float(sc) - grid.sample_offset) * grid.map_scale_m
        y0 = (float(lc) - grid.line_offset) * grid.map_scale_m
        offs = np.arange(-self.half_km, self.half_km + 1e-9, self.step_km)
        out = []
        for j, dy in enumerate(offs):
            for i, dx in enumerate(offs):
                x, y = x0 + dx * 1000.0, y0 + dy * 1000.0
                lat, lon = grid.latlon(y / grid.map_scale_m + grid.line_offset, x / grid.map_scale_m + grid.sample_offset)
                out.append({"i": i, "j": j, "x_km": round(float(dx), 3), "y_km": round(float(dy), 3),
                            "lat": round(float(lat), 5), "lon": round(float(lon), 5)})
        return out


def slope_deg(grid: PolarGrid, lat: float, lon: float) -> float:
    """Surface slope from central differences one pixel either side (240 m baseline at 120 m/pixel)."""
    li, si = grid.pixel(lat, lon)
    s = grid.map_scale_m
    lat_e, lon_e = grid.latlon([li, li, li - 1, li + 1], [si + 1, si - 1, si, si])
    h = grid.value(lat_e, lon_e)
    gx, gy = (h[0] - h[1]) / (2 * s), (h[3] - h[2]) / (2 * s)
    return float(np.degrees(np.arctan(np.hypot(gx, gy))))


def _next_dark_days(lit: np.ndarray, step_s: float) -> tuple[np.ndarray, np.ndarray]:
    """Days of continuous sunlight from each sample; True where it lasts to the end of the series."""
    n = len(lit)
    nxt = np.where(~lit, np.arange(n), n)
    nxt = np.minimum.accumulate(nxt[::-1])[::-1]
    return (nxt - np.arange(n)) * step_s / DAY, nxt == n


def slot_metrics(mask, lat: float, lon: float, site_radius_km: float, ts: np.ndarray, sun_dirs: np.ndarray,
                 earth_fixed_km: np.ndarray, period: tuple[float, float], min_daylight_days: float,
                 rules: dict = REGION_RULES) -> dict:
    """Landing slots, sunlight and Earth visibility at one point over the landing period."""
    step = float(ts[1] - ts[0])
    az_s, el_s = az_el_fixed(lat, lon, sun_dirs)
    sun_clear = el_s - mask.elevation(az_s)
    p, l = np.radians(lat), np.radians(lon)
    up = np.array([np.cos(p) * np.cos(l), np.cos(p) * np.sin(l), np.sin(p)])
    e = earth_fixed_km - site_radius_km * up
    e /= np.linalg.norm(e, axis=1, keepdims=True)
    az_e, el_e = az_el_fixed(lat, lon, e)
    earth_ok = el_e - mask.elevation(az_e) >= rules["earth_min_deg"]

    lit = sun_clear > 0
    left, capped = _next_dark_days(lit, step)
    in_period = (ts >= period[0]) & (ts <= period[1])
    rising = np.gradient(el_s) > 0
    slot = in_period & (sun_clear >= rules["sun_min_deg"]) & rising & earth_ok & (left >= min_daylight_days)

    edges = np.flatnonzero(np.diff(np.concatenate([[0], slot.astype(np.int8), [0]])))
    runs = [(float(ts[a]), float(ts[b - 1])) for a, b in zip(edges[::2], edges[1::2])]
    out = {
        "slot_days": round(float(slot.sum() * step / DAY), 2),
        "opportunities": len(runs),
        "sunlit_pct": round(100 * float(lit[in_period].mean()), 1),
        "earth_when_lit_pct": round(100 * float((earth_ok & lit)[in_period].sum() / max(1, lit[in_period].sum())), 1),
        "best_daylight_days": None, "best_daylight_capped": False, "best_slot": None,
        "energy_pct": None, "max_dark_gap_h": None,
        "earth_after_best_pct": None, "first_slot": None, "runs": [[a, b] for a, b in runs[:12]],
    }
    if slot.any():
        k = int(np.argmax(np.where(slot, left, -1)))
        n_ops = max(1, int(round(min_daylight_days * DAY / step)))
        n_en = max(1, int(round(rules.get("energy_window_days", min_daylight_days) * DAY / step)))
        x = np.clip(sun_clear[k:k + n_en] / SOLAR_SEMI_DIAMETER_DEG, -1, 1)
        th = np.arccos(-x)
        frac = (th - np.sin(th) * np.cos(th)) / np.pi             # share of the solar disc above the terrain
        dark = np.concatenate([[False], frac <= 0, [False]])
        e2 = np.flatnonzero(np.diff(dark.astype(np.int8)))
        gap = int((e2[1::2] - e2[::2]).max()) if e2.size else 0
        out.update(
            best_daylight_days=round(float(left[k]), 2), best_daylight_capped=bool(capped[k]),
            best_slot=float(ts[k]), first_slot=float(ts[int(np.argmax(slot))]),
            earth_after_best_pct=round(100 * float(earth_ok[k:k + n_ops].mean()), 1),
            energy_pct=round(100 * float(frac.mean()), 1), max_dark_gap_h=round(gap * step / 3600, 1),
        )
    return out


def region_metrics(dem: PolarGrid, point: dict, ts: np.ndarray, sun_dirs: np.ndarray, earth_fixed_km: np.ndarray,
                   period: tuple[float, float], min_daylight_days: float, rules: dict = REGION_RULES) -> dict:
    """Everything the region map shows for one grid point."""
    lat, lon = point["lat"], point["lon"]
    mask = compute_horizon(dem, lat, lon, site="grid", observer_m=rules["observer_m"],
                           az_step_deg=rules["az_step_deg"], max_dist_km=rules["max_dist_km"])
    r_km = MOON_RADIUS_KM + (mask.site_height_m + rules["observer_m"]) / 1000.0
    m = slot_metrics(mask, lat, lon, r_km, ts, sun_dirs, earth_fixed_km, period, min_daylight_days, rules)
    return {**point, "height_m": round(mask.site_height_m), "slope_deg": round(slope_deg(dem, lat, lon), 2),
            "horizon_max_deg": round(float(mask.elev_deg.max()), 2),
            "horizon_mean_deg": round(float(mask.elev_deg.mean()), 2), **m}


def rank(points: list[dict], max_slope_deg: float = 10.0, min_earth_after_pct: float = 50.0, top: int = 10) -> list[dict]:
    """Points with a landing slot, slope and Earth link within limits, ranked by the sunlight
    their best slot leaves, then by the total slot time in the period."""
    ok = [p for p in points if p["best_daylight_days"] is not None and p["slope_deg"] <= max_slope_deg
          and (p["earth_after_best_pct"] or 0) >= min_earth_after_pct]
    ok.sort(key=lambda p: (-p["best_daylight_days"], -p["slot_days"], p["slope_deg"]))
    return ok[:top]
