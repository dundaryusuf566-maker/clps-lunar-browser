"""Reading single pixels out of Diviner's polar cumulative products without
downloading them.

The south polar PCP tables (Williams et al. 2019; PDS Geosciences node,
urn-nasa-pds-lro_diviner_derived1/data_derived_pcp) are ASCII files of ~200 MB
each: one header record, then one fixed-length record per 240 m bin that has
data, with five values: x and y (distance from the pole, normalised by the mean
radius 1737.4 km), longitude, latitude, and the mean bolometric brightness
temperature in that bin. Because the records have a fixed length and the bins are
written in grid order, a bin can be found with a binary search over HTTP range
requests over one kept-alive connection: about 16 small requests per point (single
records, then one block of at most 256 records), instead of 200 MB.

Nothing about the order or the x/y convention is assumed: both are worked out from
a sample of records and checked, and the search refuses to run if they do not hold.
"""

from __future__ import annotations

import http.client
import re
import time
import urllib.parse
from dataclasses import dataclass
from typing import Callable

import numpy as np

PCP_ROOT = "https://pds-geosciences.wustl.edu/lro/urn-nasa-pds-lro_diviner_derived1/data_derived_pcp"
WILLIAMS2019 = "https://experts.colorado.edu/display/pubid_269945"   # Williams et al. 2019, JGR Planets 124
BIN_KM = 0.240
R_KM = 1737.4
_NUM = re.compile(r"[-+]?(?:\d+\.\d*|\.\d+|\d+)(?:[eE][-+]?\d+)?")


def ltim_url(season: str, num: int) -> str:
    """Local-time bin file: season 'sum' or 'win', num 1..96 (local time (num - 1) * 0.25 h)."""
    return f"{PCP_ROOT}/diurnal/ltim/pols/pcp_avg_tbol_pols_{season}_ltim{num:02d}_240.tab"


def latlon_from_xy(x: float, y: float) -> tuple[float, float]:
    """South polar stereographic x = rho sin(lon), y = rho cos(lon), rho = 2 tan(45 deg + lat/2)
    (the convention detect_layout finds in the archive), back to latitude and longitude."""
    rho = np.hypot(x, y)
    return float(np.degrees(2 * np.arctan(rho / 2)) - 90.0), float(np.degrees(np.arctan2(x, y)) % 360.0)


def parse_record(raw: bytes) -> tuple[float, ...] | None:
    vals = _NUM.findall(raw.decode("ascii", "replace"))
    if len(vals) < 5:
        return None
    return tuple(float(v) for v in vals[:5])


class HttpRange:
    """Byte ranges of one remote file over one kept-alive HTTPS connection, with retries.

    The total size comes from the Content-Range header of the first range response
    (no separate HEAD request). Failed requests are retried with a growing pause on a
    fresh connection; after `retries` attempts the error is raised.
    """

    def __init__(self, url: str, timeout: float = 30.0, retries: int = 6, pause: float = 2.0):
        u = urllib.parse.urlsplit(url)
        self.url, self.host, self.https = url, u.netloc, u.scheme == "https"
        self.path = u.path + (f"?{u.query}" if u.query else "")
        self.timeout, self.retries, self.pause = timeout, retries, pause
        self.requests = 0
        self.total: int | None = None
        self._conn = None

    def _connect(self):
        cls = http.client.HTTPSConnection if self.https else http.client.HTTPConnection
        self._conn = cls(self.host, timeout=self.timeout)

    def close(self):
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _get(self, start: int, length: int) -> bytes:
        if self._conn is None:
            self._connect()
        self._conn.request("GET", self.path, headers={"Range": f"bytes={start}-{start + length - 1}",
                                                       "User-Agent": "clps-lunar-browser (Diviner check)"})
        r = self._conn.getresponse()
        body = r.read()
        if r.status == 429 or r.status >= 500:
            raise ConnectionError(f"{self.url}: HTTP {r.status} (server busy), will retry")
        if r.status != 206:
            raise RangeIgnored(f"{self.url}: the server did not return the byte range (HTTP {r.status})")
        m = re.search(r"/(\d+)\s*$", r.getheader("Content-Range") or "")
        if m:
            self.total = int(m.group(1))
        if r.getheader("Connection", "").lower() == "close":
            self.close()
        return body

    def __call__(self, start: int, length: int) -> bytes:
        for attempt in range(self.retries):
            try:
                out = self._get(start, length)
                self.requests += 1
                return out
            except RangeIgnored:
                raise
            except Exception:
                self.close()
                if attempt == self.retries - 1:
                    raise
                time.sleep(min(30.0, self.pause * 2 ** attempt))
        raise RuntimeError("unreachable")

    def size(self) -> int:
        if self.total is None:
            self(0, 1)
        if self.total is None:
            raise RangeIgnored(f"{self.url}: no Content-Range header, file size unknown")
        return self.total


class RangeIgnored(RuntimeError):
    """The server answered but not with the requested bytes: retrying will not help."""


class Rows:
    """Records of one table, read one at a time or in blocks, and kept (shared by all lookups in the file)."""

    def __init__(self, fetch: Callable[[int, int], bytes], record: int):
        self.fetch, self.record = fetch, record
        self.cache: dict[int, tuple[float, ...]] = {}

    def get(self, i: int) -> tuple[float, ...]:
        if i not in self.cache:
            r = parse_record(self.fetch((i + 1) * self.record, self.record))
            if r is None:
                raise ValueError(f"unreadable record {i}")
            self.cache[i] = r
        return self.cache[i]

    def block(self, lo: int, hi: int):
        """Read records lo..hi-1 with one request (those not already known)."""
        if all(i in self.cache for i in range(lo, hi)):
            return
        raw = self.fetch((lo + 1) * self.record, (hi - lo) * self.record)
        for k in range(hi - lo):
            r = parse_record(raw[k * self.record:(k + 1) * self.record])
            if r is not None:
                self.cache[lo + k] = r


@dataclass
class Layout:
    """How a PCP table is written: record length, sort columns, x/y convention."""
    record: int
    primary: int              # column index the rows are sorted by (0 = x, 1 = y)
    secondary: int
    xy: Callable[[float, float], tuple[float, float]]
    name: str


def _candidates():
    """x/y conventions to test: polar stereographic or orthographic radius, axes and signs."""
    out = []
    for rname, rad in (("stereographic", lambda la: 2 * np.tan(np.pi / 4 + np.radians(la) / 2)),
                       ("orthographic", lambda la: np.cos(np.radians(la)))):
        for ax in ("sin_cos", "cos_sin"):
            for sx in (1, -1):
                for sy in (1, -1):
                    def f(lat, lon, rad=rad, ax=ax, sx=sx, sy=sy):
                        r, lo = rad(lat), np.radians(lon)
                        a, b = (np.sin(lo), np.cos(lo)) if ax == "sin_cos" else (np.cos(lo), np.sin(lo))
                        return sx * r * a, sy * r * b
                    out.append((f"{rname} x={'+' if sx > 0 else '-'}{ax.split('_')[0]}, y={'+' if sy > 0 else '-'}{ax.split('_')[1]}", f))
    return out


def detect_layout(fetch: Callable[[int, int], bytes], size: int, record: int = 59, samples: int = 48) -> Layout:
    """Work out the sort order and the x/y convention from records spread over the file."""
    n = size // record - 1
    idx = np.unique(np.linspace(0, n - 1, samples).astype(int))
    rows = [parse_record(fetch((i + 1) * record, record)) for i in idx]
    rows = np.array([r for r in rows if r is not None])
    if len(rows) < samples // 2:
        raise ValueError("could not parse the sampled records")
    prim = [c for c in (0, 1) if np.all(np.diff(rows[:, c]) >= -1e-12)]
    if not prim:
        raise ValueError("records are not sorted by x or y; a binary search would not work")
    p = prim[0]
    tol = 0.2 * BIN_KM / R_KM
    for name, f in _candidates():
        x, y = f(rows[:, 3], rows[:, 2])
        if np.max(np.abs(x - rows[:, 0])) < tol and np.max(np.abs(y - rows[:, 1])) < tol:
            return Layout(record, p, 1 - p, f, name)
    raise ValueError("no known projection reproduces the x/y columns from longitude/latitude")


BLOCK = 256           # once the search is down to this many records, read them in one request (~15 kB)
MAX_BAND = 4096       # records in one grid column at most (poleward of 80 S there are ~2,600)


def find_bin(fetch: Callable[[int, int], bytes], n_rows: int, lay: Layout, lat: float, lon: float,
             max_dist_bins: float = 0.75, rows: Rows | None = None, with_row: bool = False):
    """Temperature in the bin nearest (lat, lon), and its distance in bins; None if no bin with data is close.

    Pass the same `rows` for several points in one file so that they share what was read. With
    `with_row`, the whole record (x, y, lon, lat, T) is returned as a third value."""
    tx, ty = lay.xy(lat, lon)
    target = (tx, ty)
    half = 0.5 * BIN_KM / R_KM
    rows = rows or Rows(fetch, lay.record)
    row = rows.get

    def lower(key: Callable[[tuple], tuple], value: tuple, lo: int = 0, hi: int = n_rows) -> int:
        blocked = False
        while lo < hi:
            if not blocked and hi - lo <= BLOCK:
                rows.block(lo, hi)
                blocked = True
            mid = (lo + hi) // 2
            if key(row(mid)) < value:
                lo = mid + 1
            else:
                hi = mid
        return lo

    p, s = lay.primary, lay.secondary
    i = lower(lambda r: (r[p],), (target[p] - half,))
    if i >= n_rows or row(i)[p] > target[p] + half:
        return None
    band = row(i)[p]                                     # the grid column starts at i
    j = lower(lambda r: (r[p], r[s]), (band, target[s] - 1.5 * half), i, min(n_rows, i + MAX_BAND))
    best = None
    for k in range(j, min(j + 4, n_rows)):
        r = row(k)
        if abs(r[p] - band) > half:                      # left the column
            break
        d = np.hypot(r[0] - tx, r[1] - ty) / (2 * half)
        if best is None or d < best[1]:
            best = (r[4], d, r)
    if best is None or best[1] > max_dist_bins:
        return None
    if with_row:
        return float(best[0]), float(best[1]), tuple(float(v) for v in best[2])
    return float(best[0]), float(best[1])
