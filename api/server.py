"""Engine server: live transfer design for the web UI, and the UI itself.

    python -m api.server                       # http://127.0.0.1:8000, DE440 if the kernels are there
    python -m api.server --ephem-cache data/cache/ephem_spice_....npz
    python -m api.server --port 8080 --workers 4

No third-party packages: the Python standard library serves HTTP, worker
processes run the engine. With a built UI in web/dist (npm run build) the whole
browser runs from this one command; during development `npm run dev` proxies
/api here instead.

Endpoints
    GET  /api/health            server status and ephemeris
    GET  /api/sites             landing-site catalogue and default constraints
    POST /api/transfers         start designing a transfer -> {job_id}
    GET  /api/jobs/<job_id>     poll: queued | running | done | error
    POST /api/trajectory        re-propagate a stored transfer's path (fast)
    GET  /data/...              the static database (web/public/data)
    GET  /...                   the built UI (web/dist)
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import threading
import time
import traceback
import uuid
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FutureTimeout
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from api import engine_service as svc  # noqa: E402
from engine import __version__  # noqa: E402
from engine.surface import SITES, LandingConstraints  # noqa: E402

MAX_BODY = 64 * 1024
JOB_TTL_S = 3600.0
mimetypes.add_type("application/javascript", ".js")
mimetypes.add_type("font/woff", ".woff")
mimetypes.add_type("font/woff2", ".woff2")


def spice_available() -> bool:
    try:
        import spiceypy  # noqa: F401
    except ImportError:
        return False
    return any((ROOT / "data" / "kernels").glob("*.bsp"))


class EngineApp:
    """Job bookkeeping around a process pool."""

    def __init__(self, use_spice: bool, ephem_cache: str | None, workers: int, max_queue: int = 8):
        self.use_spice, self.ephem_cache = use_spice, ephem_cache
        if ephem_cache:
            from engine.ephemeris import CachedEphemeris
            self.ephemeris = CachedEphemeris.load(ephem_cache).name
        else:
            self.ephemeris = "spice" if use_spice else "analytic-lowfi"
        self.workers, self.max_queue = workers, max_queue
        self.pool = ProcessPoolExecutor(max_workers=workers, initializer=svc.init_worker,
                                        initargs=(use_spice, ephem_cache))
        self.jobs: dict[str, dict] = {}
        self.lock = threading.Lock()

    def _active(self) -> int:
        return sum(not j["future"].done() for j in self.jobs.values())

    def submit_design(self, params: dict) -> dict:
        svc.spec_from_params(params)  # validate now, so bad input fails with 400 instead of in a job
        svc.constraints_from_params(params)
        with self.lock:
            now = time.time()
            for jid in [k for k, j in self.jobs.items() if j["future"].done() and now - j["created"] > JOB_TTL_S]:
                del self.jobs[jid]
            if self._active() >= self.max_queue:
                raise OverflowError(f"The engine is busy with {self._active()} transfers; try again shortly")
            jid = uuid.uuid4().hex[:12]
            self.jobs[jid] = {"future": self.pool.submit(svc.design, params), "created": now, "params": params}
            return {"job_id": jid, "status": "queued"}

    def job_status(self, jid: str) -> dict | None:
        with self.lock:
            job = self.jobs.get(jid)
        if job is None:
            return None
        fut = job["future"]
        out = {"job_id": jid, "elapsed_s": round(time.time() - job["created"], 1)}
        if not fut.done():
            out["status"] = "running" if fut.running() else "queued"
            return out
        exc = fut.exception()
        if exc is None:
            out.update(status="done", result=fut.result())
        else:
            out.update(status="error", error=str(exc) if isinstance(exc, svc.RequestError)
                       else f"{type(exc).__name__}: {exc}")
        return out

    def trajectory(self, params: dict, timeout: float = 120.0) -> dict:
        svc.spec_from_params(params)
        return self.pool.submit(svc.trajectory, params).result(timeout=timeout)

    def health(self) -> dict:
        with self.lock:
            active = self._active()
        return {"status": "ok", "version": __version__, "ephemeris": self.ephemeris,
                "workers": self.workers, "active_jobs": active}

    def close(self) -> None:
        self.pool.shutdown(wait=False, cancel_futures=True)


def make_handler(app: EngineApp, static_dir: Path | None, data_dir: Path | None):
    class Handler(BaseHTTPRequestHandler):
        server_version = f"CLPSLunarBrowser/{__version__}"

        def log_message(self, fmt, *args):  # quieter, one line per API call
            if self.path.startswith("/api/"):
                sys.stderr.write(f"  {self.command} {self.path} -> {args[1] if len(args) > 1 else ''}\n")

        # --- responses -----------------------------------------------------------
        def _json(self, status: int, obj) -> None:
            body = json.dumps(obj, separators=(",", ":"), allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, status: int, message: str) -> None:
            self._json(status, {"error": message})

        def _file(self, base: Path, rel: str) -> None:
            target = (base / rel).resolve()
            if not target.is_relative_to(base.resolve()) or not target.is_file():
                if rel and "." not in Path(rel).name and (base / "index.html").is_file():
                    target = (base / "index.html").resolve()  # client-side routes
                else:
                    self._error(HTTPStatus.NOT_FOUND, f"Not found: /{rel}")
                    return
            data = target.read_bytes()
            ctype = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache" if target.suffix in (".html", ".json") else "max-age=3600")
            self.end_headers()
            self.wfile.write(data)

        def _body(self) -> dict:
            length = int(self.headers.get("Content-Length") or 0)
            if length > MAX_BODY:
                raise svc.RequestError("Request body too large")
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                raise svc.RequestError("Request body is not valid JSON") from None
            if not isinstance(body, dict):
                raise svc.RequestError("Request body must be a JSON object")
            return body

        # --- routing ---------------------------------------------------------------
        def do_OPTIONS(self):
            self.send_response(HTTPStatus.NO_CONTENT)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = unquote(urlparse(self.path).path)
            try:
                if path == "/api/health":
                    return self._json(HTTPStatus.OK, app.health())
                if path == "/api/sites":
                    return self._json(HTTPStatus.OK, {"sites": [s.to_dict() for s in SITES],
                                                      "constraints": LandingConstraints().to_dict()})
                if path.startswith("/api/jobs/"):
                    status = app.job_status(path.rsplit("/", 1)[-1])
                    if status is None:
                        return self._error(HTTPStatus.NOT_FOUND, "Unknown job (it may have expired)")
                    return self._json(HTTPStatus.OK, status)
                if path.startswith("/api/"):
                    return self._error(HTTPStatus.NOT_FOUND, f"No endpoint {path}")
                if path.startswith("/data/") and data_dir is not None:
                    return self._file(data_dir, path[len("/data/"):])
                if static_dir is not None:
                    return self._file(static_dir, path.lstrip("/") or "index.html")
                return self._error(HTTPStatus.NOT_FOUND,
                                   "No built UI here. Run `npm run build` in web/, or use `npm run dev`.")
            except BrokenPipeError:
                pass
            except Exception as exc:  # pragma: no cover - last resort
                traceback.print_exc()
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

        def do_POST(self):
            path = urlparse(self.path).path
            try:
                body = self._body()
                if path == "/api/transfers":
                    return self._json(HTTPStatus.ACCEPTED, app.submit_design(body))
                if path == "/api/trajectory":
                    return self._json(HTTPStatus.OK, app.trajectory(body))
                return self._error(HTTPStatus.NOT_FOUND, f"No endpoint {path}")
            except svc.RequestError as exc:
                self._error(HTTPStatus.BAD_REQUEST, str(exc))
            except OverflowError as exc:
                self._error(HTTPStatus.TOO_MANY_REQUESTS, str(exc))
            except FutureTimeout:
                self._error(HTTPStatus.GATEWAY_TIMEOUT, "The engine took too long; try again")
            except Exception as exc:
                traceback.print_exc()
                self._error(HTTPStatus.INTERNAL_SERVER_ERROR, f"{type(exc).__name__}: {exc}")

    return Handler


def make_server(host: str = "127.0.0.1", port: int = 8000, use_spice: bool | None = None,
                ephem_cache: str | None = None, workers: int = 2, static_dir: Path | None = None,
                data_dir: Path | None = None) -> tuple[ThreadingHTTPServer, EngineApp]:
    if use_spice is None:
        use_spice = ephem_cache is None and spice_available()
    app = EngineApp(use_spice, ephem_cache, workers)
    httpd = ThreadingHTTPServer((host, port), make_handler(app, static_dir, data_dir))
    httpd.daemon_threads = True
    return httpd, app


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 to share on your network")
    ap.add_argument("--port", type=int, default=8000)
    eph = ap.add_mutually_exclusive_group()
    eph.add_argument("--spice", dest="spice", action="store_true", default=None, help="force DE440 via SPICE")
    eph.add_argument("--analytic", dest="spice", action="store_false", help="force the analytic ephemeris")
    ap.add_argument("--ephem-cache", default=None, help="saved CachedEphemeris .npz (no SPICE needed)")
    ap.add_argument("--workers", type=int, default=2, help="transfers designed in parallel")
    ap.add_argument("--static", default=str(ROOT / "web" / "dist"), help="built UI folder")
    ap.add_argument("--data", default=str(ROOT / "web" / "public" / "data"), help="database folder")
    args = ap.parse_args()

    static = Path(args.static) if Path(args.static, "index.html").is_file() else None
    data = Path(args.data) if Path(args.data).is_dir() else None
    httpd, app = make_server(args.host, args.port, args.spice, args.ephem_cache, args.workers, static, data)
    url = f"http://{'localhost' if args.host in ('127.0.0.1', '0.0.0.0') else args.host}:{args.port}"
    print(f"CLPS Lunar Mission Browser engine {__version__}")
    print(f"  ephemeris : {app.ephemeris}")
    print(f"  workers   : {args.workers}")
    print(f"  database  : {data or 'none (web/public/data missing)'}")
    print(f"  UI        : {url + '/' if static else 'not built (run npm run build in web/, or npm run dev)'}")
    print(f"  API       : {url}/api/health\nPress Ctrl+C to stop.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        httpd.server_close()
        app.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
