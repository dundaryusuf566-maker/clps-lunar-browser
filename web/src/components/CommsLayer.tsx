/**
 * Shared pieces of the communication layers on the Anywhere page's maps: the layer switch, the
 * colour image of a layer and its legend. Lighter = more of the time (both themes), as the
 * Forecast's region map.
 */
import { useMemo } from "react";
import { isDark } from "../lib/color";
import { COMMS_LAYERS, type CommsLayer } from "../lib/commsMap";
import { fmtNum } from "../lib/format";
import { useThemeVersion } from "../lib/hooks";
import { goodFill } from "./ForecastPage";

export type LayerChoice = "none" | CommsLayer;

export function LayerSwitch({ value, onChange, noneLabel }: { value: LayerChoice; onChange: (v: LayerChoice) => void; noneLabel: string }) {
  return (
    <div className="comms-switch">
      <span className="comms-switch-label">Map shows</span>
      <div className="segmented" role="group" aria-label="Map layer">
        <button aria-pressed={value === "none"} onClick={() => onChange("none")}>{noneLabel}</button>
        {COMMS_LAYERS.map((l) => (
          <button key={l.id} aria-pressed={value === l.id} onClick={() => onChange(l.id)} title={l.label}>{l.short}</button>
        ))}
      </div>
    </div>
  );
}

/** Colour of a share (%) of the time. */
export function useCommsFill() {
  const theme = useThemeVersion();
  return useMemo(() => {
    const dark = isDark();
    return { dark, ...goodFill([0, 100], "high", dark) };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [theme]);
}

const rgb = (css: string): [number, number, number] => {
  const m = css.match(/\d+(\.\d+)?/g);
  return m ? [Number(m[0]), Number(m[1]), Number(m[2])] : [128, 128, 128];
};

/** A PNG data URL, one pixel per cell, row 0 at the top; null values transparent. */
export function cellImage(rows: number, cols: number, value: (r: number, c: number) => number | null, fill: (v: number) => string): string {
  const cv = document.createElement("canvas");
  cv.width = cols; cv.height = rows;
  const ctx = cv.getContext("2d");
  if (!ctx) return "";
  const img = ctx.createImageData(cols, rows);
  const lut = Array.from({ length: 201 }, (_, i) => rgb(fill(i / 2)));   // 0.5 % steps
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const v = value(r, c), o = (r * cols + c) * 4;
      if (v === null) continue;
      const [R, G, B] = lut[Math.max(0, Math.min(200, Math.round(v * 2)))];
      img.data[o] = R; img.data[o + 1] = G; img.data[o + 2] = B; img.data[o + 3] = 255;
    }
  }
  ctx.putImageData(img, 0, 0);
  return cv.toDataURL("image/png");
}

/** Diagonal two-tone stripes over flagged cells, `scale` pixels per cell; transparent elsewhere. */
export function hatchImage(rows: number, cols: number, flagged: (r: number, c: number) => boolean, scale = 6): string {
  const cv = document.createElement("canvas");
  cv.width = cols * scale; cv.height = rows * scale;
  const ctx = cv.getContext("2d");
  if (!ctx) return "";
  const img = ctx.createImageData(cv.width, cv.height);
  for (let r = 0; r < rows; r++) for (let c = 0; c < cols; c++) {
    if (!flagged(r, c)) continue;
    for (let y = r * scale; y < (r + 1) * scale; y++) for (let x = c * scale; x < (c + 1) * scale; x++) {
      const k = (x + y) % scale, o = (y * cv.width + x) * 4;
      if (k === 0) { img.data[o] = 20; img.data[o + 1] = 33; img.data[o + 2] = 61; img.data[o + 3] = 200; }
      else if (k === 1) { img.data[o] = 255; img.data[o + 1] = 255; img.data[o + 2] = 255; img.data[o + 3] = 220; }
    }
  }
  ctx.putImageData(img, 0, 0);
  return cv.toDataURL("image/png");
}

export function CommsLegend({ layer, fill, here, note, hatch }: { layer: CommsLayer; fill: (v: number) => string; here: React.ReactNode; note: React.ReactNode; hatch?: boolean }) {
  const stops = Array.from({ length: 11 }, (_, i) => `${fill(i * 10)} ${i * 10}%`).join(", ");
  const label = COMMS_LAYERS.find((l) => l.id === layer)!.label;
  return (
    <div className="comms-legend">
      <div className="comms-scale">
        <span>0%</span><span className="comms-bar" style={{ background: `linear-gradient(90deg, ${stops})` }} /><span>100% of the time</span>
        {hatch && <><span className="comms-hatch" aria-hidden="true" /><span>uncertain: the grid points around disagree</span></>}
      </div>
      <p className="table-note"><strong>{label}.</strong> {here ? <>{here} </> : null}{note}</p>
    </div>
  );
}

export const pct = (v: number) => `${fmtNum(v, v > 0 && v < 1 ? 1 : 0)}%`;
