"""Download the LOLA south-polar terrain and NASA's illumination map into data/terrain/.

    python scripts/download_terrain.py            # ~233 MB, skips files already present
    python scripts/download_terrain.py --fine     # also the 60 m elevation map (+465 MB)
    python scripts/download_terrain.py --north    # also the north polar elevation map (+116 MB)
    python scripts/download_terrain.py --force    # re-download everything

Files (PDS Geosciences Node, LRO LOLA):
    ldem_75s_120m.img/.lbl            elevation, 75-90 S, 120 m/pixel        (data/lola_gdr/polar/img)
    avgvisib_75s_120m_201608.img/.lbl average solar illumination on the same
                                      grid (Mazarico et al. 2011), used only to
                                      check our horizons                     (extras/illumination/img)
    ldem_75s_60m.img/.lbl  (--fine)   elevation at 60 m/pixel, for checking
                                      that the horizons do not depend on resolution
    ldem_75n_120m.img/.lbl (--north)  elevation, 75-90 N, 120 m/pixel; check its orientation with
                                      scripts/check_polar_orientation.py --pole north before use
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
from pathlib import Path

PDS = "https://pds-geosciences.wustl.edu/lro/lro-l-lola-3-rdr-v1/lrolol_1xxx"
DEM = f"{PDS}/data/lola_gdr/polar/img"
ILL = f"{PDS}/extras/illumination/img"
FILES = {
    "ldem_75s_120m.lbl": f"{DEM}/ldem_75s_120m.lbl",
    "ldem_75s_120m.img": f"{DEM}/ldem_75s_120m.img",
    "avgvisib_75s_120m_201608.lbl": f"{ILL}/avgvisib_75s_120m_201608.lbl",
    "avgvisib_75s_120m_201608.img": f"{ILL}/avgvisib_75s_120m_201608.img",
}
FINE = {
    "ldem_75s_60m.lbl": f"{DEM}/ldem_75s_60m.lbl",
    "ldem_75s_60m.img": f"{DEM}/ldem_75s_60m.img",
}
NORTH = {
    "ldem_75n_120m.lbl": f"{DEM}/ldem_75n_120m.lbl",
    "ldem_75n_120m.img": f"{DEM}/ldem_75n_120m.img",
}
SIZES = {"ldem_75n_120m.img": 116_250_752, "ldem_75s_120m.img": 116_250_752, "avgvisib_75s_120m_201608.img": 116_250_752,
         "ldem_75s_60m.img": 465_003_008}
DEST = Path(__file__).resolve().parents[1] / "data" / "terrain"


def _progress(name: str):
    def hook(blocks: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100.0, 100.0 * blocks * block_size / total)
            sys.stdout.write(f"\r  {name:<32} {pct:5.1f}%  ({total / 1e6:.0f} MB)")
            sys.stdout.flush()
    return hook


def complete(path: Path) -> bool:
    return path.exists() and path.stat().st_size > 0 and path.stat().st_size >= SIZES.get(path.name, 1)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fine", action="store_true", help="also download the 60 m/pixel elevation map (465 MB)")
    ap.add_argument("--north", action="store_true", help="also download the north polar elevation map (116 MB)")
    ap.add_argument("--force", action="store_true", help="re-download files that already exist")
    args = ap.parse_args()

    DEST.mkdir(parents=True, exist_ok=True)
    files = {**FILES, **(FINE if args.fine else {}), **(NORTH if args.north else {})}
    print(f"LOLA terrain -> {DEST}")
    failures = []
    for name, url in files.items():
        target = DEST / name
        if complete(target) and not args.force:
            print(f"  {name:<32} already present, skipping")
            continue
        tmp = target.with_suffix(target.suffix + ".part")
        try:
            urllib.request.urlretrieve(url, tmp, _progress(name))
            tmp.replace(target)
            print()
        except Exception as exc:  # network errors, 404s
            print(f"\n  {name:<32} FAILED: {exc}")
            tmp.unlink(missing_ok=True)
            failures.append(name)
    if failures:
        print(f"\n{len(failures)} file(s) failed: {', '.join(failures)}")
        print("Run the command again (finished files are kept) or download them from the URLs in this script.")
        return 1
    print("\nTerrain ready. Next:  python scripts/build_horizons.py --spice")
    return 0


if __name__ == "__main__":
    sys.exit(main())
