"""Sweep TLI epoch x time of flight x family and write the solution space to CSV.

This is the seed of the solution database: one row per designed transfer.

    python scripts/sweep_transfers.py                              # small default sweep
    python scripts/sweep_transfers.py --start 2025-12-07 --end 2026-03-31 --step 3 \
        --tofs 4 6 8 10 12 --workers 8 --plot                      # Genova et al. (2024) window
    python scripts/sweep_transfers.py --spice ...                  # DE440 ephemeris
    python scripts/sweep_transfers.py --ephem-cache data/cache/ephem_spice_....npz ...

Rows are appended to the CSV as soon as each transfer finishes, and a re-run
with the same --out skips transfers that are already in the file. An
interrupted sweep therefore continues where it stopped (--fresh starts over,
--retry-failed re-runs the failed rows).

Ephemeris handling: by default the window needed by the sweep is tabulated once
(CachedEphemeris, 1 h Hermite grid) in the main process and every worker reads
that table instead of calling SPICE ~200 000 times per transfer. --ephem-cache
reuses a saved table (no SPICE needed); --no-cache queries the base directly.
"""

from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timedelta, timezone
from multiprocessing import Pool, cpu_count
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from engine.core.time import utc_to_tdb  # noqa: E402
from engine.mission import TransferSpec, design_transfer, row_fields  # noqa: E402

_EPH = None
DAY = 86_400.0
EXTRA_FIELDS = ["error", "ephemeris", "solve_seconds"]


def csv_fields() -> list[str]:
    return [*row_fields(), *EXTRA_FIELDS]


def _init_worker(use_spice: bool, cache_file: str | None) -> None:
    """Each process loads the shared table, or builds its own base provider
    (SPICE kernels are per-process)."""
    global _EPH
    if cache_file is not None:
        from engine.ephemeris import CachedEphemeris
        _EPH = CachedEphemeris.load(cache_file)
    else:
        from engine.ephemeris.factory import base_ephemeris
        _EPH = base_ephemeris(use_spice)


def _run(job: dict) -> dict:
    t0 = time.perf_counter()
    spec = TransferSpec(**job)
    try:
        row = design_transfer(_EPH, spec).to_row()
        row["error"] = ""
    except Exception as exc:  # keep the sweep going; record the failure
        row = {f"spec_{k}": v for k, v in job.items()}
        row.update(converged=False, error=f"{type(exc).__name__}: {exc}")
    row["ephemeris"] = _EPH.name
    row["solve_seconds"] = round(time.perf_counter() - t0, 2)
    return row


def job_key(spec_like: dict) -> tuple:
    """Identity of a transfer, from a job dict or a CSV row (spec_ columns)."""
    g = (lambda k: spec_like[k]) if "tli_epoch" in spec_like else (lambda k: spec_like[f"spec_{k}"])
    return (round(float(g("tli_epoch")), 1), round(float(g("tof_days")), 4), int(float(g("family"))),
            round(float(g("lunar_inc_deg")), 4), round(float(g("periselene_alt_km")), 4))


def sweep_window(jobs: list[dict]) -> tuple[float, float]:
    """TDB span every propagation in the sweep can touch (with margin)."""
    start = min(j["tli_epoch"] for j in jobs) - DAY
    end = max(j["tli_epoch"] + j["tof_days"] * DAY for j in jobs) + 5 * DAY
    return start, end


def build_jobs(start: str, end: str, step: float, tofs, families, lunar_inc: float = 90.0,
               periselene: float = 100.0, parking_inc: float = 28.5) -> list[dict]:
    day = datetime.fromisoformat(start).replace(tzinfo=timezone.utc)
    last = datetime.fromisoformat(end).replace(tzinfo=timezone.utc)
    jobs = []
    while day <= last:
        for tof in tofs:
            for fam in families:
                jobs.append(dict(tli_epoch=utc_to_tdb(day), tof_days=float(tof), family=int(fam),
                                 lunar_inc_deg=float(lunar_inc), periselene_alt_km=float(periselene),
                                 parking_inc_deg=float(parking_inc)))
        day += timedelta(days=step)
    return jobs


def read_rows(path: Path) -> list[dict]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="") as fh:
        return list(csv.DictReader(fh))


def run_sweep(jobs: list[dict], out: str | Path, workers: int, use_spice: bool = False,
              ephem_cache: str | None = None, no_cache: bool = False, fresh: bool = False,
              retry_failed: bool = False, quiet: bool = False) -> Path:
    """Design every job (skipping ones already in `out`) and append rows to `out`."""
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    fields = csv_fields()
    existing = [] if fresh else read_rows(out)
    if existing and set(existing[0]) != set(fields):
        raise SystemExit(
            f"{out} was written by an older version (different columns). "
            "Use --fresh to start a new file, or a different --out."
        )
    if retry_failed:
        existing = [r for r in existing if r.get("converged") == "True"]
    done = {job_key(r) for r in existing}
    todo = [j for j in jobs if job_key(j) not in done]
    print(f"{len(jobs)} transfers requested, {len(jobs) - len(todo)} already in {out.name}, {len(todo)} to design")

    # Rewrite the file when starting fresh or dropping failed rows; otherwise append.
    if fresh or retry_failed or not existing:
        with out.open("w", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=fields)
            w.writeheader()
            w.writerows(existing)
    if not todo:
        return out

    t0 = time.perf_counter()
    cache_file = None
    if not no_cache:
        from engine.ephemeris.factory import cached_for_window
        start, end = sweep_window(todo)
        cache = cached_for_window(use_spice, start, end, cache_path=ephem_cache)
        cache_file = ephem_cache or str(cache.save(out.with_name(f"_{out.stem}_ephemeris.npz")))
        print(f"ephemeris: {cache.name}, {cache.n} samples ({time.perf_counter() - t0:.1f} s)")
    print(f"designing on {workers} worker(s)...", flush=True)

    n_ok = 0
    with Pool(workers, initializer=_init_worker, initargs=(use_spice, cache_file)) as pool, \
            out.open("a", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        for i, row in enumerate(pool.imap_unordered(_run, todo), 1):
            w.writerow(row)
            fh.flush()
            n_ok += bool(row.get("converged"))
            if not quiet or i % 25 == 0 or i == len(todo):
                ok = "ok " if row.get("converged") else "FAIL"
                loi = f"LOI {row['loi_dv_ms']:6.1f} m/s" if row.get("loi_dv_ms") is not None else row.get("error", "")
                eta = (time.perf_counter() - t0) / i * (len(todo) - i) / 60
                print(f"  [{i:>5}/{len(todo)}] {ok} {row.get('tli_utc', '')[:10]} tof {float(row['spec_tof_days']):>5.2f} d "
                      f"fam {int(row['spec_family']):+d}  {loi}   eta {eta:5.1f} min", flush=True)

    # Tidy: sort the whole file by epoch, transit time, family.
    rows = read_rows(out)
    rows.sort(key=lambda r: (float(r["spec_tli_epoch"]), float(r["spec_tof_days"]), int(float(r["spec_family"]))))
    with out.open("w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    total_ok = sum(r.get("converged") == "True" for r in rows)
    print(f"\n{n_ok}/{len(todo)} new transfers converged in {(time.perf_counter() - t0) / 60:.1f} min; "
          f"{total_ok}/{len(rows)} in {out}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2026-01-01")
    ap.add_argument("--end", default="2026-01-29")
    ap.add_argument("--step", type=float, default=7.0, help="days between TLI epochs")
    ap.add_argument("--tofs", type=float, nargs="+", default=[4, 6, 8])
    ap.add_argument("--families", type=int, nargs="+", default=[1, -1])
    ap.add_argument("--lunar-inc", type=float, default=90.0)
    ap.add_argument("--periselene", type=float, default=100.0)
    ap.add_argument("--parking-inc", type=float, default=28.5)
    ap.add_argument("--workers", type=int, default=max(1, cpu_count() - 1))
    ap.add_argument("--spice", action="store_true")
    ap.add_argument("--ephem-cache", default=None, help="saved CachedEphemeris .npz to use (no SPICE needed)")
    ap.add_argument("--no-cache", action="store_true", help="query the base ephemeris directly (slow)")
    ap.add_argument("--fresh", action="store_true", help="ignore rows already in --out and start over")
    ap.add_argument("--retry-failed", action="store_true", help="re-run rows that did not converge")
    ap.add_argument("--quiet", action="store_true", help="print every 25th transfer only")
    ap.add_argument("--out", default=str(ROOT / "data" / "cache" / "transfers.csv"))
    ap.add_argument("--plot", action="store_true", help="also draw the LOI dv vs epoch chart")
    args = ap.parse_args()

    jobs = build_jobs(args.start, args.end, args.step, args.tofs, args.families,
                      args.lunar_inc, args.periselene, args.parking_inc)
    out = run_sweep(jobs, args.out, args.workers, args.spice, args.ephem_cache, args.no_cache,
                    args.fresh, args.retry_failed, args.quiet)
    if args.plot:
        from plot_solution_space import plot_loi_vs_epoch
        png = out.with_suffix(".png")
        plot_loi_vs_epoch(out, png)
        print(f"chart -> {png}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
