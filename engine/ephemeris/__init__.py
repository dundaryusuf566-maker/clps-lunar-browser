from .base import EphemerisProvider
from .analytic import AnalyticEphemeris
from .cached import CachedEphemeris
from . import iau_moon


def change_center(state, new_center: str, ephemeris: EphemerisProvider):
    """Re-express a State relative to another body (same inertial frame)."""
    from ..core.state import State

    offset = ephemeris.state(state.center, new_center, state.epoch)
    return State(state.epoch, state.vector + offset, new_center, state.frame)


__all__ = ["EphemerisProvider", "AnalyticEphemeris", "CachedEphemeris", "change_center"]
