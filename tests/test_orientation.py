"""The polar map orientation check (scripts/check_polar_orientation.py): on synthetic maps with the named
craters carved where a known reading puts them, exactly that reading must pass, at either pole."""

import sys
import tempfile
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_polar_orientation import CRATERS, READINGS, check  # noqa: E402

from engine.surface.terrain import PolarGrid  # noqa: E402

LBL = """PDS_VERSION_ID = PDS3
RECORD_TYPE = FIXED_LENGTH
RECORD_BYTES = {rb}
FILE_RECORDS = {n}
^IMAGE = "{name}.IMG"
OBJECT = IMAGE
  LINES = {n}
  LINE_SAMPLES = {n}
  SAMPLE_TYPE = LSB_INTEGER
  SAMPLE_BITS = 16
  SCALING_FACTOR = 0.5
  OFFSET = 1737400.0
END_OBJECT = IMAGE
OBJECT = IMAGE_MAP_PROJECTION
  MAP_PROJECTION_TYPE = "POLAR STEREOGRAPHIC"
  A_AXIS_RADIUS = 1737.4 <KM>
  CENTER_LATITUDE = {clat} <DEG>
  CENTER_LONGITUDE = 0.0 <DEG>
  LINE_PROJECTION_OFFSET = {c} <PIXEL>
  SAMPLE_PROJECTION_OFFSET = {c} <PIXEL>
  MAP_SCALE = 300 <METERS/PIXEL>
END_OBJECT = IMAGE_MAP_PROJECTION
END
"""


def _map(folder: Path, pole: str, truth: tuple[float, float], n: int = 1901) -> PolarGrid:
    yy, xx = np.mgrid[0:n, 0:n].astype(float)
    h = 300 * np.sin(xx / 97) * np.cos(yy / 131)
    g = PolarGrid(Path("x"), n, n, 300.0, (n - 1) / 2, (n - 1) / 2, 1737400.0, 1.0, 0.0, np.zeros((1, 1)),
                  x_sign=truth[0], y_sign=truth[1], pole=1.0 if pole == "north" else -1.0)
    for _, la, lo, dk in CRATERS[pole]:
        li, si = g.pixel(la, lo)
        d = np.hypot(yy - li, xx - si) / (dk / 2 * 1000 / 300.0)
        h += np.where(d < 1, -2500 * (1 - d ** 2), 0) + 400 * np.exp(-((d - 1.05) / 0.12) ** 2)
    name = f"O_{pole}_{int(truth[0])}_{int(truth[1])}".replace("-", "m")
    (folder / f"{name}.LBL").write_text(LBL.format(rb=2 * n, n=n, name=name, c=(n - 1) / 2,
                                                   clat=90.0 if pole == "north" else -90.0))
    np.round(h / 0.5).astype("<i2").tofile(folder / f"{name}.IMG")
    return PolarGrid.load(folder / f"{name}.IMG")


def test_named_craters_single_out_the_reading():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        for pole in ("north", "south"):
            for truth in READINGS:
                g = _map(Path(tmp), pole, truth)
                passing = [(r["x_sign"], r["y_sign"]) for r in check(g, CRATERS[pole]) if r["pass"]]
                g.close()
                assert passing == [truth], (pole, truth, passing)


def test_north_projection_round_trip():
    """pixel() and latlon() invert each other at the north pole as at the south."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        g = _map(Path(tmp), "north", (1.0, 1.0), n=301)
        lat = np.array([89.9, 88.0, 85.5, 84.0])
        lon = np.array([10.0, -120.0, 170.0, 75.0])
        li, si = g.pixel(lat, lon)
        la2, lo2 = g.latlon(li, si)
        assert np.allclose(la2, lat, atol=1e-9) and np.allclose(((lo2 - lon + 180) % 360) - 180, 0, atol=1e-9)
        assert g.pole == 1.0 and np.all(la2 > 0)
        g.close()
