"""End-to-end test of the engine server (real HTTP, real worker process)."""

import json
import tempfile
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from api.server import make_server


def _call(base, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"},
                                 method="POST" if body is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"{}")


def test_engine_server_end_to_end():
    with tempfile.TemporaryDirectory() as d:
        data = Path(d) / "data"
        data.mkdir()
        (data / "transfers.json").write_text('{"meta":{},"rows":[]}')
        (Path(d) / "secret.txt").write_text("nope")
        httpd, app = make_server("127.0.0.1", 0, use_spice=False, workers=1, data_dir=data)
        base = f"http://127.0.0.1:{httpd.server_address[1]}"
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            status, health = _call(base, "/api/health")
            assert status == 200 and health["status"] == "ok" and health["ephemeris"] == "analytic-lowfi"

            status, sites = _call(base, "/api/sites")
            assert status == 200 and len(sites["sites"]) >= 7 and "max_wait_days" in sites["constraints"]

            assert _call(base, "/data/transfers.json")[0] == 200
            assert _call(base, "/data/../secret.txt")[0] == 404
            assert _call(base, "/api/nope")[0] == 404

            status, err = _call(base, "/api/transfers", {"tli_utc": "2026-01-10", "tof_days": 40})
            assert status == 400 and "tof_days" in err["error"]
            status, err = _call(base, "/api/transfers", {"tli_utc": "not a date", "tof_days": 5})
            assert status == 400 and "tli_utc" in err["error"]

            status, job = _call(base, "/api/transfers", {"tli_utc": "2026-01-10T00:00", "tof_days": 5, "family": 1})
            assert status == 202 and job["job_id"]
            deadline = time.time() + 120
            while True:
                status, st = _call(base, f"/api/jobs/{job['job_id']}")
                assert status == 200
                if st["status"] in ("done", "error") or time.time() > deadline:
                    break
                time.sleep(0.5)
            assert st["status"] == "done", st
            res = st["result"]
            assert res["converged"]
            row = res["row"]
            assert 790 < row["loi_dv_ms"] < 900 and row["id"].startswith("live-")
            assert len(res["trajectory"]["sc_eci"]) > 100
            assert set(res["landings"]) == set(res["series"]) and "apollo-11" in res["landings"]
            assert res["landing_details"]["mons-mouton"]["site_id"] == "mons-mouton"

            status, traj = _call(base, "/api/trajectory", {
                "tli_epoch": row["tli_epoch"], "tof_days": row["tof_days"], "family": row["family"],
                "lunar_inc_deg": row["lunar_inc_deg"], "target_alt_km": row["target_alt_km"],
                "controls": row["controls"], "id": row["id"]})
            assert status == 200 and traj["id"] == row["id"]
            assert abs(traj["events"]["periselene"] - res["trajectory"]["events"]["periselene"]) < 1.0
            assert _call(base, "/api/jobs/doesnotexist")[0] == 404
        finally:
            httpd.shutdown()
            httpd.server_close()
            app.close()
