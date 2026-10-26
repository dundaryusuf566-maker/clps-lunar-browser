"""CLPS missions that have not flown yet, with what has been announced and what we assume.

Everything announced carries a source. Everything we had to assume is listed
separately, so a reader can tell the two apart.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from ..surface.sites import LandingSite


@dataclass(frozen=True)
class UpcomingMission:
    id: str
    name: str
    operator: str
    announced: tuple[tuple[str, str], ...]          # (statement, source URL)
    assumptions: tuple[str, ...]
    reference_name: str                             # the point the time forecast is made for
    reference_lat: float
    reference_lon: float
    horizon: str | None                             # terrain mask of the reference point
    tli_first: str                                  # TLI dates scanned
    tli_last: str
    min_daylight_days: float                        # surface operations the operator announced
    region_center: tuple[float, float]              # (lat, lon) of the region scan
    region_half_km: float
    region_step_km: float
    landing_first: str                              # landing period the region is scored over
    landing_last: str
    sources: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    energy_window_days: float = 14.0                # energy budget over one lunar day after touchdown

    def site(self) -> LandingSite:
        return LandingSite(f"{self.id}-reference", self.reference_name, self.reference_lat, self.reference_lon,
                           "South polar", self.name, self.sources[0][1] if self.sources else "",
                           sun_min_deg=0.5, sun_max_deg=90.0, horizon=self.horizon)

    def to_dict(self) -> dict:
        return asdict(self)


_HOODLINE = "https://hoodline.com/2026/10/pittsburgh-built-griffin-1-moon-lander-heads-home-before-late-2026-launch/"
_SFN = "https://spaceflightnow.com/2026/06/16/astrobotic-showcases-griffin-1-lander-ahead-of-environmental-testing-in-california/"
_WIKI = "https://en.wikipedia.org/wiki/Griffin_Mission_One"
_SPACENEWS_VIPER = "https://spacenews.com/nasa-picks-landing-site-for-viper-lunar-rover/"
_MOUTON = "https://en.wikipedia.org/wiki/Mons_Mouton"

GRIFFIN1 = UpcomingMission(
    id="griffin-1",
    name="Griffin Mission One (Astrobotic, CLPS)",
    operator="Astrobotic",
    announced=(
        ("Launch on a SpaceX Falcon Heavy in the fourth quarter of 2026; no specific date announced (June 2026).", _SFN),
        ("Launch targeted for late 2026 (October 2026).", _HOODLINE),
        ("Scheduled for launch no earlier than November 2026.", _WIKI),
        ("Target: the Nobile crater region near Mons Mouton, at the lunar south pole.", _WIKI),
        ("Mission objective: a soft landing followed by at least five Earth days of surface operations.", _HOODLINE),
        ("Main payload: Astrolab's FLIP rover.", _SFN),
    ),
    assumptions=(
        "No landing point has been published. The time forecast uses the point where IM-2 Athena touched down on "
        "Mons Mouton (84.7906 S, 29.1957 E) as a stand-in; the region scan covers the wider Mons Mouton - Nobile area.",
        "Trajectory not published: a direct transfer of 4 to 7 days into a 100 km near-polar orbit (80-100 deg), "
        "landing within 4 days of arrival, as tested on IM-1 and IM-2.",
        "Landing rule as tested on IM-1 and IM-2: Sun 0.5 deg above the LOLA terrain horizon and rising, Earth 2 deg "
        "above it, plane change within 150 m/s; plus the announced five days of sunlight after touchdown.",
        "TLI dates scanned from 1 November 2026 to 28 February 2027, so the forecast still holds if the launch slips.",
        "Solar energy is the share of the solar disc above the terrain over one lunar day (14 days) after touchdown; "
        "panel orientation and efficiency are not modelled.",
    ),
    reference_name="Mons Mouton (IM-2 touchdown point)",
    reference_lat=-84.7906, reference_lon=29.1957, horizon="mons-mouton",
    tli_first="2026-11-01", tli_last="2027-02-28",
    min_daylight_days=5.0,
    region_center=(-84.95, 38.0), region_half_km=40.0, region_step_km=2.0,
    landing_first="2026-11-05", landing_last="2027-03-12",
    sources=(
        ("Griffin Mission One", _WIKI),
        ("Fourth-quarter 2026 launch, FLIP rover", _SFN),
        ("Late 2026 launch, five days of surface operations", _HOODLINE),
        ("Mons Mouton coordinates; IM-2 touchdown point", _MOUTON),
        ("NASA's VIPER site criteria: Earth visibility, illumination, slopes", _SPACENEWS_VIPER),
    ),
)

UPCOMING: list[UpcomingMission] = [GRIFFIN1]


def get_upcoming(mission_id: str) -> UpcomingMission:
    for m in UPCOMING:
        if m.id == mission_id:
            return m
    raise KeyError(f"Unknown upcoming mission '{mission_id}'. Known: {[m.id for m in UPCOMING]}")
