"""The polar slope map (engine/surface/slope_map.py): its normals are build_thermal.py's local_normal,
stored and decoded within the int16 resolution, and a uniformly tilted map gives back its tilt."""

import importlib.util
import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from engine.surface.slope_map import block_centre, block_of, decode, encode, normals_at, slope_deg  # noqa: E402
from engine.surface.terrain import PolarGrid  # noqa: E402
from test_orientation import LBL  # noqa: E402


def _bt():
    spec = importlib.util.spec_from_file_location("build_thermal", ROOT / "scripts" / "build_thermal.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _map(folder: Path, h: np.ndarray, scale_m: float = 120.0) -> PolarGrid:
    n = h.shape[0]
    (folder / "S.LBL").write_text(LBL.format(rb=2 * n, n=n, name="S", c=(n - 1) / 2, clat=-90.0)
                                  .replace("MAP_SCALE = 300", f"MAP_SCALE = {scale_m:g}"))
    np.round(h / 0.5).astype("<i2").tofile(folder / "S.IMG")
    return PolarGrid.load(folder / "S.IMG")


def test_normals_are_local_normal_and_survive_storage():
    bt = _bt()
    n = 801
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        dem = _map(Path(tmp), 700 * np.sin(xx / 37) * np.cos(yy / 23) + 200 * np.sin((xx + yy) / 9))
        rng = np.random.default_rng(3)
        bi, bj = rng.integers(5, n // 2 - 5, 200), rng.integers(5, n // 2 - 5, 200)
        lc, sc = block_centre(bi, bj)
        nv, lat, lon = normals_at(dem, lc, sc)
        for k in range(0, 200, 10):
            want = bt.local_normal(dem, float(lat[k]), float(lon[k]))
            assert np.degrees(np.arccos(np.clip(nv[k] @ want, -1, 1))) < 1e-6
        back = decode(encode(nv, lat, lon), lat, lon)
        err = np.degrees(np.arccos(np.clip(np.sum(back * nv, 1), -1, 1)))
        assert err.max() < 0.005
        b2i, b2j = block_of(dem, lat, lon)                 # the centre lies in its own block
        assert (b2i == bi).all() and (b2j == bj).all()
        dem.close()


def test_tilted_plane():
    """A plane rising 1 m per 120 m pixel along the map's lines tilts the ground by atan(1/120) ~ 0.477 deg."""
    n = 401
    yy, _ = np.mgrid[0:n, 0:n].astype(float)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        dem = _map(Path(tmp), 1.0 * yy)
        lc, sc = block_centre(np.array([60, 100, 140]), np.array([100, 80, 120]))
        nv, lat, lon = normals_at(dem, lc, sc)
        s = slope_deg(nv, lat, lon)
        # the map holds radii, so a constant map is the sphere (slope 0); the stereographic scale (~1.00001 here) is negligible
        assert np.allclose(s, np.degrees(np.arctan(1 / 120)), atol=0.05), s
        dem.close()
