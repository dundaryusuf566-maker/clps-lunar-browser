import { utcFormat } from "d3-time-format";

const dayFmt = utcFormat("%-d %b %Y");
const dayTimeFmt = utcFormat("%-d %b %Y, %H:%M UTC");
const shortDayFmt = utcFormat("%-d %b");

export const parseUtc = (iso: string) => new Date(iso);
export const fmtDay = (d: Date) => dayFmt(d);
export const fmtDayTime = (d: Date) => dayTimeFmt(d);
export const fmtShortDay = (d: Date) => shortDayFmt(d);

export function fmtNum(v: number, digits = 1): string {
  return v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

export function fmtDuration(seconds: number): string {
  const days = seconds / 86400;
  if (days >= 1) return `${fmtNum(days, 2)} d`;
  return `${fmtNum(seconds / 3600, 1)} h`;
}

export const fmtTof = (d: number) => `${Number.isInteger(d) ? d : fmtNum(d, 1)} d`;

// B-plane family +1 puts the B vector on the lunar-south side of the Moon
// (B·pole = -|sinθ| cos δ < 0), so the spacecraft swings past the south first.
export const familyName = (f: number) => (f > 0 ? "South pass" : "North pass");
