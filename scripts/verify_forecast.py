"""Check that a registered forecast has not been changed since it was registered.

    python scripts/verify_forecast.py                       # web/public/data/forecast.json
    python scripts/verify_forecast.py path/to/forecast.json

Recomputes the SHA-256 of the forecast content and compares it with the one
stored at registration (and published in the commit that added the file).
"""

import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "web" / "public" / "data" / "forecast.json"
    d = json.loads(path.read_text())
    content = {k: d[k] for k in ("mission", "time", "region")}
    digest = hashlib.sha256(json.dumps(content, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    meta = d["meta"]
    ok = digest == meta["sha256"]
    print(f"{path.name}: registered {meta['registered_utc']} (engine {meta['engine_version']}, {meta['ephemeris']})")
    print(f"  stored   {meta['sha256']}\n  computed {digest}\n  -> {'unchanged' if ok else 'CHANGED since registration'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
