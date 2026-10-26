"""From the capture orbit to the surface: when can the lander go down at a site?

After LOI the spacecraft sits in a low lunar orbit whose plane is (almost) fixed
in inertial space while the Moon turns underneath it once every 27.3 days.
A site therefore passes through the orbit plane twice per sidereal month; in
between, reaching it needs a plane change. The landing is also constrained by
light and communications:

    * Sun elevation at the site within the site's window, Sun rising
      (a morning landing leaves the most daylight for surface operations);
    * Earth above the local horizon (direct-to-Earth link during descent),
      unless the site relies on a relay satellite;
    * at least `min_coast_days` of checkout in orbit, at most `max_wait_days`.

For every instant on a time grid the analysis computes the plane-change angle
needed to bring the site into the orbit plane, and picks the earliest instant
whose cost is within `prefer_within_ms` of the cheapest feasible one.

Model limits (stated in the UI): flat local horizon, orbit plane drift from the
lunar J2 secular term only (third-body and higher zonal drift ignored), descent
delta-v from a Hohmann-like deorbit plus a powered-descent loss factor, the
in-orbit phasing (< one ~2 h revolution) ignored.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

from ..core.constants import BODIES
from ..core.time import tdb_to_utc
from ..ephemeris.cached import CachedEphemeris
from .geometry import earth_az_el_deg, local_frame, sun_az_el_deg
from .sites import LandingSite
from .ground import dsn_mask, site_from_earth_km, station_names
from .terrain import SOLAR_SEMI_DIAMETER_DEG, load_horizon

MOON = BODIES["MOON"]
DAY = 86_400.0


@dataclass
class LandingConstraints:
    min_coast_days: float = 1.0          # checkout in lunar orbit before descent
    max_wait_days: float = 30.0
    max_plane_change_ms: float = 150.0   # ~5.3 deg at 100 km
    min_earth_elev_deg: float = 2.0
    step_minutes: float = 10.0
    descent_perilune_alt_km: float = 15.0
    descent_loss_factor: float = 1.06    # gravity / steering losses of the braking burn
    descent_margin_ms: float = 60.0      # terminal descent, hover, hazard avoidance
    daylight_horizon_days: float = 16.0  # how far ahead to look for sunset
    prefer_within_ms: float = 10.0       # earliest option within this of the cheapest
    use_terrain: bool = True             # measure Sun / Earth above the LOLA horizon where a mask exists
    min_daylight_days: float = 0.0       # require this much sunlight after touchdown (0 = no requirement)
    require_dsn: bool = False            # touchdown in view of a NASA DSN station (10 deg mask)
    energy_window_days: float = 5.0      # first days on the surface for the energy budget

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ArrivalState:
    """What the landing analysis needs to know about a transfer."""
    arrival_epoch: float      # LOI (periselene) epoch, TDB s
    h_hat: np.ndarray         # capture-orbit normal, J2000
    orbit_alt_km: float
    inc_deg: float            # w.r.t. the lunar equator (for the J2 node drift)
    loi_ms: float


@dataclass
class LandingResult:
    site_id: str
    feasible: bool
    reason: str = ""
    code: str = ""                         # "", "sun", "earth", "daylight" or "plane" (why infeasible)
    landing_epoch: float | None = None
    wait_days: float | None = None
    plane_change_deg: float | None = None
    plane_change_ms: float | None = None
    descent_ms: float = 0.0
    surface_dv_ms: float | None = None     # plane change + descent
    total_from_loi_ms: float | None = None  # LOI + plane change + descent
    sun_elev_deg: float | None = None      # above the local horizontal plane
    earth_elev_deg: float | None = None
    sun_horizon_deg: float | None = None   # terrain horizon in the Sun's direction (0 = flat)
    earth_horizon_deg: float | None = None
    daylight_days: float | None = None     # Sun above the horizon after touchdown
    daylight_capped: bool = False          # daylight lasts at least the look-ahead
    best_plane_change_ms: float | None = None  # cheapest when light & comms allow, even over budget
    dsn: int = 0                           # DSN stations seeing the site at touchdown (bitmask)
    energy_pct: float | None = None        # solar disc above the terrain over the first days, % of full Sun
    max_dark_gap_h: float | None = None    # longest stretch with the Sun hidden in those days

    @property
    def dsn_stations(self) -> list[str]:
        return station_names(self.dsn)

    @property
    def landing_utc(self) -> str | None:
        return None if self.landing_epoch is None else tdb_to_utc(self.landing_epoch).isoformat(timespec="minutes")

    def to_dict(self) -> dict:
        d = asdict(self)
        d["landing_utc"] = self.landing_utc
        d["dsn_stations"] = self.dsn_stations
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}


# --- delta-v models --------------------------------------------------------------
def circular_speed_kms(alt_km: float) -> float:
    return float(np.sqrt(MOON.gm / (MOON.radius + alt_km)))


def plane_change_ms(angle_deg, alt_km: float):
    """Single impulsive plane change of `angle_deg` in a circular orbit."""
    return 2.0 * circular_speed_kms(alt_km) * np.sin(np.radians(angle_deg) / 2.0) * 1000.0


def descent_delta_v_ms(orbit_alt_km: float, c: LandingConstraints) -> float:
    """Deorbit to a low perilune, then brake to zero (with losses) and land."""
    r1, r2 = MOON.radius + orbit_alt_km, MOON.radius + c.descent_perilune_alt_km
    a = 0.5 * (r1 + r2)
    v_circ = np.sqrt(MOON.gm / r1)
    v_apo = np.sqrt(MOON.gm * (2 / r1 - 1 / a))
    v_peri = np.sqrt(MOON.gm * (2 / r2 - 1 / a))
    return float(((v_circ - v_apo) + v_peri * c.descent_loss_factor) * 1000.0 + c.descent_margin_ms)


def node_rate_rad_s(alt_km: float, inc_deg: float) -> float:
    """Secular nodal regression of a circular lunar orbit from J2."""
    a = MOON.radius + alt_km
    n = np.sqrt(MOON.gm / a**3)
    return float(-1.5 * n * MOON.zonals[2] * (MOON.radius / a) ** 2 * np.cos(np.radians(inc_deg)))


# --- per-site timelines ---------------------------------------------------------
@dataclass
class SiteTimeline:
    """Site direction, Sun and Earth elevation on a uniform grid.

    sun_el / earth_el are measured from the local horizontal plane; sun_hz /
    earth_hz are the terrain horizon in those directions (zeros without a mask).
    Every light and comms rule uses the clearance above the terrain."""
    site: LandingSite
    ts: np.ndarray
    up: np.ndarray
    sun_el: np.ndarray
    earth_el: np.ndarray
    ok: np.ndarray = field(repr=False)        # light & comms constraints both met
    sun_ok: np.ndarray = field(repr=False)
    sun_hz: np.ndarray = field(default=None, repr=False)
    earth_hz: np.ndarray = field(default=None, repr=False)
    terrain: str | None = None                # horizon source, None = flat horizon
    dsn: np.ndarray = field(default=None, repr=False)   # DSN stations in view (bitmask)

    def __post_init__(self):
        if self.sun_hz is None:
            self.sun_hz = np.zeros_like(self.sun_el)
        if self.earth_hz is None:
            self.earth_hz = np.zeros_like(self.earth_el)
        if self.dsn is None:
            self.dsn = np.zeros(len(self.ts), dtype=np.int8)

    @property
    def sun_clear(self) -> np.ndarray:
        """Sun centre above the terrain horizon (deg)."""
        return self.sun_el - self.sun_hz

    def disc_fraction(self) -> np.ndarray:
        """Share of the solar disc above the terrain horizon (0 hidden .. 1 full Sun)."""
        x = np.clip(self.sun_clear / SOLAR_SEMI_DIAMETER_DEG, -1.0, 1.0)
        th = np.arccos(-x)
        return (th - np.sin(th) * np.cos(th)) / np.pi

    def energy(self, i: int, days: float) -> tuple[float, float]:
        """(% of full Sun, longest dark gap in hours) over `days` from grid index i."""
        step = self.ts[1] - self.ts[0]
        n = max(1, int(round(days * DAY / step)))
        f = self.disc_fraction()[i:i + n]
        dark = np.concatenate([[False], f <= 0.0, [False]])
        edges = np.flatnonzero(np.diff(dark.astype(np.int8)))
        gap = int((edges[1::2] - edges[::2]).max()) if edges.size else 0
        return float(100.0 * f.mean()), float(gap * step / 3600.0)

    def daylight_left_days(self) -> np.ndarray:
        """Days of continuous sunlight from each grid instant (to the end of the grid if it never sets)."""
        if getattr(self, "_daylight", None) is None:
            n = len(self.ts)
            dark = self.sun_clear < 0
            nxt = np.where(dark, np.arange(n), n)
            nxt = np.minimum.accumulate(nxt[::-1])[::-1]          # index of the next dark sample
            self._daylight = (nxt - np.arange(n)) * (self.ts[1] - self.ts[0]) / DAY
        return self._daylight

    @classmethod
    def build(cls, cache: CachedEphemeris, site: LandingSite, start: float, end: float,
              c: LandingConstraints) -> "SiteTimeline":
        step = c.step_minutes * 60.0
        ts = start + step * np.arange(int(np.ceil((end - start) / step)) + 1)
        frame = local_frame(cache, site, ts)
        sun_az, sun = sun_az_el_deg(cache, site, ts, frame)
        earth_az, earth = earth_az_el_deg(cache, site, ts, frame)
        mask = load_horizon(site.horizon) if (c.use_terrain and site.horizon) else None
        sun_hz = mask.elevation(sun_az) if mask else np.zeros_like(sun)
        earth_hz = mask.elevation(earth_az) if mask else np.zeros_like(earth)
        sun_ok = (sun - sun_hz >= site.sun_min_deg) & (sun <= site.sun_max_deg)
        if site.sun_rising:
            sun_ok &= np.gradient(sun) > 0
        earth_ok = np.ones_like(sun_ok) if site.requires_relay else (earth - earth_hz) >= c.min_earth_elev_deg
        dsn = dsn_mask(ts, site_from_earth_km(cache, ts, frame[0]))
        ok = sun_ok & earth_ok
        if c.require_dsn:
            ok &= dsn > 0
        return cls(site, ts, frame[0], sun, earth, ok, sun_ok, sun_hz, earth_hz,
                   mask.source if mask else None, dsn)

    def index(self, t: float) -> int:
        return int(round((t - self.ts[0]) / (self.ts[1] - self.ts[0])))

    def sun_series(self, every: int = 12) -> dict:
        """Down-sampled Sun elevation for charts (default every 2 h at 10 min steps)."""
        out = {"t0": float(self.ts[0]), "step_s": float((self.ts[1] - self.ts[0]) * every),
               "sun_el_deg": np.round(self.sun_el[::every], 2).tolist()}
        if self.terrain:
            out["horizon_deg"] = np.round(self.sun_hz[::every], 2).tolist()
            out["terrain"] = self.terrain
        return out


@dataclass
class Opportunities:
    """Every candidate descent instant between the end of checkout and the end of the wait."""
    i0: int                   # index of ts[0] in the site timeline
    ts: np.ndarray            # TDB s
    angle_deg: np.ndarray     # plane change needed to bring the site into the orbit plane
    plane_ms: np.ndarray
    ok: np.ndarray            # light and comms allow a landing
    sun_ok: np.ndarray

    def landable(self, budget_ms: float) -> np.ndarray:
        return self.ok & (self.plane_ms <= budget_ms)


def opportunities(arrival: ArrivalState, tl: SiteTimeline, c: LandingConstraints, pole: np.ndarray) -> Opportunities:
    i0 = tl.index(arrival.arrival_epoch + c.min_coast_days * DAY)
    i1 = tl.index(arrival.arrival_epoch + c.max_wait_days * DAY)
    if i0 < 0 or i1 >= len(tl.ts):
        raise ValueError(f"Site timeline for {tl.site.id} does not cover this arrival; widen the window")
    sl = slice(i0, i1 + 1)
    ts, up = tl.ts[sl], tl.up[sl]

    # Orbit normal drifting with the J2 node regression around the lunar pole (Rodrigues).
    theta = node_rate_rad_s(arrival.orbit_alt_km, arrival.inc_deg) * (ts - arrival.arrival_epoch)
    h0 = arrival.h_hat / np.linalg.norm(arrival.h_hat)
    k = pole / np.linalg.norm(pole)
    cth, sth = np.cos(theta)[:, None], np.sin(theta)[:, None]
    h = h0 * cth + np.cross(k, h0) * sth + k * np.dot(k, h0) * (1 - cth)

    angle = np.degrees(np.arcsin(np.clip(np.abs(np.sum(h * up, axis=1)), 0, 1)))
    return Opportunities(i0, ts, angle, plane_change_ms(angle, arrival.orbit_alt_km), tl.ok[sl], tl.sun_ok[sl])


def intervals(ts: np.ndarray, mask: np.ndarray) -> list[tuple[float, float]]:
    """[start, end] of every run of True in `mask` (sampled at `ts`)."""
    m = np.concatenate([[False], np.asarray(mask, bool), [False]])
    edges = np.flatnonzero(np.diff(m.astype(np.int8)))
    return [(float(ts[a]), float(ts[b - 1])) for a, b in zip(edges[::2], edges[1::2])]


def analyze(arrival: ArrivalState, tl: SiteTimeline, c: LandingConstraints, pole: np.ndarray) -> LandingResult:
    site = tl.site
    descent = descent_delta_v_ms(arrival.orbit_alt_km, c)
    op = opportunities(arrival, tl, c, pole)
    i0, ts, angle, pc, ok = op.i0, op.ts, op.angle_deg, op.plane_ms, op.ok
    res = LandingResult(site.id, False, descent_ms=descent)

    if not ok.any():
        if not op.sun_ok.any():
            res.code, res.reason = "sun", "The Sun never stands in the landing window during the wait"
        else:
            res.code, res.reason = "earth", "Earth is below the horizon whenever the light is right"
        return res
    if c.min_daylight_days > 0:
        enough = tl.daylight_left_days()[i0:i0 + len(ts)] >= c.min_daylight_days
        if not (ok & enough).any():
            res.code = "daylight"
            res.reason = f"No landing slot leaves {c.min_daylight_days:g} days of sunlight before sunset"
            return res
        ok = ok & enough
    best = float(pc[ok].min())
    res.best_plane_change_ms = best
    if best > c.max_plane_change_ms:
        res.code = "plane"
        res.reason = f"Needs a {best:.0f} m/s plane change, over the {c.max_plane_change_ms:.0f} m/s budget"
        return res

    pick = ok & (pc <= min(c.max_plane_change_ms, best + c.prefer_within_ms))
    j = int(np.argmax(pick))
    gi = i0 + j
    after = tl.sun_clear[gi:]                 # Sun centre above the terrain horizon
    dark = np.nonzero(after < 0)[0]
    step_days = (tl.ts[1] - tl.ts[0]) / DAY
    res.feasible = True
    res.landing_epoch = float(ts[j])
    res.wait_days = float((ts[j] - arrival.arrival_epoch) / DAY)
    res.plane_change_deg = float(angle[j])
    res.plane_change_ms = float(pc[j])
    res.surface_dv_ms = float(pc[j] + descent)
    res.total_from_loi_ms = float(arrival.loi_ms + pc[j] + descent)
    res.sun_elev_deg = float(tl.sun_el[gi])
    res.earth_elev_deg = float(tl.earth_el[gi])
    res.sun_horizon_deg = float(tl.sun_hz[gi])
    res.earth_horizon_deg = float(tl.earth_hz[gi])
    res.dsn = int(tl.dsn[gi])
    res.energy_pct, res.max_dark_gap_h = tl.energy(gi, c.energy_window_days)
    if dark.size:
        res.daylight_days = float(dark[0] * step_days)
    else:
        res.daylight_days, res.daylight_capped = float(len(after) * step_days), True
    return res


def analysis_window(arrival_epochs, c: LandingConstraints) -> tuple[float, float]:
    """Ephemeris span a landing analysis of these arrivals needs."""
    a = np.asarray(arrival_epochs, float)
    return float(a.min() + c.min_coast_days * DAY - 3600.0), \
        float(a.max() + (c.max_wait_days + c.daylight_horizon_days + 1.0) * DAY)


def analyze_many(cache: CachedEphemeris, arrivals: list[ArrivalState], sites: list[LandingSite],
                 c: LandingConstraints | None = None) -> tuple[dict[str, list[LandingResult]], dict[str, SiteTimeline]]:
    """Landing analysis for every (arrival, site) pair. Returns results by site id
    (aligned with `arrivals`) and the site timelines (for Sun-elevation charts)."""
    c = c or LandingConstraints()
    start, end = analysis_window([a.arrival_epoch for a in arrivals], c)
    timelines = {s.id: SiteTimeline.build(cache, s, start, end, c) for s in sites}
    poles = [cache.pole("MOON", a.arrival_epoch) for a in arrivals]
    out = {s.id: [analyze(a, timelines[s.id], c, p) for a, p in zip(arrivals, poles)] for s in sites}
    return out, timelines


def arrival_from_row(row: dict) -> ArrivalState:
    """ArrivalState from a solution-database row (CSV values may be strings)."""
    f = lambda k: float(row[k])  # noqa: E731
    return ArrivalState(
        arrival_epoch=f("arrival_epoch"),
        h_hat=np.array([f("cap_hx"), f("cap_hy"), f("cap_hz")]),
        orbit_alt_km=f("periselene_alt_km"),
        inc_deg=f("lunar_inc_deg"),
        loi_ms=f("loi_dv_ms"),
    )
