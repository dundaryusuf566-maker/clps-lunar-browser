from .base import DynamicsContext, ForceModel, SpacecraftProperties
from .composer import DynamicsModel
from .harmonics import ZonalHarmonics
from .point_mass import PointMassGravity
from .srp import SolarRadiationPressure
from .third_body import ThirdBodyGravity

__all__ = [
    "DynamicsContext", "ForceModel", "SpacecraftProperties", "DynamicsModel",
    "PointMassGravity", "ZonalHarmonics", "ThirdBodyGravity", "SolarRadiationPressure",
    "earth_moon_model",
]


def earth_moon_model(central: str, ephemeris, fidelity: str = "medium", spacecraft=None) -> DynamicsModel:
    """Ready-made force configurations.

    low:    central point mass + other primary as third body
    medium: + central zonals (J2-J4) + Sun third body
    high:   + full zonal set + SRP
    """
    central = central.upper()
    other = "MOON" if central == "EARTH" else "EARTH"
    forces: list[ForceModel] = [PointMassGravity(central), ThirdBodyGravity(other)]
    if fidelity in ("medium", "high"):
        forces += [ZonalHarmonics(central, degree=4 if fidelity == "medium" else None), ThirdBodyGravity("SUN")]
    if fidelity == "high":
        forces.append(SolarRadiationPressure())
    return DynamicsModel(central, ephemeris, forces, spacecraft or SpacecraftProperties())
