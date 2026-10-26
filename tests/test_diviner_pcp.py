"""Finding single bins in a fixed-record PCP-like table by binary search (local bytes,
no network): layout detection, hits, misses."""

import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from engine.validation.diviner_pcp import (BIN_KM, R_KM, HttpRange, RangeIgnored, Rows, detect_layout, find_bin, latlon_from_xy,
                                          parse_record)

REC = 59


def _table(drop=0.15, seed=1, sort_by_y=True):
    """Synthetic south-polar table: 240 m bins within 20 km of (85S, 40E), some missing."""
    rng = np.random.default_rng(seed)
    step = BIN_KM / R_KM
    rho0 = 2 * np.tan(np.pi / 4 + np.radians(-85.0) / 2)
    cx, cy = rho0 * np.sin(np.radians(40.0)), rho0 * np.cos(np.radians(40.0))
    k = np.arange(-80, 81)
    gx = np.round(cx / step) * step + k * step
    gy = np.round(cy / step) * step + k * step
    rows = []
    for y in gy:
        for x in gx:
            if rng.random() < drop:
                continue
            rho = np.hypot(x, y)
            lat = np.degrees(2 * np.arctan(rho / 2)) - 90
            lon = np.degrees(np.arctan2(x, y)) % 360
            T = 100 + 1000 * x + 3000 * y
            rows.append((x, y, lon, lat, T))
    rows.sort(key=(lambda r: (r[1], r[0])) if sort_by_y else (lambda r: (r[0], r[1])))
    out = [f"{'X Y LON LAT TBOL':<{REC - 2}}\r\n".encode()]
    for x, y, lon, lat, T in rows:
        line = f"{x:12.8f},{y:12.8f},{lon:10.5f},{lat:10.5f},{T:8.3f}"
        out.append(f"{line:<{REC - 2}}\r\n".encode())
    blob = b"".join(out)
    assert all(len(o) == REC for o in out)
    return blob, rows


def test_layout_and_lookup():
    for by_y in (True, False):
        blob, rows = _table(sort_by_y=by_y)
        fetch = lambda a, n: blob[a:a + n]          # noqa: E731
        lay = detect_layout(fetch, len(blob), REC)
        assert lay.primary == (1 if by_y else 0) and lay.name.startswith("stereographic")
        n = len(blob) // REC - 1
        for x, y, lon, lat, T in rows[::997]:
            hit = find_bin(fetch, n, lay, lat, lon)
            assert hit is not None and abs(hit[0] - T) < 1e-3 and hit[1] < 0.01
        # a point between bins snaps to the nearest one; a point far outside finds nothing
        x, y, lon, lat, T = rows[len(rows) // 2]
        hit = find_bin(fetch, n, lay, lat + 0.001, lon)
        assert hit is not None and hit[1] < 0.75
        assert find_bin(fetch, n, lay, -80.0, 200.0) is None


def test_bin_record_and_inverse_projection():
    """The bin's own x/y come back with the record and map back to its longitude and latitude."""
    blob, rows = _table()
    fetch = lambda a, n: blob[a:a + n]              # noqa: E731
    lay = detect_layout(fetch, len(blob), REC)
    n = len(blob) // REC - 1
    for x, y, lon, lat, T in rows[::1201]:
        t, dist, rec = find_bin(fetch, n, lay, lat + 0.0005, lon + 0.003, with_row=True)
        assert abs(t - T) < 1e-3 and abs(rec[0] - x) < 1e-8 and abs(rec[1] - y) < 1e-8
        la, lo = latlon_from_xy(rec[0], rec[1])
        assert abs(la - lat) < 1e-4 and abs((lo - lon + 180) % 360 - 180) < 1e-4
        fx, fy = lay.xy(la, lo)
        assert abs(fx - x) < 1e-7 and abs(fy - y) < 1e-7          # the table is written to 8 decimals


def test_missing_bin_is_not_invented():
    blob, rows = _table(drop=0.0)
    keep = blob[:REC] + b"".join(blob[(i + 1) * REC:(i + 2) * REC] for i in range(len(rows)) if i != len(rows) // 2)
    fetch = lambda a, n: keep[a:a + n]              # noqa: E731
    lay = detect_layout(fetch, len(keep), REC)
    x, y, lon, lat, T = rows[len(rows) // 2]
    hit = find_bin(fetch, len(keep) // REC - 1, lay, lat, lon, max_dist_bins=0.5)
    assert hit is None


def test_parse_record():
    assert parse_record(b" 0.01, -0.02 , 40.0, -85.0, 123.4\r\n") == (0.01, -0.02, 40.0, -85.0, 123.4)
    assert parse_record(b"X Y LON LAT TBOL") is None


def test_http_range_survives_a_flaky_server():
    """Over real HTTP: the size comes from Content-Range, 503s and dropped connections are retried,
    one connection is reused, a server that ignores ranges is refused, and lookups agree with local reads."""
    blob, rows = _table(sort_by_y=False)
    script = iter(["drop", "503"] + ["ok"] * 100000)
    seen = {"conns": 0}

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def setup(self):
            super().setup()
            self.connection.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)    # no 40 ms Nagle stalls
            seen["conns"] += 1

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path.endswith("noranges"):
                self.send_response(200); self.send_header("Content-Length", "2"); self.end_headers(); self.wfile.write(b"ok")
                return
            what = next(script)
            if what == "drop":
                self.close_connection = True
                self.connection.shutdown(socket.SHUT_RDWR)
                return
            if what == "503":
                self.send_response(503); self.send_header("Content-Length", "0"); self.end_headers()
                return
            a, b = map(int, self.headers["Range"].split("=")[1].split("-"))
            body = blob[a:b + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {a}-{b}/{len(blob)}")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True).start()
    try:
        url = f"http://127.0.0.1:{srv.server_address[1]}/table.tab"
        h = HttpRange(url, timeout=5.0, pause=0.01)
        assert h.size() == len(blob)
        lay = detect_layout(h, h.size(), REC)
        n = len(blob) // REC - 1
        shared = Rows(h, REC)
        local = lambda a, k: blob[a:a + k]          # noqa: E731
        for x, y, lon, lat, T in rows[::1499]:
            assert find_bin(h, n, lay, lat, lon, rows=shared) == find_bin(local, n, lay, lat, lon)
        h.close()
        assert seen["conns"] <= 3                   # the first one dropped, then one kept-alive connection
        bad = HttpRange(url + "?noranges", timeout=5.0, pause=0.01)
        try:
            bad(0, 10)
            raise AssertionError("a server that ignores Range must be refused")
        except RangeIgnored:
            pass
        finally:
            bad.close()
    finally:
        srv.shutdown()
        srv.server_close()
