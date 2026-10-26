"""CLPS Lunar Browser flight dynamics engine.

Conventions used everywhere in the engine:
    * Distance in km, time in s, velocity in km/s, GM in km^3/s^2.
    * Epochs are TDB seconds past J2000 (2000-01-01 12:00:00 TDB), stored as float.
    * States are 6-vectors [x, y, z, vx, vy, vz] in an inertial frame (ICRF/J2000)
      centered on a named body.
"""

__version__ = "0.19.1"
