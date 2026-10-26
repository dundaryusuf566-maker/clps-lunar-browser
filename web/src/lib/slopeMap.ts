/**
 * The tilt of the ground over a polar cap (scripts/build_slope_map.py, engine/surface/slope_map.py):
 * one surface normal per 240 m block of the LOLA map, stored as its east and north components in
 * the block centre's local frame. Tested against the Python decoder by web/tests/slope.check.mjs.
 */
import type { Vec3 } from "./sky";

export interface SlopeMapMeta {
  generated_utc: string; dem: string; pole: "south" | "north"; tiles_dir: string; map_scale_m: number; block_m: number;
  lines: number; samples: number; line_offset: number; sample_offset: number; radius_m: number; x_sign: number; y_sign: number;
  min_abs_lat: number; tile: number; tiles: [number, number][]; scale: number; missing: number;
  slope_share_below_deg: Record<string, number>;
  check: { points: number; worst_deg: number; limit_deg: number; pass: boolean };
  check_samples: { lat: number; lon: number; normal: Vec3 }[];
}

const DEG = Math.PI / 180;
const sign = (m: SlopeMapMeta) => (m.pole === "north" ? 1 : -1);

/** (line, sample) on the 120 m map, 0-based floats (PolarGrid.pixel). */
function pixel(m: SlopeMapMeta, lat: number, lon: number): [number, number] {
  const r = 2 * m.radius_m * Math.tan(Math.PI / 4 - (sign(m) * lat * DEG) / 2);
  const x = m.x_sign * r * Math.sin(lon * DEG), y = m.y_sign * r * Math.cos(lon * DEG);
  return [y / m.map_scale_m + m.line_offset, x / m.map_scale_m + m.sample_offset];
}

/** PolarGrid.latlon. */
function latlon(m: SlopeMapMeta, line: number, sample: number): [number, number] {
  const x = (sample - m.sample_offset) * m.map_scale_m, y = (line - m.line_offset) * m.map_scale_m;
  const lat = sign(m) * (90 - (2 * Math.atan((0.5 * Math.hypot(x, y)) / m.radius_m)) / DEG);
  return [lat, Math.atan2(m.x_sign * x, m.y_sign * y) / DEG];
}

export function slopeCovers(m: SlopeMapMeta, lat: number): boolean {
  return sign(m) * lat >= m.min_abs_lat;
}

/** The block a point falls in and the tile holding it. */
export function blockOf(m: SlopeMapMeta, lat: number, lon: number) {
  const [li, si] = pixel(m, lat, lon);
  const bi = Math.floor(li / 2), bj = Math.floor(si / 2);
  return { bi, bj, tile: [Math.floor(bi / m.tile), Math.floor(bj / m.tile)] as [number, number] };
}

export function slopeTileFor(m: SlopeMapMeta, lat: number, lon: number): [number, number] | null {
  if (!slopeCovers(m, lat)) return null;
  const { tile } = blockOf(m, lat, lon);
  return m.tiles.some(([a, b]) => a === tile[0] && b === tile[1]) ? tile : null;
}

/** Outward normal (Moon-fixed unit vector) of the block a point falls in, or null if not on the map. */
export function normalAt(m: SlopeMapMeta, tiles: Map<string, Int16Array>, lat: number, lon: number): { n: Vec3; slopeDeg: number } | null {
  if (!slopeCovers(m, lat)) return null;
  const { bi, bj, tile } = blockOf(m, lat, lon);
  const t = tiles.get(tile.join(","));
  if (!t) return null;
  const off = (((bi % m.tile) * m.tile) + (bj % m.tile)) * 2;
  if (t[off] === m.missing) return null;
  const e = t[off] / m.scale, nn = t[off + 1] / m.scale, u = Math.sqrt(Math.max(0, 1 - e * e - nn * nn));
  const [la, lo] = latlon(m, bi * 2 + 0.5, bj * 2 + 0.5);
  const p = la * DEG, l = lo * DEG;
  const up: Vec3 = [Math.cos(p) * Math.cos(l), Math.cos(p) * Math.sin(l), Math.sin(p)];
  const north: Vec3 = [-Math.sin(p) * Math.cos(l), -Math.sin(p) * Math.sin(l), Math.cos(p)];
  const east: Vec3 = [-Math.sin(l), Math.cos(l), 0];
  const n: Vec3 = [0, 1, 2].map((k) => e * east[k] + nn * north[k] + u * up[k]) as Vec3;
  return { n, slopeDeg: Math.acos(Math.min(1, u)) / DEG };
}
