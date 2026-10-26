"""Third-body point-mass perturbation (direct + indirect term).

    a = GM_b * ( d / |d|^3  -  r_b / |r_b|^3 ),   d = r_b - r

r_b is the perturbing body relative to the central body. The second term is the
acceleration of the central body itself (we integrate in a non-rotating frame
attached to it, which is accelerating).
"""

from __future__ import annotations

import numpy as np

from ..core.constants import body as get_body
from .base import DynamicsContext, ForceModel


class ThirdBodyGravity(ForceModel):
    def __init__(self, body: str, gm: float | None = None):
        self.body = body.upper()
        self.gm = gm if gm is not None else get_body(self.body).gm
        self.name = f"{self.body.lower()}_third_body"

    def acceleration(self, t, r, v, ctx: DynamicsContext) -> np.ndarray:
        if self.body == ctx.central_body:
            raise ValueError(f"{self.name}: body is the central body")
        rb = ctx.body_position(self.body, t)
        d = rb - r
        return self.gm * (d / np.linalg.norm(d) ** 3 - rb / np.linalg.norm(rb) ** 3)

    def describe(self):
        return {**super().describe(), "body": self.body, "gm": self.gm}
