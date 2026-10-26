import { scaleLinear } from "d3-scale";
import { useState, type ReactNode } from "react";
import { fmtNum } from "../lib/format";
import { useWidth } from "../lib/hooks";
import type { DivinerClass, DivinerDiagnosticsFile, DivinerPolarFile, ValidationCheck } from "../types";

type Season = "sum" | "win";
const SEASONS: Record<Season, string> = { sum: "Southern summer", win: "Southern winter" };
const signed = (v: number | null) => (v === null ? "–" : `${v > 0 ? "+" : ""}${fmtNum(v, 1)}`);

// Illumination classes, the same as scripts/diviner_polar_diagnose.py (chosen after seeing the data; descriptive only)
const DARK_K = 100, LIT_K = 150;
const CLASSES: [DivinerClass, string][] = [
  ["both_dark", "Both dark"],
  ["both_lit", "Both sunlit"],
  ["model_dark", "Model dark, Diviner warm"],
  ["diviner_dark", "Model sunlit, Diviner dark"],
  ["between", "In between"],
];
function classify(m: number, d: number): DivinerClass {
  if (m < DARK_K && d < DARK_K) return "both_dark";
  if (m > LIT_K && d > LIT_K) return "both_lit";
  if (m < DARK_K && d > 120) return "model_dark";
  if (m > LIT_K && d < DARK_K) return "diviner_dark";
  return "between";
}
const median = (a: number[]) => {
  if (!a.length) return null;
  const s = [...a].sort((x, y) => x - y), k = s.length >> 1;
  return s.length % 2 ? s[k] : (s[k - 1] + s[k]) / 2;
};
function breakdown(d: DivinerPolarFile) {
  const out = Object.fromEntries(CLASSES.map(([c]) => [c, [] as number[]])) as Record<DivinerClass, number[]>;
  for (const p of d.points) for (const s of ["sum", "win"] as Season[]) for (const [, dv, m] of p.seasons[s]) {
    if (dv !== null && m !== null) out[classify(m, dv)].push(m - dv);
  }
  return out;
}

export function divinerChecks(d: DivinerPolarFile): ValidationCheck[] {
  const s = d.summary;
  return [{
    id: "diviner-polar", pass: s.pass, value: s.median_abs_k,
    label: `Regolith model near the south pole against Diviner's 10-year polar maps: median difference within ${s.criterion_k} K` +
      ` (${s.median_abs_k === null ? "no data" : `${fmtNum(s.median_abs_k, 1)} K`} over ${s.n} local-time bins)`,
  }];
}

export function DivinerPolarSection({ d, diag, checks }: {
  d: DivinerPolarFile; diag?: DivinerDiagnosticsFile | null; checks: (c: ValidationCheck[]) => ReactNode;
}) {
  const s = d.summary;
  const [key, setKey] = useState(d.points[0]?.key ?? "");
  const [season, setSeason] = useState<Season>("sum");
  const p = d.points.find((q) => q.key === key) ?? d.points[0];
  const dp = diag?.points.find((q) => q.key === p?.key);
  const bd = breakdown(d);
  return (
    <section className="panel" aria-labelledby="diviner-polar-title">
      <div className="panel-head">
        <h2 id="diviner-polar-title">Polar temperatures against Diviner's measurements</h2>
        <span className="hint">Williams et al. (2019) polar maps</span>
      </div>
      <div className="panel-body val-grid">
        <div>
          <p className="val-story">
            The equator check above uses three typical numbers. This one uses measurements at the places that matter: LRO's
            Diviner mapped the south pole in 240 m bins for ten years ({d.meta.span_utc[0].slice(0, 4)}–{d.meta.span_utc[1].slice(0, 4)}),
            averaged by local time and season. For each point the browser read the bin it falls in straight from NASA's
            Planetary Data System, then ran its own regolith model over the same years with the same Sun and LOLA terrain,
            and averaged it the same way. <strong>The pass criterion ({s.criterion_k} K median difference) was written into
            the script before any Diviner value was read</strong>; whatever came out is shown.
          </p>
          {p && (
            <>
              <div className="power-grid">
                <label className="control">Point
                  <select value={p.key} onChange={(e) => setKey(e.target.value)}>
                    {d.points.map((q) => <option key={q.key} value={q.key}>{q.label}</option>)}
                  </select>
                </label>
                <label className="control">Season
                  <select value={season} onChange={(e) => setSeason(e.target.value as Season)}>
                    {(Object.keys(SEASONS) as Season[]).map((k) => <option key={k} value={k}>{SEASONS[k]}</option>)}
                  </select>
                </label>
              </div>
              <PolarChart series={p.seasons[season]} bin={dp?.seasons[season]} />
            </>
          )}
        </div>
        <div>
          {checks(divinerChecks(d))}
          <dl className="figures two">
            <div><dt>Bias in sunlight (model − Diviner)</dt><dd>{signed(s.bias_day_k)}<small>K, {s.n_day} bins</small></dd></div>
            <div><dt>Bias at night (Diviner below {d.meta.night_below_k} K)</dt><dd>{signed(s.bias_night_k)}<small>K, {s.n_night} bins</small></dd></div>
            <div><dt>Median difference</dt><dd>{s.median_abs_k === null ? "–" : fmtNum(s.median_abs_k, 1)}<small>K</small></dd></div>
            <div><dt>90% of bins within</dt><dd>{s.p90_abs_k === null ? "–" : fmtNum(s.p90_abs_k, 1)}<small>K</small></dd></div>
          </dl>
          <div className="table-wrap">
            <table>
              <thead><tr><th className="left">Point</th><th>Lat</th><th>Bins</th><th>Median |Δ|</th><th>Bias</th></tr></thead>
              <tbody>
                {d.points.map((q) => (
                  <tr key={q.key} className={q.key === p?.key ? "selected" : ""} onClick={() => setKey(q.key)}>
                    <td className="left">{q.label}</td><td>{fmtNum(q.lat, 2)}°</td><td>{q.n}</td>
                    <td>{q.median_abs_k === null ? "–" : `${fmtNum(q.median_abs_k, 1)} K`}</td><td>{signed(q.bias_k)} K</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            {d.meta.notes.join(" ")} Every {d.meta.bins.length > 1 ? d.meta.bins[1] - d.meta.bins[0] : 1}th of Diviner's 96
            local-time bins, both seasons; {d.meta.range_requests ? `${d.meta.range_requests} byte-range requests` : "read from the local cache"};
            model with {d.meta.ephemeris === "spice" ? "JPL DE440" : "the analytic ephemeris (demo)"}, {d.meta.dem}.
            {" "}<a href={d.meta.diviner_source} target="_blank" rel="noreferrer">Williams et al. 2019</a> ·{" "}
            <a href={d.meta.diviner_archive} target="_blank" rel="noreferrer">PDS archive</a>
          </p>
        </div>
        <div className="val-span">
          <h3 className="val-h3">After the check: where the difference comes from</h3>
          <p className="val-story">
            This part changes nothing above; it splits the same comparison by whether the model and Diviner see the
            point sunlit (above {LIT_K} K) or dark (below {DARK_K} K; “Diviner warm”: above 120 K; “in between”: sunrise, sunset, part shadow). The split was chosen after the data were seen.
            {diag ? <> The last columns compare like with like: Diviner's number is the radiance-weighted mean of a
              240 m bin, the registered check used the model at one point; here the model is run at
              {" "}{diag.meta.sub_points_m.length ** 2} points over the bin itself, each with its own LOLA horizon and slope,
              and averaged the same way. Nothing is fitted. These columns use only the local-time bins where the point's
              own Diviner bin had data (elsewhere the check took a neighbouring bin), with the point model on the same bins
              beside it.</> : null}
          </p>
          <div className="table-wrap">
            <table>
              <thead><tr><th className="left">Model, Diviner</th><th>Bins</th><th>Median Δ</th>
                {diag && <><th>Own-bin bins</th><th>Median Δ, point</th><th>Median Δ, over the bin (bins)</th></>}</tr></thead>
              <tbody>
                {CLASSES.map(([c, label]) => (
                  <tr key={c} className="static">
                    <td className="left">{label}</td><td>{bd[c].length}</td><td>{bd[c].length ? `${signed(median(bd[c]))} K` : "–"}</td>
                    {diag && <><td>{diag.same_bins_point_breakdown?.[c].n ?? "–"}</td>
                      <td>{diag.same_bins_point_breakdown?.[c].n ? `${signed(diag.same_bins_point_breakdown[c].median_k)} K` : "–"}</td>
                      <td>{diag.bin_breakdown[c].n ? `${signed(diag.bin_breakdown[c].median_k)} K (${diag.bin_breakdown[c].n})` : "– (0)"}</td></>}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="table-note">
            Reading it (this data set): where both are dark the model follows Diviner closely, so the heat stored in the
            regolith and the night are right. The difference comes with sunlight: when both are sunlit the model is
            colder, less so at IM-1's Malapert A (80° S) where the Sun stands higher than at the 85° S points; and in many
            bins Diviner's bin is warm while the model's point is still behind the terrain, never the other way round.
            Candidates for what the model leaves out at grazing Sun: a bin that is partly sunlit (its warm part dominates a
            radiance-weighted temperature), roughness below the 120 m map, and an albedo law fitted at the equator. None
            was adjusted here.
            {diag && diag.bin_median_abs_k !== null && ` On the ${diag.bin_n} own-bin local-time bins the median difference is ${diag.same_bins_point_median_abs_k != null ? `${fmtNum(diag.same_bins_point_median_abs_k, 1)} K with the point model and ` : ""}${fmtNum(diag.bin_median_abs_k, 1)} K with the model over the bin; this is a diagnosis after the fact, not a second attempt at the check.`}
          </p>
        </div>
      </div>
    </section>
  );
}

function PolarChart({ series, bin }: { series: [number, number | null, number | null][]; bin?: [number, number | null, number | null, number | null][] }) {
  const [ref, width] = useWidth<HTMLDivElement>();
  const W = Math.max(0, width), H = 220, M = { top: 10, right: 12, bottom: 30, left: 44 };
  const iw = Math.max(0, W - M.left - M.right), ih = H - M.top - M.bottom;
  const vals = [...series.flatMap(([, a, b]) => [a, b]), ...(bin ?? []).map((r) => r[3])].filter((v): v is number => v !== null);
  const lo = vals.length ? Math.min(...vals) : 0, hi = vals.length ? Math.max(...vals) : 300;
  const x = scaleLinear().domain([0, 24]).range([0, iw]);
  const y = scaleLinear().domain([Math.max(0, lo - 10), hi + 10]).nice().range([ih, 0]);
  let d = "", pen = false;
  for (const [lt, , m] of series) {
    if (m === null) { pen = false; continue; }
    d += `${pen ? "L" : "M"}${x(lt).toFixed(1)},${y(m).toFixed(1)}`;
    pen = true;
  }
  let db = "";
  pen = false;
  for (const [lt, , , m] of bin ?? []) {
    if (m === null) { pen = false; continue; }
    db += `${pen ? "L" : "M"}${x(lt).toFixed(1)},${y(m).toFixed(1)}`;
    pen = true;
  }
  return (
    <div ref={ref} className="chart">
      {W > 0 && (
        <svg width={W} height={H} role="img" aria-label="Surface temperature by local time: Diviner bins and the model">
          <g transform={`translate(${M.left},${M.top})`}>
            {y.ticks(5).map((v) => (
              <g key={v} className="axis"><line className="gridline" x1={0} x2={iw} y1={y(v)} y2={y(v)} />
                <text x={-6} y={y(v) + 4} textAnchor="end">{v}</text></g>
            ))}
            {[0, 6, 12, 18, 24].map((v) => (
              <g key={v} className="axis"><text x={x(v)} y={ih + 14} textAnchor="middle">{v}h</text></g>
            ))}
            <text className="axis-title" x={iw} y={ih + 27} textAnchor="end">local time</text>
            <text className="axis-title" x={4} y={8}>K</text>
            <path d={d} fill="none" stroke="var(--earth)" strokeWidth={2} />
            {db && <path d={db} fill="none" stroke="var(--earth)" strokeWidth={1.5} strokeDasharray="5 4" />}
            {series.map(([lt, v]) => v !== null && (
              <circle key={lt} cx={x(lt)} cy={y(v)} r={3.5} fill="var(--signal)" />
            ))}
          </g>
        </svg>
      )}
      <div className="key"><span className="k-earth">Model (same years, same averaging)</span>{bin && <span className="k-earth">- - model over the 240 m bin (after the check)</span>}<span className="k-signal">Diviner, measured</span></div>
    </div>
  );
}
