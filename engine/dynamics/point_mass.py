"""Central-body point-mass gravity."""

from __future__ import annotations

import numpy as np

from ..core.constants import body as get_body
from .base import DynamicsContext, ForceModel


class PointMassGravity(ForceModel):
    def __init__(self, body: str, gm: float | None = None):
        self.body = body.upper()
        self.gm = gm if gm is not None else get_body(self.body).gm
        self.name = f"{self.body.lower()}_point_mass"

    def acceleration(self, t, r, v, ctx: DynamicsContext) -> np.ndarray:
        rn = np.linalg.norm(r)
        return -self.gm * r / rn**3

    def potential(self, t, r, ctx) -> float:
        return -self.gm / np.linalg.norm(r)

    def describe(self):
        return {**super().describe(), "body": self.body, "gm": self.gm}
