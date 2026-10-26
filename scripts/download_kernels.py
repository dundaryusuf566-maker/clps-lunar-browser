"""Download the NASA NAIF SPICE kernels the engine needs into data/kernels/.

    python scripts/download_kernels.py            # ~44 MB, skips files already present
    python scripts/download_kernels.py --force    # re-download everything

Kernels (all from https://naif.jpl.nasa.gov/pub/naif/generic_kernels/):
    naif0012.tls               leap seconds
    de440s.bsp                 Sun / Earth / Moon ephemeris, 1849-2150
    pck00011.tpc               IAU body orientation and radii
    moon_pa_de440_200625.bpc   high-precision lunar orientation (MOON_PA frame)
    moon_de440_250416.tf       lunar frame definitions (MOON_PA / MOON_ME)
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

BASE = "https://naif.jpl.nasa.gov/pub/naif/generic_kernels"
KERNELS = {
    "naif0012.tls": f"{BASE}/lsk/naif0012.tls",
    "de440s.bsp": f"{BASE}/spk/planets/de440s.bsp",
    "pck00011.tpc": f"{BASE}/pck/pck00011.tpc",
    "moon_pa_de440_200625.bpc": f"{BASE}/pck/moon_pa_de440_200625.bpc",
    "moon_de440_250416.tf": f"{BASE}/fk/satellites/moon_de440_250416.tf",
}
DEST = Path(__file__).resolve().parents[1] / "data" / "kernels"


def _progress(name: str):
    def hook(blocks: int, block_size: int, total: int) -> None:
        done = blocks * block_size
        if total > 0:
            pct = min(100.0, 100.0 * done / total)
            sys.stdout.write(f"\r  {name:<28} {pct:5.1f}%  ({total / 1e6:.1f} MB)")
            sys.stdout.flush()
    return hook


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = parser.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    print(f"Kernels -> {DEST}")
    failures = []
    for name, url in KERNELS.items():
        target = DEST / name
        if target.exists() and target.stat().st_size > 0 and not args.force:
            print(f"  {name:<28} already present, skipping")
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, tmp, _progress(name))
            tmp.replace(target)
            print()
        except Exception as exc:  # network errors, 404s
            print(f"\n  {name:<28} FAILED: {exc}")
            tmp.unlink(missing_ok=True)
            failures.append(name)

    if failures:
        print(f"\n{len(failures)} kernel(s) failed: {', '.join(failures)}")
        print("Check your connection or download them manually from the URLs in this script.")
        return 1
    print("\nAll kernels ready. Verify with:  python scripts/check_spice.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
