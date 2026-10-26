"""The browser's regolith reference (web/tests/regolith_reference.json) is the current engine's answer.

If engine/surface/thermal.py changes, the committed file goes stale and the browser test would
compare against an old model: rerun scripts/build_regolith_reference.py.
"""

import importlib.util
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def test_reference_matches_engine():
    spec = importlib.util.spec_from_file_location("brr", ROOT / "scripts" / "build_regolith_reference.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fresh = mod.build()
    kept = json.loads((ROOT / "web" / "tests" / "regolith_reference.json").read_text())
    assert kept["meta"]["regolith"] == json.loads(json.dumps(fresh["meta"]["regolith"]))
    for a, b in zip(kept["cases"], fresh["cases"]):
        assert a["name"] == b["name"] and a["layers"] == b["layers"]
        assert np.allclose(a["F"], b["F"], rtol=0, atol=1e-9)
        assert np.max(np.abs(np.array(a["surface_k"]) - np.array(b["surface_k"]))) < 1e-6, \
            f"{a['name']}: rerun python scripts/build_regolith_reference.py"
