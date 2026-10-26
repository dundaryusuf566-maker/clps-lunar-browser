"""Minimal test runner for environments without pytest:  python tests/run_all.py

The `if __name__ == "__main__"` guard matters on Windows: worker processes
(the API test starts a process pool) are spawned by re-importing this file, and
without the guard each worker would run the whole suite and exit, which kills
the pool ("BrokenProcessPool").
"""

import importlib
import sys
import time
import traceback
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main(pattern: str = "test_*.py") -> int:
    passed, failed, skipped = 0, [], 0
    start = time.perf_counter()
    for path in sorted((ROOT / "tests").glob(pattern)):
        module = importlib.import_module(path.stem)
        for name in sorted(n for n in dir(module) if n.startswith("test_")):
            t0 = time.perf_counter()
            try:
                getattr(module, name)()
                passed += 1
                print(f"  PASS  {path.stem}::{name}  ({time.perf_counter() - t0:.2f}s)", flush=True)
            except unittest.SkipTest as exc:
                skipped += 1
                print(f"  SKIP  {path.stem}::{name}  ({exc})", flush=True)
            except Exception:
                failed.append(f"{path.stem}::{name}")
                print(f"  FAIL  {path.stem}::{name}", flush=True)
                traceback.print_exc()
                sys.stderr.flush()

    print(f"\n{passed} passed, {len(failed)} failed, {skipped} skipped in {time.perf_counter() - start:.1f}s")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "test_*.py"))
