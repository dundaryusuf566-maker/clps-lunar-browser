"""High-fidelity ephemeris via NASA NAIF SPICE (spiceypy).

Kernels expected in data/kernels/ (see scripts/download_kernels.py):
    naif0012.tls                  leap seconds
    de440s.bsp                    planetary ephemeris
    pck00011.tpc                  body orientation (IAU_MOON)
    moon_pa_de440_200625.bpc      high-precision lunar orientation (MOON_PA)
    moon_de440_250416.tf          lunar frame definitions (MOON_ME / MOON_PA)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .base import EphemerisProvider

_BODY_FIXED = {"MOON": "MOON_PA", "EARTH": "ITRF93", "SUN": "IAU_SUN"}
_FALLBACK_FIXED = {"MOON": "IAU_MOON", "EARTH": "IAU_EARTH", "SUN": "IAU_SUN"}


class SpiceEphemeris(EphemerisProvider):
    name = "spice"

    def __init__(self, kernels: list[str | Path] | None = None, kernel_dir: str | Path = "data/kernels"):
        try:
            import spiceypy as sp
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise ImportError("SpiceEphemeris needs spiceypy: pip install spiceypy") from exc
        self._sp = sp
        if kernels is None:
            kernels = sorted(Path(kernel_dir).glob("*.*"))
            kernels = [k for k in kernels if k.suffix in {".tls", ".bsp", ".tpc", ".bpc", ".tf"}]
        if not kernels:
            raise FileNotFoundError(
                f"No SPICE kernels found in {kernel_dir}. Download them with: "
                "python scripts/download_kernels.py"
            )
        for k in kernels:
            sp.furnsh(str(k))

    def state(self, target: str, observer: str, epoch: float) -> np.ndarray:
        st, _ = self._sp.spkezr(target.upper(), epoch, "J2000", "NONE", observer.upper())
        return np.asarray(st, dtype=float)

    def _fixed_frame(self, body: str, epoch: float) -> np.ndarray:
        body = body.upper()
        for frame in (_BODY_FIXED.get(body), _FALLBACK_FIXED.get(body)):
            if frame is None:
                continue
            try:
                return np.asarray(self._sp.pxform("J2000", frame, epoch))
            except Exception:  # frame kernel not loaded -> try fallback
                continue
        raise KeyError(f"No body-fixed frame available for {body}")

    def body_fixed_rotation(self, body: str, epoch: float) -> np.ndarray:
        return self._fixed_frame(body, epoch)

    def pole(self, body: str, epoch: float) -> np.ndarray:
        return self._fixed_frame(body, epoch)[2]
