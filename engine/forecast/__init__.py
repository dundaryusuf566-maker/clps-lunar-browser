"""Forecasts for CLPS missions that have not flown yet: when and where they can land.

A forecast is made with exactly the rules that were tested on flown missions
(engine/validation/retrodiction.py) and registered with a timestamp and a hash
before the mission flies, so it can be checked afterwards.
"""

from .region import REGION_RULES, RegionGrid, rank, region_metrics, slope_deg, slot_metrics
from .timing import forecast_constraints, forecast_jobs, time_forecast
from .upcoming import GRIFFIN1, UPCOMING, UpcomingMission, get_upcoming

__all__ = [
    "UpcomingMission", "UPCOMING", "GRIFFIN1", "get_upcoming",
    "forecast_jobs", "forecast_constraints", "time_forecast",
    "RegionGrid", "region_metrics", "slot_metrics", "slope_deg", "rank", "REGION_RULES",
]
