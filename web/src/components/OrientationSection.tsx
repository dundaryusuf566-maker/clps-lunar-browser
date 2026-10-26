import { fmtNum } from "../lib/format";
import type { OrientationFile, ValidationCheck } from "../types";
import type { ReactNode } from "react";

const poleName = (f: OrientationFile) => (f.dem.includes("75N") || f.craters[0]?.lat > 0 ? "North" : "South");

export function orientationChecks(files: OrientationFile[]): ValidationCheck[] {
  return files.map((f) => ({
    id: `orientation-${poleName(f).toLowerCase()}`, pass: f.code === 0,
    label: `${poleName(f)} polar map read the right way round: only one of the four readings puts all ${f.craters.length} named craters where the IAU does`,
  }));
}

export function OrientationSection({ files, checks }: { files: OrientationFile[]; checks: (c: ValidationCheck[]) => ReactNode }) {
  return (
    <section className="panel" aria-labelledby="orient-title">
      <div className="panel-head">
        <h2 id="orient-title">Which way round the polar maps are read</h2>
        <span className="hint">named craters at their IAU positions</span>
      </div>
      <div className="panel-body">
        <p className="val-story">
          A polar map can be read four ways (each axis straight or mirrored). Read wrongly, the terrain stands in the wrong
          directions around every point and the Sun is hidden at the wrong hours. NASA's average-illumination map cannot tell
          the readings apart (averaged over 18.6 years the Sun goes round the sky evenly; we first believed it could, and
          corrected that), so the check uses geography: six large craters per pole, spread around it, at their official
          positions. The right reading puts a deep bowl at every one; a wrong one puts the "floor" somewhere else.
          <strong> Criterion, written before the first run: every crater at least {files[0] ? fmtNum(files[0].criterion_min_depth_m, 0) : 500} m deep, and exactly one reading passing.</strong>
        </p>
        {checks(orientationChecks(files))}
        {files.map((f) => (
          <div key={f.dem} className="table-wrap">
            <table>
              <thead><tr><th className="left">{f.dem}: reading</th>{f.craters.map((c) => <th key={c.name}>{c.name}</th>)}<th>Result</th></tr></thead>
              <tbody>
                {f.readings.map((r) => {
                  const used = r.x_sign === f.engine_reading[0] && r.y_sign === f.engine_reading[1];
                  return (
                    <tr key={`${r.x_sign}${r.y_sign}`} className={used ? "selected static" : "static"}>
                      <td className="left">x {r.x_sign > 0 ? "+" : "−"}, y {r.y_sign > 0 ? "+" : "−"}{used ? " (used)" : ""}</td>
                      {f.craters.map((c) => <td key={c.name} className={r.depths_m[c.name] !== null && r.depths_m[c.name]! >= f.criterion_min_depth_m ? "" : "bad-text"}>
                        {r.depths_m[c.name] === null ? "–" : `${fmtNum(r.depths_m[c.name]!, 0)} m`}</td>)}
                      <td>{r.pass ? "pass" : "fail"}</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ))}
        <p className="table-note">Depth: mean height on the rim ring (0.9–1.15 crater radii) minus the floor (within 0.35 radii), at the
          crater's IAU latitude and longitude, for each reading. Crater positions: {files[0]?.craters_source}. scripts/check_polar_orientation.py;
          tests/test_orientation.py checks on synthetic maps that the test singles out the true reading at both poles.</p>
      </div>
    </section>
  );
}
