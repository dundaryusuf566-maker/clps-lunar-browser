import { rampGradient } from "../lib/color";
import { fmtNum } from "../lib/format";

interface Props {
  domain: [number, number];
  label: string;
  digits: number;
  dark: boolean;
  note?: string;
  format?: (v: number) => string;
}

export function Legend({ domain, label, digits, dark, note, format }: Props) {
  const f = format ?? ((v: number) => fmtNum(v, digits));
  return (
    <div className="legend">
      <span className="label">{label}</span>
      <span className="num">{f(domain[0])}</span>
      <span className="bar" style={{ background: rampGradient(dark) }} aria-hidden="true" />
      <span className="num">{f(domain[1])}</span>
      {note && <span>{note}</span>}
    </div>
  );
}
