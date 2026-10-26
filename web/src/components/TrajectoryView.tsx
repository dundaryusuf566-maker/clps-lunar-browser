import { useEffect, useRef, useState } from "react";
import type { Trajectory, Vec3 } from "../types";

type Mode = "earth" | "moon";

// --- tiny vector kit ---------------------------------------------------------
const dot = (a: Vec3, b: Vec3) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
const cross = (a: Vec3, b: Vec3): Vec3 => [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]];
const norm = (a: Vec3) => Math.hypot(a[0], a[1], a[2]);
const unit = (a: Vec3): Vec3 => { const n = norm(a) || 1; return [a[0] / n, a[1] / n, a[2] / n]; };
const sub = (a: Vec3, b: Vec3): Vec3 => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
const scale = (a: Vec3, k: number): Vec3 => [a[0] * k, a[1] * k, a[2] * k];
const reject = (a: Vec3, n: Vec3): Vec3 => sub(a, scale(n, dot(a, n)));

/** Rows: right, up, toward-viewer. */
type Basis = [Vec3, Vec3, Vec3];

function baseBasis(traj: Trajectory, mode: Mode): Basis {
  if (mode === "earth") {
    const ring = traj.moon_ring_eci;
    const fwd = unit(cross(ring[0], ring[Math.floor(ring.length / 4)])); // Moon's orbit normal: look from above
    const right = unit(reject(traj.moon_arrival, fwd)); // Moon at arrival to the right
    return [right, cross(fwd, right), fwd];
  }
  const cap = traj.capture_mci;
  const fwd = unit(cross(cap[0], cap[Math.floor(cap.length / 4)])); // capture-orbit normal: orbit is a circle
  const up = unit(reject(traj.moon_pole, fwd)); // lunar north up
  return [cross(up, fwd), up, fwd];
}

function rotate(b: Basis, yaw: number, pitch: number): Basis {
  // yaw about the screen's up axis, then pitch about the screen's right axis
  const [r, u, f] = b;
  const cy = Math.cos(yaw), sy = Math.sin(yaw);
  const r1: Vec3 = [r[0] * cy - f[0] * sy, r[1] * cy - f[1] * sy, r[2] * cy - f[2] * sy];
  const f1: Vec3 = [r[0] * sy + f[0] * cy, r[1] * sy + f[1] * cy, r[2] * sy + f[2] * cy];
  const cp = Math.cos(pitch), sp = Math.sin(pitch);
  const u2: Vec3 = [u[0] * cp - f1[0] * sp, u[1] * cp - f1[1] * sp, u[2] * cp - f1[2] * sp];
  const f2: Vec3 = [u[0] * sp + f1[0] * cp, u[1] * sp + f1[1] * cp, u[2] * sp + f1[2] * cp];
  return [r1, u2, f2];
}

function cssVar(name: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
}

interface Props {
  traj: Trajectory;
  themeVersion: number;
}

export function TrajectoryView({ traj, themeVersion }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [mode, setMode] = useState<Mode>("earth");
  const [cam, setCam] = useState({ yaw: 0, pitch: 0, zoom: 1 });
  const drag = useRef<{ x: number; y: number; yaw: number; pitch: number } | null>(null);
  const [size, setSize] = useState(0);

  const reset = (m: Mode) => setCam({ yaw: 0, pitch: m === "moon" ? -0.28 : 0, zoom: 1 });
  useEffect(() => reset(mode), [mode, traj.id]);

  useEffect(() => {
    const el = canvasRef.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setSize(Math.floor(e.contentRect.width)));
    ro.observe(el);
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      setCam((c) => ({ ...c, zoom: Math.min(25, Math.max(0.4, c.zoom * Math.exp(-e.deltaY * 0.0015))) }));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => {
      ro.disconnect();
      el.removeEventListener("wheel", onWheel);
    };
  }, []);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || size === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = size * dpr;
    canvas.height = size * dpr;
    const ctx = canvas.getContext("2d")!;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, size, size);
    const C = {
      ink: cssVar("--ink"), ink2: cssVar("--ink-2"), ink3: cssVar("--ink-3"), signal: cssVar("--signal"),
      earth: cssVar("--earth"), moon: cssVar("--moon"), moonFill: cssVar("--moon-fill"), surface: cssVar("--surface"),
      sun: "#eda100",
    };
    const B = rotate(baseBasis(traj, mode), cam.yaw, cam.pitch);
    const half = size / 2;
    const extentKm =
      mode === "earth"
        ? Math.max(...traj.moon_ring_eci.map(norm), ...traj.sc_eci.map(norm)) * 1.16
        : traj.radii.moon * 3.1;
    const s = (half / extentKm) * cam.zoom;
    const P = (p: Vec3) => ({ x: half + dot(p, B[0]) * s, y: half - dot(p, B[1]) * s, z: dot(p, B[2]) });
    ctx.font = `12px ${cssVar("--font")}`;
    ctx.lineJoin = "round";
    ctx.lineCap = "round";

    const polyline = (pts: Vec3[], color: string, width: number, alpha = 1, occluder?: number) => {
      ctx.strokeStyle = color;
      ctx.lineWidth = width;
      ctx.globalAlpha = alpha;
      ctx.beginPath();
      let pen = false;
      for (const p of pts) {
        const q = P(p);
        const hidden = occluder !== undefined && q.z < 0 && Math.hypot(q.x - half, q.y - half) < occluder;
        if (hidden) { pen = false; continue; }
        if (pen) ctx.lineTo(q.x, q.y); else ctx.moveTo(q.x, q.y);
        pen = true;
      }
      ctx.stroke();
      ctx.globalAlpha = 1;
    };
    const disk = (c: { x: number; y: number }, r: number, fill: string, stroke?: string) => {
      ctx.beginPath();
      ctx.arc(c.x, c.y, r, 0, Math.PI * 2);
      ctx.fillStyle = fill;
      ctx.fill();
      if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = 1.25; ctx.stroke(); }
    };
    const label = (text: string, at: { x: number; y: number }, dx = 8, dy = -8, color = C.ink2, align: CanvasTextAlign = "left") => {
      ctx.fillStyle = color;
      // Keep labels inside the canvas: flip to the other side near the edges.
      const w = ctx.measureText(text).width;
      let x = at.x + dx;
      if (align === "left" && x + w > size - 6) { x = at.x - Math.abs(dx); align = "right"; }
      if (align === "right" && x - w < 6) { x = at.x + Math.abs(dx); align = "left"; }
      ctx.textAlign = align;
      ctx.fillText(text, x, Math.min(size - 6, Math.max(14, at.y + dy)));
    };
    const arrow = (from: { x: number; y: number }, dir: Vec3, len: number, color: string, text: string) => {
      const dx = dot(dir, B[0]), dy = -dot(dir, B[1]);
      const n = Math.hypot(dx, dy) || 1;
      const ux = dx / n, uy = dy / n;
      const to = { x: from.x + ux * len, y: from.y + uy * len };
      ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 1.5;
      ctx.beginPath(); ctx.moveTo(from.x, from.y); ctx.lineTo(to.x, to.y); ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(to.x, to.y);
      ctx.lineTo(to.x - ux * 7 - uy * 4, to.y - uy * 7 + ux * 4);
      ctx.lineTo(to.x - ux * 7 + uy * 4, to.y - uy * 7 - ux * 4);
      ctx.closePath(); ctx.fill();
      label(text, to, ux * 10, uy * 10 + 4, C.ink2, ux < -0.3 ? "right" : ux > 0.3 ? "left" : "center");
    };

    if (mode === "earth") {
      polyline(traj.moon_ring_eci, C.moon, 1, 0.8);
      const earth = P([0, 0, 0]);
      const moonStart = P(traj.moon_tli);
      const moonEnd = P(traj.moon_arrival);
      disk(moonStart, Math.max(3, traj.radii.moon * s), "transparent", C.moon);
      label("Moon at TLI", moonStart, 8, 14, C.ink3);
      polyline(traj.sc_eci, C.signal, 2.25);
      disk(earth, Math.max(4, traj.radii.earth * s), C.earth);
      label("Earth", earth, -10, 18, C.ink2, "right");
      disk(moonEnd, Math.max(4, traj.radii.moon * s), C.moonFill, C.moon);
      label("Moon at arrival", moonEnd, 10, -10, C.ink);
      const iSoi = traj.t.findIndex((t) => t >= traj.events.soi);
      if (iSoi > 0) {
        const q = P(traj.sc_eci[iSoi]);
        disk(q, 3.5, C.surface, C.signal);
      }
      const tli = P(traj.sc_eci[0]);
      disk(tli, 3.5, C.signal);
      arrow({ x: earth.x, y: earth.y }, traj.sun_dir, 46, C.sun, "Sun");
      void tli;
    } else {
      const R = traj.radii.moon * s;
      const center = P([0, 0, 0]);
      // far side first (occluded parts skipped), then the Moon, then near side
      disk(center, R, C.moonFill, C.moon);
      // equator and pole axis
      const pole = traj.moon_pole;
      const e1 = unit(reject(B[0], pole)), e2 = cross(pole, e1);
      const eq: Vec3[] = Array.from({ length: 97 }, (_, i) => {
        const a = (i / 96) * Math.PI * 2;
        return scale([e1[0] * Math.cos(a) + e2[0] * Math.sin(a), e1[1] * Math.cos(a) + e2[1] * Math.sin(a), e1[2] * Math.cos(a) + e2[2] * Math.sin(a)], traj.radii.moon);
      });
      polyline(eq, C.moon, 1, 0.9, R + 0.5);
      const np = P(scale(pole, traj.radii.moon * 1.35)), sp = P(scale(pole, -traj.radii.moon * 1.35));
      ctx.strokeStyle = C.ink3; ctx.lineWidth = 1; ctx.beginPath(); ctx.moveTo(sp.x, sp.y); ctx.lineTo(np.x, np.y); ctx.stroke();
      label("N", np, 6, 4, C.ink3);

      polyline(traj.capture_mci, C.signal, 1.75, 0.8, R);
      polyline(traj.approach_mci, C.signal, 2.25, 1, R);
      const peri = P(traj.approach_mci[traj.approach_mci.length - 1]);
      disk(peri, 4, C.signal);
      label("LOI at periselene", peri, 10, 4, C.ink);
      const earthDir = unit(scale(traj.moon_arrival, -1));
      const edge = (d: Vec3) => {
        const dx = dot(d, B[0]), dy = -dot(d, B[1]), n = Math.hypot(dx, dy) || 1;
        return { x: center.x + (dx / n) * (R + 6), y: center.y + (dy / n) * (R + 6) };
      };
      arrow(edge(traj.sun_dir), traj.sun_dir, 38, C.sun, "Sun");
      arrow(edge(earthDir), earthDir, 38, C.earth, "Earth");
    }
  }, [traj, mode, cam, size, themeVersion]);

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    drag.current = { x: e.clientX, y: e.clientY, yaw: cam.yaw, pitch: cam.pitch };
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>) => {
    const d = drag.current;
    if (!d) return;
    const k = Math.PI / Math.max(200, size);
    setCam((c) => ({ ...c, yaw: d.yaw + (e.clientX - d.x) * k, pitch: Math.max(-1.55, Math.min(1.55, d.pitch + (e.clientY - d.y) * k)) }));
  };
  const onKey = (e: React.KeyboardEvent) => {
    const step = 0.08;
    const map: Record<string, Partial<typeof cam>> = {
      ArrowLeft: { yaw: cam.yaw - step }, ArrowRight: { yaw: cam.yaw + step },
      ArrowUp: { pitch: Math.max(-1.55, cam.pitch - step) }, ArrowDown: { pitch: Math.min(1.55, cam.pitch + step) },
      "+": { zoom: Math.min(25, cam.zoom * 1.2) }, "=": { zoom: Math.min(25, cam.zoom * 1.2) }, "-": { zoom: Math.max(0.4, cam.zoom / 1.2) },
    };
    if (map[e.key]) { e.preventDefault(); setCam({ ...cam, ...map[e.key] }); }
  };

  return (
    <div className="orbit-view">
      <div className="toolbar">
        <h3>{mode === "earth" ? "Earth to Moon" : "Arrival at the Moon"}</h3>
        <div className="segmented" role="group" aria-label="View">
          <button aria-pressed={mode === "earth"} onClick={() => setMode("earth")}>Earth view</button>
          <button aria-pressed={mode === "moon"} onClick={() => setMode("moon")}>Moon view</button>
          <button onClick={() => reset(mode)}>Reset</button>
        </div>
      </div>
      <canvas
        ref={canvasRef}
        className="orbit-canvas"
        tabIndex={0}
        role="img"
        aria-label={mode === "earth"
          ? "Transfer path from Earth parking orbit to the Moon, Earth-centred inertial frame"
          : "Approach hyperbola and 100 km polar capture orbit around the Moon"}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={() => (drag.current = null)}
        onPointerCancel={() => (drag.current = null)}
        onDoubleClick={() => reset(mode)}
        onKeyDown={onKey}
      />
      <div className="key">
        <span className="k-path">This transfer</span>
        {mode === "earth" && <span className="k-soi">Enters the Moon's sphere of influence</span>}
        {mode === "earth" ? <span className="k-moon">Moon's path</span> : <span className="k-moon">Lunar equator</span>}
        <span className="k-sun">Sun direction</span>
      </div>
      <p className="orbit-note">Drag to rotate, scroll to zoom, double-click to reset. {mode === "earth"
        ? "Seen from above the Moon's orbital plane, J2000 inertial frame."
        : "Seen along the capture orbit's normal, lunar north up. The thin loop hugging the Moon is the 100 km orbit after LOI."}</p>
    </div>
  );
}
