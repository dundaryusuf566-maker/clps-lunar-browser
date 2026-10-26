"""LOI delta-v vs TLI epoch, coloured by time of flight (the Lunar Browser view).

    python scripts/plot_solution_space.py data/cache/transfers.csv [out.png]

Requires matplotlib (pip install matplotlib).
"""

from __future__ import annotations

import csv
import sys
from datetime import datetime
from pathlib import Path

# Single-hue sequential ramp (light -> dark = short -> long flight).
_RAMP = ["#86b6ef", "#6da7ec", "#5598e7", "#3987e5", "#2a78d6", "#256abf", "#1c5cab", "#184f95", "#104281", "#0d366b"]
_SURFACE, _INK, _INK_2, _GRID = "#fcfcfb", "#0b0b0b", "#52514e", "#e6e5e0"


def load(path: Path) -> list[dict]:
    with Path(path).open() as fh:
        return [r for r in csv.DictReader(fh) if r.get("converged") == "True" and r.get("loi_dv_ms")]


def plot_loi_vs_epoch(csv_path: Path, png_path: Path, title: str | None = None) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.dates as mdates
    import matplotlib.pyplot as plt
    from matplotlib.colors import LinearSegmentedColormap

    rows = load(csv_path)
    if not rows:
        raise SystemExit("No converged transfers in the CSV")
    dates = [datetime.fromisoformat(r["tli_utc"]) for r in rows]
    loi = [float(r["loi_dv_ms"]) for r in rows]
    tof = [float(r["tof_days"]) for r in rows]
    eph = rows[0].get("ephemeris", "?")

    cmap = LinearSegmentedColormap.from_list("tof", _RAMP)
    fig, ax = plt.subplots(figsize=(11, 5.2), dpi=150)
    fig.patch.set_facecolor(_SURFACE)
    ax.set_facecolor(_SURFACE)
    order = sorted(range(len(rows)), key=lambda i: tof[i])  # long flights drawn on top
    sc = ax.scatter([dates[i] for i in order], [loi[i] for i in order], c=[tof[i] for i in order],
                    cmap=cmap, s=34, linewidths=1.2, edgecolors=_SURFACE, zorder=3)
    cb = fig.colorbar(sc, ax=ax, pad=0.015)
    cb.set_label("TLI → LOI duration (days)", color=_INK_2)
    cb.outline.set_visible(False)
    cb.ax.tick_params(colors=_INK_2, length=0)

    ax.set_title(title or f"LOI Δv vs TLI epoch  ·  100 km polar capture  ·  ephemeris: {eph}",
                 loc="left", color=_INK, fontsize=12, pad=12)
    ax.set_ylabel("LOI Δv (m/s)", color=_INK_2)
    ax.set_xlabel("TLI epoch (UTC)", color=_INK_2)
    ax.grid(True, color=_GRID, linewidth=0.8, zorder=0)
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %d\n%Y"))
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)
    ax.spines["bottom"].set_color(_GRID)
    ax.tick_params(colors=_INK_2, length=0)
    fig.tight_layout()
    fig.savefig(png_path, facecolor=_SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("data/cache/transfers.csv")
    dst = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".png")
    plot_loi_vs_epoch(src, dst)
    print(f"chart -> {dst}")
