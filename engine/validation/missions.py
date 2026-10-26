"""Flown CLPS missions used to test the browser against reality.

Only what the operators and NASA published goes in here; every value carries
its source. Times are UTC. Where a time had to be derived (TLI from the launch
timeline, periselene from the end of the LOI burn) the derivation is noted and
its uncertainty is far below the analysis step (10 min) or a day.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..surface.sites import LandingSite


@dataclass(frozen=True)
class MissionRecord:
    id: str
    name: str
    site_id: str                      # browser site with these coordinates
    site_name: str
    lat_deg: float
    lon_deg: float
    launch_utc: str
    tli_utc: str                      # derived, see tli_note
    tli_note: str
    loi_utc: str                      # periselene of the LOI burn (derived, see loi_note)
    loi_note: str
    landing_utc: str
    surface_end_utc: str | None
    surface_end_note: str
    orbit_alt_km: float               # capture orbit used for the reconstruction
    orbit_note: str
    loi_dv_ms: float | None           # reported LOI delta-v
    launch_windows: tuple[tuple[str, str, str], ...]  # (first day, last day, note)
    sources: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    # the browser's lighting rule for the site (as in engine/surface/sites.py)
    region: str = "South polar"
    sun_min_deg: float = 0.5
    sun_max_deg: float = 90.0
    # mission-specific inputs, each published before the landing (see the notes)
    max_wait_days: float | None = None           # None: the IM-1/IM-2 limit (retrodiction.MISSION_CONSTRAINTS)
    wait_note: str = ""
    recon_incs: tuple[float, ...] | None = None  # capture inclinations tried (None: near-polar 80-100)
    scan_incs: tuple[float, ...] | None = None
    scan_note: str = ""                          # why the launch-window question does or does not apply
    # derived real sunset after touchdown, for the sunset check (None: no such check)
    sunset_utc: str | None = None
    sunset_note: str = ""
    sunset_tol_h: float = 3.0

    @property
    def polar(self) -> bool:
        return abs(self.lat_deg) >= 75.0

    def site(self) -> LandingSite:
        """The real landing point, with the browser's illumination window for that kind of site."""
        return LandingSite(f"{self.id}-touchdown", self.site_name, self.lat_deg, self.lon_deg, self.region,
                           self.name, self.sources[0][1] if self.sources else "", sun_min_deg=self.sun_min_deg,
                           sun_max_deg=self.sun_max_deg, horizon=self.site_id if self.polar else None)

    def to_dict(self) -> dict:
        return asdict(self)


IM1 = MissionRecord(
    id="im-1", name="IM-1 Odysseus (Intuitive Machines, CLPS)",
    site_id="malapert-a", site_name="Malapert A", lat_deg=-80.13, lon_deg=1.44,
    launch_utc="2024-02-15T06:05:37Z",
    tli_utc="2024-02-15T06:48:10Z",
    tli_note="Falcon 9 second-stage burn ended at T+00:42:33 (launch timeline); the stage put Odysseus on its translunar path.",
    loi_utc="2024-02-21T15:16:36Z",
    loi_note="408 s LOI burn reported complete at 09:20 CST (15:20 UTC); periselene taken at mid-burn.",
    landing_utc="2024-02-22T23:23:53Z",
    surface_end_utc="2024-02-29T00:00:00Z",
    surface_end_note="Lander powered down on 29 February at the onset of local night (date only). It landed tipped over, so its panels saw less Sun than an upright lander would.",
    orbit_alt_km=92.0,
    orbit_note="92 km circular lunar orbit (reported). Inclination not published; polar assumed.",
    loi_dv_ms=800.0,
    launch_windows=(
        ("2024-01-12", "2024-01-14", "Original multi-day window opening 12 January (Intuitive Machines, 27 Oct 2023); the launch slipped to the next month's window when SpaceX rescheduled."),
        ("2024-02-14", "2024-02-16", "Three-day window, 14 February primary, 15 and 16 backup (SpaceX, 5 Feb 2024). Launched 15 February."),
    ),
    sources=(
        ("IM-1 mission timeline", "https://en.wikipedia.org/wiki/IM-1"),
        ("LOI burn and 92 km orbit", "https://spacepolicyonline.com/news/im-1-enters-lunar-orbit-moon-landing-tomorrow/"),
        ("LOI 800 m/s, landing 23:24 UTC", "https://spaceflightnow.com/2024/02/21/intuitive-machines-moon-lander-odysseus-reaches-lunar-orbit/"),
        ("Launch timeline (SECO-2, deployment)", "https://everydayastronaut.com/im-1-nova-c-odysseus-falcon-9-block-5/"),
        ("February window: 14, 15, 16", "https://spacepolicyonline.com/news/a-valentines-day-launch-for-the-next-u-s-moon-mission/"),
        ("January window opening 12 January", "https://spacepolicyonline.com/events/launch-of-intuitive-machines-nova-c-lunar-lander-jan-12-2024-fl/"),
    ),
)

IM2 = MissionRecord(
    id="im-2", name="IM-2 Athena (Intuitive Machines, CLPS)",
    site_id="mons-mouton", site_name="Mons Mouton", lat_deg=-84.7906, lon_deg=29.1957,
    launch_utc="2025-02-27T00:16:30Z",
    tli_utc="2025-02-27T00:55:00Z",
    tli_note="Athena was deployed about 45 minutes after launch, already on its translunar path; TLI taken a few minutes earlier (±10 min).",
    loi_utc="2025-03-03T12:22:54Z",
    loi_note="492 s LOI burn reported complete at 06:27 CST (12:27 UTC); periselene taken at mid-burn.",
    landing_utc="2025-03-06T17:28:50Z",
    surface_end_utc="2025-03-07T06:15:00Z",
    surface_end_note="Last contact 7 March: the lander came to rest on its side in a crater and its batteries ran down. This end is not a lighting limit.",
    orbit_alt_km=100.0,
    orbit_note="Circular orbit with a ~2 h period (reported), about 100-120 km; 100 km polar assumed.",
    loi_dv_ms=None,
    launch_windows=(
        ("2025-02-26", "2025-03-01", "Four-day window opening no earlier than 26 February (Intuitive Machines). Launched 27 February."),
    ),
    sources=(
        ("IM-2 mission timeline", "https://en.wikipedia.org/wiki/IM-2"),
        ("LOI burn time, orbit period", "https://intuitivemachines.com/im-2"),
        ("Four-day window from 26 February", "https://www.space.com/the-universe/moon/private-athena-moon-lander-arrives-in-florida-ahead-of-feb-26-spacex-launch"),
    ),
)

BG1 = MissionRecord(
    id="blue-ghost-1", name="Blue Ghost Mission 1 (Firefly Aerospace, CLPS)",
    site_id="mare-crisium", site_name="Mare Crisium, Mons Latreille", lat_deg=18.56, lon_deg=61.81,
    launch_utc="2025-01-15T06:11:39Z",
    tli_utc="2025-02-08T12:00:00Z",
    tli_note="Firefly reported the TLI burn on 8 February 2025 without a time (after 25 days in Earth orbit); noon UTC "
             "assumed, +-12 h. It only sets the transit time of the reconstructed transfer; the landing analysis starts "
             "from the LOI below.",
    loi_utc="2025-02-14T01:53:08Z",
    loi_note="4 min 15 s LOI burn starting 7:51 pm CST on 13 February (01:51 UTC on 14 February); periselene taken at "
             "mid-burn.",
    landing_utc="2025-03-02T08:34:00Z",
    surface_end_utc="2025-03-16T23:15:00Z",
    surface_end_note="Final data around 6:15 pm CDT on 16 March, just over 5 hours into the lunar night: the solar-powered "
                     "lander ran its batteries down after sunset, as planned. More than 14 days on the surface, 346 hours "
                     "of daylight.",
    orbit_alt_km=100.0,
    orbit_note="Elliptical capture orbit, lowered to ~120 km on 18 February and to a near-circular orbit with a 100 km "
               "perilune on 24 February (Firefly). 100 km circular assumed. Inclination not published: 22-158 deg tried.",
    loi_dv_ms=None,
    launch_windows=(),
    region="Near side", sun_min_deg=3.0, sun_max_deg=20.0,
    max_wait_days=20.0,
    wait_note="Firefly planned 16 days in lunar orbit for checkout before descent (announced at LOI, 16 February). "
              "The browser may wait up to 20 days, enough not to cut its search; its rule still takes the earliest "
              "feasible option, so the limit does not choose the day.",
    recon_incs=tuple(float(i) for i in range(22, 159, 4)),          # 22-158 deg, 90 (polar) included
    scan_incs=(30.0, 60.0, 90.0, 120.0, 150.0),
    scan_note="Blue Ghost spent 25 days in Earth orbit between launch and TLI, so its launch day was not tied to the "
              "Moon's position and there is no launch window to predict. The TLI-day scan is shown for reference only.",
    sunset_utc="2025-03-16T18:30:00Z",
    sunset_note="Derived: 346 hours of daylight after the 08:34 UTC touchdown (Firefly, 17 March) put sunset at 18:34 UTC; "
                "the last data, 'just over 5 hours into the lunar night' at about 23:15 UTC, put it shortly before 18:15. "
                "Taken as 18:30 UTC, +-20 min. Pass if the browser's flat-horizon sunset is within 3 h (fixed before the "
                "first run: 1 deg of unmodelled horizon moves sunset by ~2 h at this latitude).",
    sources=(
        ("Blue Ghost Mission 1 timeline", "https://en.wikipedia.org/wiki/Blue_Ghost_Mission_1"),
        ("Firefly live updates: burns, orbit, landing, end of mission", "https://fireflyspace.com/news/blue-ghost-mission-1-live-updates/"),
        ("LOI and 16 days of checkout in lunar orbit", "https://spaceflightnow.com/2025/02/16/fireflys-blue-ghost-lander-arrives-in-lunar-orbit/"),
    ),
)

MISSIONS: list[MissionRecord] = [IM1, IM2, BG1]


def get_mission(mission_id: str) -> MissionRecord:
    for m in MISSIONS:
        if m.id == mission_id:
            return m
    raise KeyError(f"Unknown mission '{mission_id}'. Known: {[m.id for m in MISSIONS]}")
