import { utcFormat } from "d3-time-format";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { fmtNum } from "../lib/format";
import { contextAt, craftAt, loadJourneys, pointAt, quatMatrix, rotate, type Journey, type JourneysFile } from "../lib/scene3d/journey";
import { JourneyRenderer, PHASE_COLORS, type Frame } from "../lib/scene3d/journeyRenderer";
import { add, cross, DEG, lookAt, mul, norm, perspective, project, scale, sub, unit, type V3 } from "../lib/scene3d/math";
import type { View } from "../lib/scene3d/renderer";
import { readParams, writeParams } from "../lib/urlstate";

const BASE = import.meta.env.BASE_URL;
const HOUR = 3600;
const timeFmt = utcFormat("%-d %b %Y, %H:%M UTC");
type Cam = "earth" | "moon" | "craft";
const CAMS: Record<Cam, { label: string; frame: Frame }> = {
  earth: { label: "Earth and Moon", frame: "earth" },
  moon: { label: "Around the Moon", frame: "moon" },
  craft: { label: "Follow the spacecraft", frame: "moon" },
};
const KEY_EVENTS = new Set(["tli", "loi", "touchdown"]);
const rgb = (c: [number, number, number]) => `rgb(${c.map((v) => Math.round(v * 255)).join(",")})`;

function elapsed(t: number): string {
  const s = Math.abs(t), d = Math.floor(s / 86400), h = Math.floor((s % 86400) / 3600), m = Math.floor((s % 3600) / 60);
  return `T${t < 0 ? "−" : "+"}${d > 0 ? `${d} d ` : ""}${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}`;
}

/** Playback rate (mission seconds per second): slow near events, fast in the long coasts. */
function autoRate(j: Journey, t: number): number {
  let d = Infinity;
  for (const e of j.events) if (e.id !== "checkout" && e.id !== "plane") d = Math.min(d, Math.abs(t - e.t));
  return Math.min(Math.max(0.5 * d, 120), 12 * HOUR);
}

export function JourneyView() {
  const [data, setData] = useState<{ file: JourneysFile; cap: Float32Array | null } | null | "loading" | Error>("loading");
  useEffect(() => {
    let alive = true;
    loadJourneys(BASE).then((d) => alive && setData(d)).catch((e: Error) => alive && setData(e));
    return () => { alive = false; };
  }, []);
  if (data === "loading") return <p className="empty">Loading the journeys…</p>;
  if (data instanceof Error) return <p className="empty">Could not load the journeys ({data.message}).</p>;
  if (!data) {
    return (
      <p className="empty">
        No journey data yet. Build it with <code>python scripts/build_journeys.py --spice</code> (after the validation and
        forecast runs) and reload.
      </p>
    );
  }
  return <Journeys file={data.file} cap={data.cap} />;
}

function Journeys({ file, cap }: { file: JourneysFile; cap: Float32Array | null }) {
  const params = useMemo(() => readParams(), []);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const wrapRef = useRef<HTMLDivElement>(null);
  const labels = useRef(new Map<string, HTMLDivElement | null>());
  const rend = useRef<JourneyRenderer | null>(null);
  const [glError, setGlError] = useState<string | null>(null);
  const [mid, setMid] = useState(() => {
    const m = params.get("m");
    return file.missions.some((x) => x.id === m) ? m! : file.missions[0].id;
  });
  const j = file.missions.find((x) => x.id === mid)!;
  const tMin = j.t[0], tMax = j.t[j.t.length - 1];
  const [t, setT] = useState(() => {
    const v = Number(params.get("jt"));
    return Number.isFinite(v) && params.get("jt") !== null ? Math.min(Math.max(v, tMin), tMax) : 0;
  });
  const [cam, setCam] = useState<Cam>(() => (params.get("jcam") as Cam) in CAMS ? (params.get("jcam") as Cam) : "earth");
  const [playing, setPlaying] = useState(false);
  const [speed, setSpeed] = useState<number>(0);          // 0 = auto
  const [links, setLinks] = useState(true);
  const view = useRef({ yaw: 0, pitch: 0.4, dist: 900000 });
  const frameReq = useRef<number | null>(null);

  // default camera for a mode and mission
  const aim = useCallback((c: Cam, jj: Journey, tt: number) => {
    const set = (d: V3, dist: number) => {
      const u = unit(d);
      view.current = { yaw: Math.atan2(u[0], u[1]), pitch: Math.asin(Math.max(-1, Math.min(1, u[2]))), dist };
    };
    if (c === "earth") {
      const loi = jj.events.find((e) => e.id === "loi")!.t;
      const n = cross(jj.eci[Math.floor(jj.t.length * 0.1)], contextAt(jj, loi).moon);
      set(add(scale(unit(n), 0.85), scale(unit(contextAt(jj, loi).moon), -0.25)), 560000);
    } else if (c === "moon") {
      const ctx = contextAt(jj, tt), pole = rotate(quatMatrix(ctx.qMoon), [0, 0, 1]);
      const k = jj.phase.indexOf(2);
      const h = k >= 0 ? cross(jj.mci[k], jj.mci[k + 1]) : [1, 0, 0] as V3;
      set(add(unit(h), scale(pole, -0.45)), 9000);
    } else {
      const cr = craftAt(jj, tt), r = unit(cr.mci);
      const v = unit(sub(jj.mci[Math.min(cr.i + 1, jj.t.length - 1)], jj.mci[cr.i]));
      set(add(scale(r, 0.6), scale(v, -0.8)), Math.max(150, Math.min(1500, (norm(cr.mci) - 1737.4) * 4)));
    }
  }, []);

  useEffect(() => { aim(cam, j, t); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, []);

  useEffect(() => {
    const c = canvasRef.current!;
    let r: JourneyRenderer;
    try {
      r = new JourneyRenderer(c, file.meta.moon_cap, cap);
    } catch (e) {
      setGlError((e as Error).message);
      return;
    }
    rend.current = r;
    return () => { rend.current = null; r.dispose(); };
  }, [file, cap]);

  useEffect(() => { rend.current?.setJourney(j); requestDraw(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [j, glError]);

  const draw = useCallback(() => {
    const r = rend.current, c = canvasRef.current;
    if (!r || !c || !r.j) return;
    const frame = CAMS[cam].frame, k = view.current;
    const cr = craftAt(j, t);
    const target: V3 = cam === "earth" ? scale(contextAt(j, j.events.find((e) => e.id === "loi")!.t).moon, 0.45)
      : cam === "moon" ? [0, 0, 0] : cr.mci;
    const w = c.width, h = c.height, fov = 45 * DEG, far = 4e6;
    const fit = cam === "craft" ? 1 : Math.max(1, 1.4 / (w / h));        // keep the scene in a narrow (portrait) view
    const eye = add(target, scale([Math.cos(k.pitch) * Math.sin(k.yaw), Math.cos(k.pitch) * Math.cos(k.yaw), Math.sin(k.pitch)], k.dist * fit));
    const vm = lookAt(eye, target, [0, 0, 1]), pm = perspective(fov, w / h, 0.005, far), vp = mul(pm, vm);
    const tanY = Math.tan(fov / 2);
    const v: View = { viewProj: vp, eye, far, tanX: tanY * w / h, tanY,
      right: [vm[0], vm[4], vm[8]], up: [vm[1], vm[5], vm[9]], fwd: [-vm[2], -vm[6], -vm[10]] };
    const out = r.draw(v, { frame, t, enlarge: 1, showLinks: links });
    if (!out) return;
    const d = Math.min(window.devicePixelRatio || 1, 1.75);
    const place = (key: string, p: V3 | null) => {
      const el = labels.current.get(key);
      if (!el) return;
      const q = p ? project(vp, p) : null;
      if (!q || Math.abs(q.x) > 1.02 || Math.abs(q.y) > 1.02) { el.style.display = "none"; return; }
      el.style.display = "";
      el.style.transform = `translate(${((q.x + 1) / 2) * (w / d)}px, ${((1 - q.y) / 2) * (h / d)}px)`;
    };
    place("earth", out.earth);
    place("moon", out.moon);
    place("craft", out.craft);
    place("site", cam === "earth" ? null : out.site);
    for (const e of j.events) if (KEY_EVENTS.has(e.id)) place(`ev-${e.id}`, pointAt(j, e.t, frame));
  }, [cam, j, t, links]);

  const requestDraw = useCallback(() => {
    if (frameReq.current !== null) return;
    frameReq.current = requestAnimationFrame(() => { frameReq.current = null; draw(); });
  }, [draw]);
  useEffect(() => { requestDraw(); }, [requestDraw]);

  useEffect(() => {
    const c = canvasRef.current!, wrap = wrapRef.current!;
    const ro = new ResizeObserver(() => {
      const d = Math.min(window.devicePixelRatio || 1, 1.75);
      c.width = Math.max(1, Math.round(wrap.clientWidth * d));
      c.height = Math.max(1, Math.round(wrap.clientHeight * d));
      requestDraw();
    });
    ro.observe(wrap);
    return () => ro.disconnect();
  }, [requestDraw]);

  // play
  useEffect(() => {
    if (!playing) return;
    let last = performance.now(), id = 0;
    const tick = (now: number) => {
      const dt = Math.min(0.1, (now - last) / 1000);
      last = now;
      setT((x) => {
        const y = x + dt * (speed || autoRate(j, x));
        if (y >= tMax) { setPlaying(false); return tMax; }
        return y;
      });
      id = requestAnimationFrame(tick);
    };
    id = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(id);
  }, [playing, speed, j, tMax]);

  // link
  useEffect(() => {
    if (playing) return;
    const id = window.setTimeout(() => writeParams({ scene: "journey", m: mid, jt: Math.round(t), jcam: cam === "earth" ? null : cam }), 300);
    return () => window.clearTimeout(id);
  }, [mid, t, cam, playing]);

  // pointer
  useEffect(() => {
    const c = canvasRef.current!;
    const pts = new Map<number, { x: number; y: number }>();
    let startDist = 0, startVal = 0;
    const minDist = () => (cam === "earth" ? 15000 : cam === "moon" ? 1900 : 0.3);
    const maxDist = () => (cam === "earth" ? 3e6 : cam === "moon" ? 400000 : 30000);
    const down = (e: PointerEvent) => {
      c.setPointerCapture(e.pointerId);
      pts.set(e.pointerId, { x: e.clientX, y: e.clientY });
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        startDist = Math.hypot(a.x - b.x, a.y - b.y);
        startVal = view.current.dist;
      }
    };
    const move = (e: PointerEvent) => {
      const p = pts.get(e.pointerId);
      if (!p) return;
      const dx = e.clientX - p.x, dy = e.clientY - p.y;
      p.x = e.clientX; p.y = e.clientY;
      const k = view.current;
      if (pts.size === 2) {
        const [a, b] = [...pts.values()];
        k.dist = Math.min(Math.max(startVal * startDist / Math.max(1, Math.hypot(a.x - b.x, a.y - b.y)), minDist()), maxDist());
      } else {
        k.yaw -= dx * 0.006;
        k.pitch = Math.min(Math.max(k.pitch + dy * 0.006, -1.5), 1.5);
      }
      requestDraw();
    };
    const up = (e: PointerEvent) => { pts.delete(e.pointerId); };
    const wheel = (e: WheelEvent) => {
      e.preventDefault();
      const k = view.current;
      k.dist = Math.min(Math.max(k.dist * Math.exp(e.deltaY * 0.0015), minDist()), maxDist());
      requestDraw();
    };
    c.addEventListener("pointerdown", down);
    c.addEventListener("pointermove", move);
    c.addEventListener("pointerup", up);
    c.addEventListener("pointercancel", up);
    c.addEventListener("wheel", wheel, { passive: false });
    return () => {
      c.removeEventListener("pointerdown", down);
      c.removeEventListener("pointermove", move);
      c.removeEventListener("pointerup", up);
      c.removeEventListener("pointercancel", up);
      c.removeEventListener("wheel", wheel);
    };
  }, [cam, requestDraw]);

  function chooseCam(c: Cam) { aim(c, j, t); setCam(c); }
  function chooseMission(id: string) {
    const jj = file.missions.find((x) => x.id === id)!;
    setPlaying(false);
    setMid(id);
    setT(0);
    aim(cam === "craft" ? "earth" : cam, jj, 0);
    if (cam === "craft") setCam("earth");
  }
  function jump(e: { id: string; t: number }) {
    setPlaying(false);
    const tt = e.id === "touchdown" ? e.t - 2 * 60 : e.t;
    setT(tt);
    const c: Cam = ["tli", "parking", "soi"].includes(e.id) ? "earth" : ["deorbit", "braking", "touchdown"].includes(e.id) ? "craft" : "moon";
    aim(c, j, tt);
    setCam(c);
  }

  const cr = craftAt(j, t);
  const utc = new Date(Date.parse(j.t0_utc) + t * 1000);
  const altMoon = norm(cr.mci) - j.radii.moon, altEarth = norm(cr.eci) - j.radii.earth;
  const dsn = j.stations.filter((s) => cr.dsn & s.bit).map((s) => s.name);
  const f = j.facts;
  const span = tMax - tMin;

  return (
    <>
      <section className="panel" aria-label="3D journey">
        <div className="scene-stage" ref={wrapRef}>
          <canvas ref={canvasRef} className="scene-canvas" tabIndex={0} aria-label={`3D journey of ${j.name}, ${CAMS[cam].label}, ${elapsed(t)}`}
            onKeyDown={(e) => { if (e.key === " ") { e.preventDefault(); setPlaying((p) => !p); } }} />
          <div ref={(el) => { labels.current.set("earth", el); }} className="scene-sky earth">Earth</div>
          <div ref={(el) => { labels.current.set("moon", el); }} className="scene-sky moon">Moon</div>
          <div ref={(el) => { labels.current.set("craft", el); }} className="scene-pin on"><span>{j.name.split(" (")[0]}</span></div>
          <div ref={(el) => { labels.current.set("site", el); }} className="scene-sky site">{j.site_name}</div>
          {j.events.filter((e) => KEY_EVENTS.has(e.id)).map((e) => (
            <div key={e.id} ref={(el) => { labels.current.set(`ev-${e.id}`, el); }} className="scene-sky event">{e.id === "touchdown" ? "" : e.id.toUpperCase()}</div>
          ))}
          <div className="scene-hud">
            <strong className="num">{elapsed(t)}</strong>
            <span className="num">{timeFmt(utc)}</span>
            <span><span className="phase-dot" style={{ background: rgb(PHASE_COLORS[cr.phase]) }} />{j.phase_names[cr.phase]}</span>
            <span className="num">{cr.phase >= 2 || altMoon < 60000 ? `${fmtNum(altMoon, altMoon < 100 ? 1 : 0)} km above the Moon, ${fmtNum(cr.vMoon, 2)} km/s`
              : `${fmtNum(altEarth, 0)} km from Earth, ${fmtNum(cr.vEarth, 2)} km/s`}</span>
            <span>{dsn.length ? `DSN: ${dsn.join(", ")}` : "No DSN station in view"}</span>
          </div>
          {glError && <p className="scene-error">The 3D view needs WebGL2: {glError}</p>}
          <p className="scene-help">Drag to turn, scroll or pinch to zoom. Bright path: flown so far; green: DSN stations that see the spacecraft (10° mask).</p>
        </div>
        <div className="panel-body scene-controls">
          <div className="journey-timeline" aria-hidden="true">
            {j.phase_names.map((name, k) => {
              const idx = j.phase.map((p, i) => (p === k ? i : -1)).filter((i) => i >= 0);
              if (!idx.length) return null;
              const a = j.t[idx[0] > 0 ? idx[0] - 1 : 0], b = j.t[idx[idx.length - 1]];
              return <span key={name} title={name} style={{ left: `${((a - tMin) / span) * 100}%`, width: `${Math.max(0.4, ((b - a) / span) * 100)}%`, background: rgb(PHASE_COLORS[k]) }} />;
            })}
            <i style={{ left: `${((t - tMin) / span) * 100}%` }} />
          </div>
          <div className="scene-time">
            <button className="play" onClick={() => setPlaying((p) => !p)} aria-pressed={playing}>{playing ? "Pause" : "Play"}</button>
            <input type="range" min={tMin} max={tMax} step={60} value={t} aria-label="Mission time"
              onChange={(e) => { setPlaying(false); setT(Number(e.target.value)); }} />
            <label className="control">Speed
              <select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
                <option value={0}>Auto (slow near events)</option>
                <option value={600}>10 min / s</option>
                <option value={3600}>1 h / s</option>
                <option value={21600}>6 h / s</option>
              </select>
            </label>
          </div>
          <div className="controls">
            <div className="control">
              <span id="j-mission">Mission</span>
              <div className="segmented" role="group" aria-labelledby="j-mission">
                {file.missions.map((m) => (
                  <button key={m.id} aria-pressed={m.id === mid} onClick={() => chooseMission(m.id)}>
                    {m.name.split(" (")[0]}{m.kind === "forecast" ? " (forecast)" : ""}
                  </button>
                ))}
              </div>
            </div>
            <div className="control">
              <span id="j-cam">Camera</span>
              <div className="segmented" role="group" aria-labelledby="j-cam">
                {(Object.keys(CAMS) as Cam[]).map((c) => <button key={c} aria-pressed={cam === c} onClick={() => chooseCam(c)}>{CAMS[c].label}</button>)}
              </div>
            </div>
            <label className="control check"><input type="checkbox" checked={links} onChange={(e) => setLinks(e.target.checked)} /> DSN links</label>
          </div>
          <div className="scene-jumps">
            <span>Go to</span>
            {j.events.filter((e) => e.id !== "checkout").map((e) => (
              <button key={e.id} onClick={() => jump(e)} title={e.utc}>{e.label.replace(/ \(.*\)$/, "")}</button>
            ))}
          </div>
        </div>
      </section>

      <div className="val-grid">
        <section className="panel" aria-labelledby="j-facts">
          <div className="panel-head"><h2 id="j-facts">{j.name}</h2><span className="hint">{j.kind === "flown" ? "flown, reconstructed" : "forecast"}</span></div>
          <div className="panel-body">
            <p className="val-story">{j.story}</p>
            <table>
              <thead><tr><th className="left">Step</th><th className="left">Engine</th>{j.kind === "flown" && <th className="left">Real mission</th>}</tr></thead>
              <tbody>
                {j.kind === "flown" && <tr><td className="left">Launch</td><td className="left">–</td><td className="left num">{String(f.launch_utc).replace("T", " ").slice(0, 16)}</td></tr>}
                <tr><td className="left">Trans-lunar injection</td><td className="left num">{String(f.tli_utc).replace("T", " ").slice(0, 16)}, {fmtNum(Number(f.tli_dv_ms), 0)} m/s</td>{j.kind === "flown" && <td className="left">same date (input)</td>}</tr>
                <tr><td className="left">Coast</td><td className="left num">{fmtNum(Number(f.tof_days), 2)} d</td>{j.kind === "flown" && <td className="left">same (input)</td>}</tr>
                <tr><td className="left">Lunar orbit insertion</td><td className="left num">{String(f.loi_utc).replace("T", " ").slice(0, 16)}, {fmtNum(Number(f.loi_dv_ms), 0)} m/s</td>
                  {j.kind === "flown" && <td className="left num">{String(f.real_loi_utc).replace("T", " ").slice(0, 16)}{f.real_loi_dv_ms ? `, ${fmtNum(Number(f.real_loi_dv_ms), 0)} m/s` : ", Δv not published"}</td>}</tr>
                <tr><td className="left">Orbit</td><td className="left num">{fmtNum(j.orbit.alt_km, 0)} km, {fmtNum(j.orbit.inc_deg, 1)}°, {fmtNum(j.orbit.period_min, 0)} min</td>{j.kind === "flown" && <td className="left">–</td>}</tr>
                <tr><td className="left">Wait in orbit</td><td className="left num">{fmtNum(Number(f.wait_days), 2)} d</td>{j.kind === "flown" && <td className="left">–</td>}</tr>
                <tr><td className="left">Plane change</td><td className="left num">{fmtNum(Number(f.plane_change_deg), 2)}°, {fmtNum(Number(f.plane_change_ms), 1)} m/s</td>{j.kind === "flown" && <td className="left">–</td>}</tr>
                {j.kind === "forecast" && f.daylight_days != null && <tr><td className="left">Sunlight after touchdown</td><td className="left num">{fmtNum(Number(f.daylight_days), 1)} d</td></tr>}
                <tr><td className="left">Touchdown</td><td className="left num">{String(f.landing_utc).replace("T", " ").slice(0, 16)}</td>
                  {j.kind === "flown" && <td className="left num">{String(f.real_landing_utc).replace("T", " ").slice(0, 16)} (used as input)</td>}</tr>
              </tbody>
            </table>
            {j.kind === "forecast" && <p className="table-note">Registered forecast <code>{String(f.forecast_sha256).slice(0, 16)}…</code>, launch window {String(f.window)}.</p>}
          </div>
        </section>
        <section className="panel" aria-labelledby="j-honest">
          <div className="panel-head"><h2 id="j-honest">What this path is, and is not</h2></div>
          <div className="panel-body">
            <ul className="plain-list">
              {file.meta.notes.map((n) => <li key={n}>{n}</li>)}
              <li>For this mission the drawing shifts the spacecraft along its orbit by {fmtNum(Math.abs(j.orbit.phase_adjust_deg), 0)}° over the
                wait, {fmtNum(j.orbit.phase_adjust_pct_of_motion, 2)}% of its orbital motion, so it is over the site at the landing time.</li>
              <li>Coast: {fmtNum(Number(f.tof_days), 2)} days in the engine's force model (Earth, Moon and Sun gravity, Earth and lunar zonal harmonics).
                {file.meta.ephemeris.includes("spice") ? " JPL DE440." : " Analytic ephemeris (demo data)."} Earth and Moon are to scale.</li>
              <li>The Moon's south polar terrain is LOLA{file.meta.moon_cap ? ` (${fmtNum(file.meta.moon_cap.step_km, 1)} km blocks)` : " (not built: no map)"}, lit without cast shadows here; the Landing region view has the real shadows.</li>
            </ul>
            {j.sources.length > 0 && (
              <details className="sources"><summary>Sources</summary>
                <ul>{j.sources.map(([label, url]) => <li key={url}><a href={url} target="_blank" rel="noreferrer">{label}</a></li>)}</ul>
              </details>
            )}
          </div>
        </section>
      </div>
    </>
  );
}
