"""Engine answers for the browser's regolith model (web/tests/regolith_reference.json).

    python scripts/build_regolith_reference.py          (~10 s, no ephemeris, no map)

web/src/lib/regolith.ts is a line-for-line port of engine/surface/thermal.py. This script
runs the engine on made-up sunlight (nothing here depends on the ephemeris or the LOLA
map, so the file is the same on every machine and is kept in the repository), and
web/tests/regolith.check.mjs runs the browser model on the same sunlight and requires
the same temperatures (criterion in that file).

Cases:
  equator   build_thermal.py's Diviner check: level ground at the equator, 1 AU, a
            lunation in 1440 steps, 8 spin-up passes, then one more lunation.
  polar     a low Sun near a pole: elevation 1.0 +- 1.2 deg over a lunation, a 1.5 deg
            horizon cutting the disc, the Sun's distance varying; 4 spin-up passes on
            the first 30 days, then 60 days hourly.
  eclipse   a few days around noon at the equator in 5-minute steps with the Sun gone
            for 5 hours: spans shorter than the model's own time step, sudden cooling.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine import __version__  # noqa: E402
from engine.surface.scene3d import disc_fraction  # noqa: E402
from engine.surface.thermal import LUNATION_S, Column, Regolith, absorbed_flux  # noqa: E402

OUT = ROOT / "web" / "tests" / "regolith_reference.json"


def case(name, t, F, spin_t, spin_F, cycles, every, note):
    col = Column(1, Regolith())
    changes = col.spin_up(spin_t, spin_F[None, :], cycles=cycles)
    T = col.run(t, F[None, :])["surface"][0]
    keep = np.arange(0, len(t), every)
    return {"name": name, "note": note, "cycles": cycles,
            "spin_t": spin_t.tolist(), "spin_F": spin_F.tolist(), "t": t.tolist(), "F": F.tolist(),
            "spin_up_changes_k": changes, "keep": keep.tolist(), "surface_k": T[keep].tolist(),
            "layers": len(col.g.z), "first_layer_m": float(col.g.h[0]), "bottom_m": float(col.g.z[-1])}


def build() -> dict:
    r = Regolith()
    P = LUNATION_S
    cases = []

    t = np.arange(0, P + 1, P / 1440)
    F = absorbed_flux(np.cos(2 * np.pi * t / P), 1.0, 1.0, r)
    cases.append(case("equator", t, F, t, F, 8, 6, "level equator, 1 AU, as build_thermal.py's Diviner check"))

    hours = np.arange(0, 60 * 86400 + 1, 3600.0)
    el = 1.0 + 1.2 * np.sin(2 * np.pi * hours / P)
    au = 1.0 + 0.0167 * np.cos(2 * np.pi * hours / (365.25 * 86400))
    F = absorbed_flux(np.sin(np.radians(el)), disc_fraction(el - 1.5), au, r)
    spin = hours <= 30 * 86400
    cases.append(case("polar", hours, F, hours[spin], F[spin], 4, 4, "Sun 1.0 +- 1.2 deg, horizon 1.5 deg"))

    t = np.arange(-2 * 86400, 2 * 86400 + 1, 300.0)
    h = 2 * np.pi * t / P
    F = absorbed_flux(np.cos(h), 1.0, 1.0, r) * np.where((t > 3600) & (t < 6 * 3600), 0.0, 1.0)
    tl = np.arange(-P, 1.0, 3600.0) - 2 * 86400                    # a lunation ending where the case begins
    Fl = absorbed_flux(np.cos(2 * np.pi * tl / P), 1.0, 1.0, r)
    cases.append(case("eclipse", t, F, tl, Fl, 6, 3, "noon at the equator, Sun gone for 5 h, 5-minute steps"))

    return {"meta": {"engine_version": __version__, "source": "engine/surface/thermal.py", "regolith": r.to_dict()},
            "cases": cases}


def main() -> int:
    doc = build()
    OUT.write_text(json.dumps(doc, separators=(",", ":")))
    for c in doc["cases"]:
        T = np.array(c["surface_k"])
        print(f"  {c['name']:<8} {len(c['t']):5d} samples, {T.min():6.1f} .. {T.max():6.1f} K, "
              f"spin-up changes {', '.join(f'{x:.3f}' for x in c['spin_up_changes_k'])} K")
    print(f"-> {OUT} ({OUT.stat().st_size // 1024} kB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
