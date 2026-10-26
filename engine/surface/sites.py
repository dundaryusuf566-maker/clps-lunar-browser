"""Candidate landing sites: CLPS destinations plus a reference site.

Coordinates are selenographic (Mean Earth / polar axis), latitude north
positive, longitude east positive in [-180, 180]. Sources are listed per site.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np

MOON_MEAN_RADIUS_KM = 1737.4


@dataclass(frozen=True)
class LandingSite:
    id: str
    name: str
    lat_deg: float
    lon_deg: float
    region: str                      # "Near side", "Far side", "South polar"
    missions: str                    # who flew or will fly there
    source: str                      # where the coordinates come from
    requires_relay: bool = False     # Earth below the horizon: no direct-to-Earth link
    sun_min_deg: float = 3.0         # Sun elevation window at touchdown
    sun_max_deg: float = 20.0
    sun_rising: bool = True          # land in the local morning (maximises daylight)
    note: str = ""
    horizon: str | None = None       # terrain horizon mask (engine/surface/horizons/<name>.json)

    def unit_fixed(self) -> np.ndarray:
        """Unit vector to the site in the lunar body-fixed frame."""
        la, lo = np.radians(self.lat_deg), np.radians(self.lon_deg)
        return np.array([np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)])

    def to_dict(self) -> dict:
        return asdict(self)


_POLAR_NOTE = ("Near the pole the Sun stays within a few degrees of the horizon, so the surrounding relief "
               "decides illumination. With a LOLA horizon mask the Sun and Earth are measured above the real "
               "terrain horizon; without one, above a flat horizon.")

SITES: list[LandingSite] = [
    LandingSite(
        "apollo-11", "Tranquility Base", 0.67416, 23.47314, "Near side",
        "Apollo 11 (1969). Reference site for comparison.",
        "https://en.wikipedia.org/wiki/Apollo_11",
    ),
    LandingSite(
        "mare-crisium", "Mare Crisium, Mons Latreille", 18.56, 61.81, "Near side",
        "Firefly Blue Ghost Mission 1 (landed March 2025).",
        "https://en.wikipedia.org/wiki/Mons_Latreille",
    ),
    LandingSite(
        "reiner-gamma", "Reiner Gamma", 7.5, -59.0, "Near side",
        "Intuitive Machines IM-3, CLPS CP-11 (planned).",
        "https://en.wikipedia.org/wiki/Reiner_Gamma",
    ),
    LandingSite(
        "gruithuisen-gamma", "Mons Gruithuisen Gamma", 36.45715, -40.79602, "Near side",
        "Lunar-VISE on Firefly Blue Ghost 3, CLPS CP-21 (planned).",
        "https://www.usgs.gov/publications/lunar-vise-landing-site-selection-and-characterization-mons-gruithuisen-gamma",
    ),
    LandingSite(
        "malapert-a", "Malapert A", -80.13, 1.44, "South polar",
        "Intuitive Machines IM-1 Odysseus (landed February 2024).",
        "https://en.wikipedia.org/wiki/IM-1",
        sun_min_deg=0.5, sun_max_deg=90.0, note=_POLAR_NOTE, horizon="malapert-a",
    ),
    LandingSite(
        "mons-mouton", "Mons Mouton", -84.7906, 29.1957, "South polar",
        "Intuitive Machines IM-2 Athena (landed March 2025); CLPS CP-22 (planned).",
        "https://en.wikipedia.org/wiki/IM-2",
        sun_min_deg=0.5, sun_max_deg=90.0, note=_POLAR_NOTE, horizon="mons-mouton",
    ),
    LandingSite(
        "schrodinger", "Schrödinger basin (centre)", -75.0, 132.4, "Far side",
        "Was the target of Draper / ispace-U.S. APEX 1.0 (CLPS CP-12), cancelled in July 2026; kept as a far-side reference.",
        "https://en.wikipedia.org/wiki/Commercial_Lunar_Payload_Services",
        requires_relay=True, sun_min_deg=2.0, sun_max_deg=20.0,
        note="Basin centre, not a published landing ellipse. Earth is never in view: needs a relay satellite.",
    ),
]

_BY_ID = {s.id: s for s in SITES}


def get_site(site_id: str) -> LandingSite:
    try:
        return _BY_ID[site_id]
    except KeyError as exc:
        raise KeyError(f"Unknown site '{site_id}'. Known: {sorted(_BY_ID)}") from exc


def custom_site(lat_deg: float, lon_deg: float, name: str = "Custom site", **kw) -> LandingSite:
    lon = ((lon_deg + 180.0) % 360.0) - 180.0
    return LandingSite(f"custom-{lat_deg:.3f}-{lon:.3f}", name, lat_deg, lon, kw.pop("region", "Custom"),
                       kw.pop("missions", ""), kw.pop("source", ""), **kw)
