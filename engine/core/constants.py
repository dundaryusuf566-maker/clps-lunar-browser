"""Physical constants and body definitions (km, s units)."""

from __future__ import annotations

from dataclasses import dataclass, field


AU_KM = 149_597_870.7
SPEED_OF_LIGHT_KM_S = 299_792.458
# Solar radiation pressure at 1 AU, N/m^2 (= solar flux / c).
SOLAR_PRESSURE_1AU = 4.56e-6
SECONDS_PER_DAY = 86_400.0
OBLIQUITY_J2000_DEG = 23.43928


@dataclass(frozen=True)
class Body:
    name: str
    gm: float                     # km^3/s^2
    radius: float                 # mean equatorial radius, km
    # Unnormalized zonal coefficients {n: Jn}. Placeholder low-degree values;
    # the high-fidelity lunar field (GRAIL GL0660B) is loaded separately.
    zonals: dict[int, float] = field(default_factory=dict)
    spice_id: int | None = None


BODIES: dict[str, Body] = {
    "SUN": Body("SUN", gm=1.32712440018e11, radius=695_700.0, spice_id=10),
    "EARTH": Body(
        "EARTH",
        gm=398_600.4418,
        radius=6_378.1366,
        zonals={2: 1.08262668e-3, 3: -2.53265649e-6, 4: -1.61962159e-6},
        spice_id=399,
    ),
    "MOON": Body(
        "MOON",
        gm=4_902.800066,
        radius=1_738.0,
        # Approximate unnormalized lunar zonals. Good enough for frozen-orbit
        # behaviour studies; replace with GRAIL field for flight-grade work.
        zonals={2: 2.0330e-4, 3: 8.476e-6, 4: -9.59e-6, 5: 7.15e-7, 6: -1.36e-5, 7: -2.15e-5},
        spice_id=301,
    ),
}


def body(name: str) -> Body:
    try:
        return BODIES[name.upper()]
    except KeyError as exc:
        raise KeyError(f"Unknown body '{name}'. Known: {sorted(BODIES)}") from exc
