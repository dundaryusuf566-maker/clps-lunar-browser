"""Lunar terrain: LOLA polar elevation maps and the horizon they cast.

Near the poles the Sun skims the horizon, so whether a site is lit is decided by
the surrounding relief, not by a flat local horizon. This module reads the LOLA
polar stereographic grids (PDS3 .IMG + .LBL, e.g. LDEM_75S_120M) and computes,
for a site, the elevation angle of the terrain horizon in every direction
(a "horizon mask").

Grid conventions (LOLA polar products, south pole), from the LOLA map
projection description (DSMAP_POLAR.CAT) and the product labels:

    R = 2 * R_moon * tan(pi/4 + lat/2)          lat < 0, planetocentric
    x = R * sin(lon)                            lon east-positive
    y = -R * cos(lon)                           (inverse: lon = atan2(x, -y))
    sample = x / MAP_SCALE + SAMPLE_PROJECTION_OFFSET     0-based
    line   = y / MAP_SCALE + LINE_PROJECTION_OFFSET       0-based, line 0 at the top

so the 0 deg meridian points to the top of the image and 90 deg E to the right.
Values: DN * SCALING_FACTOR + OFFSET (for LDEM: planetary radius in metres).

The orientation (which way the map is read) is checked against named craters at their
IAU positions: scripts/check_polar_orientation.py. NASA's average illumination map
(engine/validation/illumination.py) checks the heights, the horizon geometry and the
distance from the pole, but cannot tell a mirrored or rotated reading: averaged over
18.6 years the Sun goes round the sky evenly.

Horizon geometry is exact on a sphere: a terrain point at angular distance d
from the site, with planetary radius r_t, rises above the site's local
horizontal plane by r_t cos(d) - r_s and lies r_t sin(d) away horizontally,
where r_s is the site radius plus the observer height.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import numpy as np

HORIZON_DIR = Path(__file__).resolve().parent / "horizons"
# North polar map: x = +R sin(lon), y = +R cos(lon) (0 deg at the bottom, 90 E to the right, the map seen
# from above the pole). Not yet confirmed: scripts/check_polar_orientation.py tests all four sign pairs
# against NASA's northern illumination map and says which one fits.
NORTH_SIGNS = (1.0, 1.0)
SOLAR_SEMI_DIAMETER_DEG = 0.2666   # mean, at 1 AU


# --- PDS3 labels ------------------------------------------------------------------
def parse_pds3_label(text: str) -> dict[str, str]:
    """KEY = VALUE pairs of a PDS3 label (first occurrence wins, units kept)."""
    out: dict[str, str] = {}
    for line in text.splitlines():
        m = re.match(r"^\s*(\^?[A-Z][A-Z0-9_:]*)\s*=\s*(.*?)\s*$", line)
        if m and m.group(1) not in out:
            out[m.group(1)] = m.group(2)
    return out


def _num(value: str) -> tuple[float, str]:
    """'120 <M/PIXEL>' -> (120.0, 'M/PIXEL')."""
    m = re.match(r'^"?\s*([-+0-9.eE]+)\s*"?\s*(?:<([^>]*)>)?', value)
    if not m:
        raise ValueError(f"not a number: {value!r}")
    return float(m.group(1)), (m.group(2) or "").upper()


def _metres(value: str) -> float:
    v, unit = _num(value)
    return v * 1000.0 if unit.startswith("KM") else v


def _find(base: Path, suffixes: tuple[str, ...]) -> Path:
    for s in suffixes:
        for cand in (base.with_suffix(s), base.with_suffix(s.upper())):
            if cand.exists():
                return cand
    raise FileNotFoundError(f"No {'/'.join(suffixes)} next to {base}")


@dataclass
class PolarGrid:
    """A LOLA polar stereographic raster (elevation or illumination map), south or north."""
    path: Path
    lines: int
    samples: int
    map_scale_m: float
    line_offset: float
    sample_offset: float
    radius_m: float
    scale: float
    offset: float
    data: np.ndarray = field(repr=False)
    name: str = ""
    # Projection signs: x = x_sign * R sin(lon), y = y_sign * R cos(lon). South: (+1, -1), checked
    # against NASA's illumination map (scripts/build_horizons.py). North: NORTH_SIGNS below, which
    # scripts/check_polar_orientation.py must confirm against the northern map before use.
    x_sign: float = 1.0
    y_sign: float = -1.0
    pole: float = -1.0              # -1 south, +1 north

    @classmethod
    def load(cls, img_path: str | Path) -> "PolarGrid":
        img = Path(img_path)
        lbl = _find(img, (".lbl",)) if img.suffix.lower() != ".lbl" else img
        if img.suffix.lower() == ".lbl":
            img = _find(lbl, (".img",))
        kv = parse_pds3_label(lbl.read_text(errors="replace"))
        if "POLAR" not in kv.get("MAP_PROJECTION_TYPE", "").upper():
            raise ValueError(f"{lbl.name}: not a polar stereographic product")
        center_lat, _ = _num(kv["CENTER_LATITUDE"])
        if abs(center_lat) < 89.0:
            raise ValueError(f"{lbl.name}: not centred on a pole (CENTER_LATITUDE {center_lat})")
        pole = 1.0 if center_lat > 0 else -1.0
        bits = int(_num(kv["SAMPLE_BITS"])[0])
        stype = kv["SAMPLE_TYPE"].upper()
        if bits != 16 or "INTEGER" not in stype:
            raise ValueError(f"{lbl.name}: expected 16-bit integers, got {bits}-bit {stype}")
        dtype = np.dtype("<i2" if stype.startswith(("LSB", "PC")) else ">i2")
        lines, samples = int(_num(kv["LINES"])[0]), int(_num(kv["LINE_SAMPLES"])[0])
        expected = lines * samples * 2
        if img.stat().st_size < expected:
            raise ValueError(f"{img.name} is {img.stat().st_size} bytes, expected {expected} (incomplete download?)")
        data = np.memmap(img, dtype=dtype, mode="r", shape=(lines, samples))
        radius = _metres(kv.get("A_AXIS_RADIUS", "1737.4 <KM>"))
        xs, ys = (1.0, -1.0) if pole < 0 else NORTH_SIGNS
        return cls(img, lines, samples, _metres(kv["MAP_SCALE"]), _num(kv["LINE_PROJECTION_OFFSET"])[0],
                   _num(kv["SAMPLE_PROJECTION_OFFSET"])[0], radius, _num(kv.get("SCALING_FACTOR", "1"))[0],
                   _num(kv.get("OFFSET", "0"))[0], data, name=img.stem.upper(), x_sign=xs, y_sign=ys, pole=pole)

    def close(self) -> None:
        """Release the memory-mapped file (Windows cannot delete a mapped file)."""
        mm = getattr(self.data, "_mmap", None)
        self.data = None
        if mm is not None:
            mm.close()

    def __enter__(self) -> "PolarGrid":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # --- projection ---------------------------------------------------------------
    def pixel(self, lat_deg, lon_deg) -> tuple[np.ndarray, np.ndarray]:
        """(line, sample) as 0-based floats."""
        lat, lon = np.radians(lat_deg), np.radians(lon_deg)
        r = 2.0 * self.radius_m * np.tan(np.pi / 4 - self.pole * lat / 2)
        x, y = self.x_sign * r * np.sin(lon), self.y_sign * r * np.cos(lon)
        return y / self.map_scale_m + self.line_offset, x / self.map_scale_m + self.sample_offset

    def latlon(self, line, sample) -> tuple[np.ndarray, np.ndarray]:
        x = (np.asarray(sample, float) - self.sample_offset) * self.map_scale_m
        y = (np.asarray(line, float) - self.line_offset) * self.map_scale_m
        r = np.hypot(x, y)
        lat = self.pole * (90.0 - np.degrees(2.0 * np.arctan(0.5 * r / self.radius_m)))
        return lat, np.degrees(np.arctan2(self.x_sign * x, self.y_sign * y))

    def value(self, lat_deg, lon_deg) -> np.ndarray:
        """Bilinear interpolation in physical units (NaN outside the grid)."""
        li, si = self.pixel(np.asarray(lat_deg, float), np.asarray(lon_deg, float))
        li, si = np.atleast_1d(li), np.atleast_1d(si)
        out = np.full(li.shape, np.nan)
        ok = (li >= 0) & (si >= 0) & (li <= self.lines - 1) & (si <= self.samples - 1)
        if ok.any():
            l, s = li[ok], si[ok]
            l0 = np.minimum(np.floor(l).astype(np.int64), self.lines - 2)
            s0 = np.minimum(np.floor(s).astype(np.int64), self.samples - 2)
            fl, fs = l - l0, s - s0
            d = self.data
            v = (d[l0, s0] * (1 - fl) * (1 - fs) + d[l0, s0 + 1] * (1 - fl) * fs
                 + d[l0 + 1, s0] * fl * (1 - fs) + d[l0 + 1, s0 + 1] * fl * fs)
            out[ok] = v * self.scale + self.offset
        return out.reshape(np.shape(li)) if np.ndim(lat_deg) else out

    def covers(self, lat_deg: float, lon_deg: float) -> bool:
        return bool(np.isfinite(self.value(lat_deg, lon_deg)).all())


# --- horizon masks -------------------------------------------------------------------
@dataclass
class HorizonMask:
    """Terrain horizon elevation around a site, one value per azimuth.

    Azimuth is measured from local north, clockwise (east = 90 deg)."""
    site: str
    lat_deg: float
    lon_deg: float
    az_deg: np.ndarray
    elev_deg: np.ndarray
    dist_km: np.ndarray            # distance of the horizon-forming terrain
    observer_m: float
    site_height_m: float           # above the 1737.4 km reference sphere
    max_dist_km: float
    coverage_km: float             # shortest distance the DEM reaches in any direction
    source: str
    map_scale_m: float
    created_utc: str = ""

    def elevation(self, az_deg) -> np.ndarray:
        """Horizon elevation (deg) in the given directions, periodic linear interpolation."""
        az = np.mod(np.asarray(az_deg, float), 360.0)
        x = np.concatenate([self.az_deg, [self.az_deg[0] + 360.0]])
        y = np.concatenate([self.elev_deg, [self.elev_deg[0]]])
        return np.interp(az, x, y)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["az_step_deg"] = float(self.az_deg[1] - self.az_deg[0])
        d.pop("az_deg")
        d["elev_deg"] = [round(float(v), 3) for v in self.elev_deg]
        d["dist_km"] = [round(float(v), 2) for v in self.dist_km]
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "HorizonMask":
        elev = np.asarray(d["elev_deg"], float)
        az = np.arange(len(elev)) * float(d["az_step_deg"])
        keys = {k: d[k] for k in ("site", "lat_deg", "lon_deg", "observer_m", "site_height_m", "max_dist_km",
                                  "coverage_km", "source", "map_scale_m")}
        return cls(az_deg=az, elev_deg=elev, dist_km=np.asarray(d["dist_km"], float),
                   created_utc=d.get("created_utc", ""), **keys)

    def save(self, path: str | Path | None = None) -> Path:
        path = Path(path) if path else HORIZON_DIR / f"{self.site}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), separators=(",", ":")))
        return path

    def summary(self) -> str:
        i = int(np.argmax(self.elev_deg))
        return (f"{self.site}: horizon {self.elev_deg.min():+.2f}..{self.elev_deg.max():+.2f} deg "
                f"(highest at az {self.az_deg[i]:.0f}, {self.dist_km[i]:.1f} km away), "
                f"site {self.site_height_m:+.0f} m, DEM reaches >= {self.coverage_km:.0f} km")


def compute_horizon(dem: PolarGrid, lat_deg: float, lon_deg: float, site: str = "site", observer_m: float = 2.0,
                    az_step_deg: float = 0.5, max_dist_km: float = 250.0, step_m: float | None = None,
                    min_dist_m: float | None = None) -> HorizonMask:
    """March outward along great circles in every direction and keep the highest
    elevation angle of the terrain, with the Moon's curvature."""
    step = step_m or dem.map_scale_m
    d = np.arange(min_dist_m or 1.5 * dem.map_scale_m, max_dist_km * 1000.0 + step, step)
    az = np.arange(0.0, 360.0, az_step_deg)
    r_ref = dem.radius_m
    r_site = float(dem.value(lat_deg, lon_deg)[0])
    if not np.isfinite(r_site):
        raise ValueError(f"({lat_deg}, {lon_deg}) is outside {dem.name}")
    r_obs = r_site + observer_m

    phi, lam = np.radians(lat_deg), np.radians(lon_deg)
    delta = d / r_ref                                  # angular distance
    a = np.radians(az)[:, None]
    sin_lat2 = np.sin(phi) * np.cos(delta) + np.cos(phi) * np.sin(delta) * np.cos(a)
    lat2 = np.arcsin(np.clip(sin_lat2, -1, 1))
    lon2 = lam + np.arctan2(np.sin(a) * np.sin(delta) * np.cos(phi), np.cos(delta) - np.sin(phi) * sin_lat2)
    r_t = dem.value(np.degrees(lat2), np.degrees(lon2))      # planetary radius, m

    rise = r_t * np.cos(delta) - r_obs
    run = r_t * np.sin(delta)
    elev = np.degrees(np.arctan2(rise, run))
    valid = np.isfinite(elev)
    elev_f = np.where(valid, elev, -np.inf)
    k = np.argmax(elev_f, axis=1)
    best = elev_f[np.arange(len(az)), k]
    reach = np.where(valid.any(axis=1), d[np.where(valid, np.arange(len(d)), -1).max(axis=1)], 0.0)
    return HorizonMask(
        site=site, lat_deg=float(lat_deg), lon_deg=float(lon_deg), az_deg=az,
        elev_deg=np.where(np.isfinite(best), best, 0.0), dist_km=d[k] / 1000.0,
        observer_m=float(observer_m), site_height_m=r_site - r_ref, max_dist_km=float(max_dist_km),
        coverage_km=float(reach.min() / 1000.0), source=dem.name, map_scale_m=dem.map_scale_m,
        created_utc=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )


@lru_cache(maxsize=None)
def load_horizon(name: str) -> HorizonMask | None:
    """Saved mask engine/surface/horizons/<name>.json, or None if not built yet."""
    path = HORIZON_DIR / f"{name}.json"
    if not path.exists():
        return None
    return HorizonMask.from_dict(json.loads(path.read_text()))


def available_horizons() -> list[str]:
    return sorted(p.stem for p in HORIZON_DIR.glob("*.json") if not p.stem.startswith("_"))
