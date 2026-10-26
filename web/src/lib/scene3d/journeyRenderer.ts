/** WebGL2 renderer of a mission journey: Earth, Moon (with the LOLA south polar
 *  terrain), the mission path, the spacecraft and the DSN links. */
import { upOf } from "./data";
import { contextAt, craftAt, mat3, quatMatrix, rotate, type CapMeta, type Journey } from "./journey";
import { norm, scale, sub, unit, type V3 } from "./math";
import { Program, type View } from "./renderer";
import { BODY_FS, FLAT_FS, OBJ_VS, PATH_FS, PATH_VS, QUAD_VS, SKY_FS } from "./shaders";

type GL = WebGL2RenderingContext;
export type Frame = "earth" | "moon";
interface Mesh { vao: WebGLVertexArrayObject; count: number; buffers: WebGLBuffer[]; mode: number; indexed: boolean }

export const PHASE_COLORS: [number, number, number][] = [
  [0.6, 0.65, 0.72],     // parking orbit
  [0.42, 0.66, 1.0],     // coast
  [0.94, 0.42, 0.71],    // lunar orbit
  [1.0, 0.72, 0.3],      // descent
];
const IDENTITY = new Float32Array([1, 0, 0, 0, 1, 0, 0, 0, 1]);

export interface DrawState { frame: Frame; t: number; enlarge: number; showLinks: boolean }

export class JourneyRenderer {
  readonly gl: GL;
  private sky: Program; private body: Program; private flat: Program; private path: Program;
  private sphere: Mesh; private grat: Mesh; private cap: Mesh | null = null; private dot: Mesh;
  private stations: Mesh | null = null;
  private paths: Record<Frame, Mesh> | null = null;
  private tracks: Record<Frame, Mesh> | null = null;      // the Moon's path (Earth frame) / the Earth's (Moon frame)
  private link: { vao: WebGLVertexArrayObject; buf: WebGLBuffer };
  private quadVao: WebGLVertexArrayObject;
  j: Journey | null = null;
  moonGain = 4;

  constructor(readonly canvas: HTMLCanvasElement, capMeta: CapMeta | null, capH: Float32Array | null) {
    const gl = canvas.getContext("webgl2", { antialias: true, preserveDrawingBuffer: true });
    if (!gl) throw new Error("WebGL2 is not available in this browser");
    this.gl = gl;
    this.sky = new Program(gl, QUAD_VS, SKY_FS);
    this.body = new Program(gl, OBJ_VS, BODY_FS);
    this.flat = new Program(gl, OBJ_VS, FLAT_FS);
    this.path = new Program(gl, PATH_VS, PATH_FS);
    this.quadVao = gl.createVertexArray()!;
    this.sphere = this.unitSphere(96, 192);
    this.grat = this.graticule();
    this.dot = this.mesh([new Float32Array([0, 0, 0]), new Float32Array([0, 0, 1])], null, gl.POINTS);
    if (capMeta && capH) this.cap = this.capMesh(capMeta, capH);
    const vao = gl.createVertexArray()!, buf = gl.createBuffer()!;
    gl.bindVertexArray(vao);
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array(6), gl.DYNAMIC_DRAW);
    gl.enableVertexAttribArray(0);
    gl.vertexAttribPointer(0, 3, gl.FLOAT, false, 0, 0);
    gl.vertexAttrib3f(1, 0, 0, 1);
    gl.bindVertexArray(null);
    this.link = { vao, buf };
  }

  // --- meshes ----------------------------------------------------------------------------
  private mesh(attrs: Float32Array[], idx: Uint32Array | null, mode: number, extra?: { loc: number; size: number; data: Float32Array }[]): Mesh {
    const gl = this.gl, vao = gl.createVertexArray()!, buffers: WebGLBuffer[] = [];
    gl.bindVertexArray(vao);
    attrs.forEach((a, k) => {
      const b = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, a, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(k);
      gl.vertexAttribPointer(k, 3, gl.FLOAT, false, 0, 0);
      buffers.push(b);
    });
    for (const e of extra ?? []) {
      const b = gl.createBuffer()!;
      gl.bindBuffer(gl.ARRAY_BUFFER, b);
      gl.bufferData(gl.ARRAY_BUFFER, e.data, gl.STATIC_DRAW);
      gl.enableVertexAttribArray(e.loc);
      gl.vertexAttribPointer(e.loc, e.size, gl.FLOAT, false, 0, 0);
      buffers.push(b);
    }
    if (idx) {
      const ib = gl.createBuffer()!;
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, ib);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, idx, gl.STATIC_DRAW);
      buffers.push(ib);
    }
    gl.bindVertexArray(null);
    return { vao, count: idx ? idx.length : attrs[0].length / 3, buffers, mode, indexed: !!idx };
  }

  private unitSphere(nLat: number, nLon: number): Mesh {
    const pos: number[] = [], idx: number[] = [];
    for (let a = 0; a <= nLat; a++) {
      const lat = -Math.PI / 2 + (Math.PI * a) / nLat;
      for (let b = 0; b <= nLon; b++) {
        const lon = (2 * Math.PI * b) / nLon;
        pos.push(Math.cos(lat) * Math.cos(lon), Math.cos(lat) * Math.sin(lon), Math.sin(lat));
      }
    }
    for (let a = 0; a < nLat; a++)
      for (let b = 0; b < nLon; b++) {
        const i = a * (nLon + 1) + b;
        idx.push(i, i + 1, i + nLon + 1, i + 1, i + nLon + 2, i + nLon + 1);
      }
    const p = new Float32Array(pos);
    return this.mesh([p, p], new Uint32Array(idx), this.gl.TRIANGLES);
  }

  /** Meridians every 30 deg and parallels every 30 deg on a unit sphere (line segments). */
  private graticule(): Mesh {
    const pts: number[] = [];
    const seg = (a: V3, b: V3) => pts.push(...a, ...b);
    const p = (lat: number, lon: number): V3 => {
      const la = (lat * Math.PI) / 180, lo = (lon * Math.PI) / 180;
      return [Math.cos(la) * Math.cos(lo), Math.cos(la) * Math.sin(lo), Math.sin(la)].map((v) => v * 1.002) as V3;
    };
    for (let lon = 0; lon < 360; lon += 30) for (let lat = -88; lat < 88; lat += 4) seg(p(lat, lon), p(lat + 4, lon));
    for (let lat = -60; lat <= 60; lat += 30) for (let lon = 0; lon < 360; lon += 4) seg(p(lat, lon), p(lat, lon + 4));
    const a = new Float32Array(pts);
    return this.mesh([a, a], null, this.gl.LINES);
  }

  /** LOLA south polar map (block means) as a mesh in Moon-fixed km. */
  private capMesh(m: CapMeta, h: Float32Array): Mesh {
    const n = m.n, R = 1737.4;
    const pos = new Float32Array(n * n * 3), ok = new Uint8Array(n * n);
    for (let j = 0; j < n; j++)
      for (let i = 0; i < n; i++) {
        const k = j * n + i, X = m.x0_km + i * m.step_km, Y = m.y0_km + j * m.step_km, hh = h[k];
        const u = upOf(X, Y, R);
        ok[k] = Number.isFinite(hh) ? 1 : 0;
        pos.set(scale(u, R + (ok[k] ? hh : 0)), k * 3);
      }
    const nor = new Float32Array(n * n * 3);
    const at = (i: number, j: number): V3 => {
      const k = Math.min(Math.max(j, 0), n - 1) * n + Math.min(Math.max(i, 0), n - 1);
      return [pos[k * 3], pos[k * 3 + 1], pos[k * 3 + 2]];
    };
    for (let j = 0; j < n; j++)
      for (let i = 0; i < n; i++) {
        const dx = sub(at(i + 1, j), at(i - 1, j)), dy = sub(at(i, j + 1), at(i, j - 1));
        let nn: V3 = [dy[1] * dx[2] - dy[2] * dx[1], dy[2] * dx[0] - dy[0] * dx[2], dy[0] * dx[1] - dy[1] * dx[0]];
        const p = at(i, j);
        if (nn[0] * p[0] + nn[1] * p[1] + nn[2] * p[2] < 0) nn = scale(nn, -1);
        nor.set(unit(nn), (j * n + i) * 3);
      }
    const idx: number[] = [];
    for (let j = 0; j < n - 1; j++)
      for (let i = 0; i < n - 1; i++) {
        const a = j * n + i, b = a + 1, c = a + n, d = c + 1;
        if (ok[a] && ok[b] && ok[c] && ok[d]) idx.push(a, c, b, b, c, d);
      }
    return this.mesh([pos, nor], new Uint32Array(idx), this.gl.TRIANGLES);
  }

  setJourney(j: Journey) {
    const gl = this.gl;
    for (const m of [...Object.values(this.paths ?? {}), ...Object.values(this.tracks ?? {})]) {
      m.buffers.forEach((b) => gl.deleteBuffer(b));
      gl.deleteVertexArray(m.vao);
    }
    if (this.stations) { this.stations.buffers.forEach((b) => gl.deleteBuffer(b)); gl.deleteVertexArray(this.stations.vao); }
    this.j = j;
    const time = new Float32Array(j.t), phase = new Float32Array(j.phase.flatMap((p) => [p, 0]));
    const mk = (pts: V3[]) => this.mesh([new Float32Array(pts.flat())], null, gl.LINE_STRIP,
      [{ loc: 2, size: 2, data: phase }, { loc: 3, size: 1, data: time }]);
    this.paths = { earth: mk(j.eci), moon: mk(j.mci) };
    const mt = new Float32Array(j.hourly.moon.flat()), et = mt.map((v) => -v);
    this.tracks = { earth: this.mesh([mt, mt], null, gl.LINE_STRIP), moon: this.mesh([et, et], null, gl.LINE_STRIP) };
    const st = new Float32Array(j.stations.flatMap((s) => s.ecef));
    this.stations = this.mesh([st, st], null, gl.POINTS);
  }

  // --- frame -----------------------------------------------------------------------------
  draw(v: View, st: DrawState): { earth: V3; moon: V3; craft: V3; site: V3 } | null {
    const gl = this.gl, j = this.j, c = this.canvas;
    gl.bindFramebuffer(gl.FRAMEBUFFER, null);
    gl.viewport(0, 0, c.width, c.height);
    gl.clearColor(0, 0, 0, 1);
    gl.clearDepth(1);
    gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
    if (!j || !this.paths) return null;
    const ctx = contextAt(j, st.t), craft = craftAt(j, st.t);
    const earth: V3 = st.frame === "earth" ? [0, 0, 0] : scale(ctx.moon, -1);
    const moon: V3 = st.frame === "earth" ? ctx.moon : [0, 0, 0];
    const sc = st.frame === "earth" ? craft.eci : craft.mci;
    const Rm = quatMatrix(ctx.qMoon), Re = quatMatrix(ctx.qEarth);
    const site: V3 = [moon[0], moon[1], moon[2]];
    const sp = rotate(Rm, scale(j.site.fixed, j.radii.moon + j.site.height_m / 1000));
    site[0] += sp[0]; site[1] += sp[1]; site[2] += sp[2];

    // sky with the Sun
    gl.disable(gl.DEPTH_TEST);
    const sk = this.sky;
    gl.useProgram(sk.p);
    gl.uniform3f(sk.u("uRight"), ...scale(v.right, v.tanX));
    gl.uniform3f(sk.u("uUp"), ...scale(v.up, v.tanY));
    gl.uniform3f(sk.u("uFwd"), ...v.fwd);
    gl.uniform3f(sk.u("uSunDir"), ...ctx.sun);
    gl.uniform3f(sk.u("uEarthDir"), 0, 0, 1);
    gl.uniform1f(sk.u("uSunRad"), 0.2666 * Math.PI / 180);
    gl.uniform1f(sk.u("uEarthRad"), 0);
    gl.uniform1f(sk.u("uGlow"), 1);
    gl.bindVertexArray(this.quadVao);
    gl.drawArrays(gl.TRIANGLES, 0, 3);

    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    const vp = new Float32Array(v.viewProj), logC = 2 / Math.log2(v.far + 1);
    const use = (p: Program) => {
      gl.useProgram(p.p);
      gl.uniformMatrix4fv(p.u("uViewProj"), false, vp);
      gl.uniform1f(p.u("uLogC"), logC);
    };
    const place = (p: Program, rot: Float32Array, center: V3, s: number) => {
      gl.uniformMatrix3fv(p.u("uRot"), false, rot);
      gl.uniform3f(p.u("uCenter"), ...center);
      gl.uniform1f(p.u("uScale"), s);
    };
    const drawMesh = (m: Mesh) => {
      gl.bindVertexArray(m.vao);
      if (m.indexed) gl.drawElements(m.mode, m.count, gl.UNSIGNED_INT, 0); else gl.drawArrays(m.mode, 0, m.count);
    };
    const eScale = j.radii.earth * st.enlarge, mScale = st.enlarge;

    // Earth and Moon
    const b = this.body;
    use(b);
    gl.uniform3f(b.u("uSun"), ...ctx.sun);
    gl.uniform1f(b.u("uGain"), this.moonGain);
    gl.uniform1f(b.u("uPointSize"), 1);
    gl.uniform1i(b.u("uKind"), 0);
    place(b, mat3(Re), earth, eScale);
    drawMesh(this.sphere);
    gl.uniform1i(b.u("uKind"), 1);
    place(b, mat3(Rm), moon, (j.radii.moon - (this.cap ? 8 : 0)) * mScale);
    drawMesh(this.sphere);
    if (this.cap) {
      place(b, mat3(Rm), moon, mScale);
      drawMesh(this.cap);
    }

    // Earth graticule, DSN stations
    const f = this.flat;
    use(f);
    gl.enable(gl.BLEND);
    gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
    gl.uniform1i(f.u("uRound"), 0);
    gl.uniform4f(f.u("uColor"), 0.75, 0.85, 1, 0.22);
    place(f, mat3(Re), earth, eScale);
    drawMesh(this.grat);
    if (this.stations) {
      gl.uniform1i(f.u("uRound"), 1);
      gl.uniform1f(f.u("uPointSize"), 6 * devicePixelRatio);
      gl.uniform4f(f.u("uColor"), 0.55, 0.95, 0.6, 1);
      place(f, mat3(Re), earth, st.enlarge);
      drawMesh(this.stations);
    }
    // DSN links to the spacecraft
    if (st.showLinks) {
      gl.uniform1i(f.u("uRound"), 0);
      gl.uniform4f(f.u("uColor"), 0.55, 0.95, 0.6, 0.45);
      place(f, IDENTITY, [0, 0, 0], 1);
      gl.bindVertexArray(this.link.vao);
      for (const s of j.stations) {
        if (!(craft.dsn & s.bit)) continue;
        const p = rotate(Re, scale(s.ecef, st.enlarge));
        gl.bindBuffer(gl.ARRAY_BUFFER, this.link.buf);
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, new Float32Array([earth[0] + p[0], earth[1] + p[1], earth[2] + p[2], ...sc]));
        gl.drawArrays(gl.LINES, 0, 2);
      }
    }

    if (this.tracks) {
      gl.uniform1i(f.u("uRound"), 0);
      gl.uniform4f(f.u("uColor"), 0.8, 0.82, 0.86, 0.28);
      place(f, IDENTITY, [0, 0, 0], 1);
      drawMesh(this.tracks[st.frame]);
    }

    // path
    const pp = this.path;
    use(pp);
    gl.uniform1f(pp.u("uNow"), st.t);
    gl.uniform3f(pp.u("uOffset"), 0, 0, 0);
    gl.uniform3fv(pp.u("uColors"), new Float32Array(PHASE_COLORS.flat()));
    drawMesh(this.paths[st.frame]);

    // spacecraft and site
    use(f);
    gl.uniform1i(f.u("uRound"), 1);
    gl.uniform1f(f.u("uPointSize"), 9 * devicePixelRatio);
    gl.uniform4f(f.u("uColor"), 1, 1, 1, 1);
    place(f, IDENTITY, sc, 1);
    gl.bindVertexArray(this.dot.vao);
    gl.drawArrays(gl.POINTS, 0, 1);
    gl.uniform1f(f.u("uPointSize"), 7 * devicePixelRatio);
    gl.uniform4f(f.u("uColor"), 1, 0.72, 0.3, 1);
    place(f, IDENTITY, site, 1);
    gl.drawArrays(gl.POINTS, 0, 1);
    gl.disable(gl.BLEND);
    gl.bindVertexArray(null);
    return { earth, moon, craft: sc, site };
  }

  /** Distance from the camera to the nearest surface, for zoom limits. */
  static clearance(eye: V3, earth: V3, moon: V3, rEarth: number, rMoon: number) {
    return Math.min(norm(sub(eye, earth)) - rEarth, norm(sub(eye, moon)) - rMoon);
  }

  dispose() {
    const gl = this.gl;
    for (const p of [this.sky, this.body, this.flat, this.path]) gl.deleteProgram(p.p);
  }
}
