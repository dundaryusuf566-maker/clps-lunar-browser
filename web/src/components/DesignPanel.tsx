import { useRef, useState } from "react";
import { designTransfer, type Health } from "../lib/api";
import { familyName, fmtDay, fmtNum, fmtTof, parseUtc } from "../lib/format";
import type { DesignResult, TransferRow } from "../types";

interface Props {
  health: Health | null;
  seed: TransferRow | null;          // pre-fill the form from the selected transfer
  custom: TransferRow[];
  selectedId: string | null;
  onDesigned: (r: DesignResult) => void;
  onSelect: (id: string) => void;
}

const toLocalInput = (iso: string) => iso.slice(0, 16);
const ephName = (e: string) => (e.includes("spice") ? "JPL DE440" : "the analytic ephemeris");

export function DesignPanel({ health, seed, custom, selectedId, onDesigned, onSelect }: Props) {
  const fromRow = (r: TransferRow | null) => ({
    tli: r ? toLocalInput(r.tli_utc) : "2026-01-10T00:00",
    tof: r ? String(r.tof_days) : "5",
    family: r ? String(r.family) : "1",
    inc: r ? String(r.lunar_inc_deg) : "90",
    alt: r ? String(r.target_alt_km) : "100",
  });
  const [form, setForm] = useState(() => fromRow(seed));
  const [busy, setBusy] = useState<number | null>(null);
  const [message, setMessage] = useState<{ kind: "error" | "info"; text: string } | null>(null);
  const abort = useRef<AbortController | null>(null);

  if (!health) {
    return (
      <section className="panel design-panel offline">
        <div className="panel-body">
          <p>
            <strong>Live design is off.</strong> Start the engine with <code>python -m api.server</code> to design a
            transfer for any date, approach and capture orbit, and to see the path of every transfer in the database.
          </p>
        </div>
      </section>
    );
  }

  const set = (k: keyof typeof form) => (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) =>
    setForm({ ...form, [k]: e.target.value });

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setMessage(null);
    setBusy(0);
    abort.current = new AbortController();
    try {
      const res = await designTransfer(
        { tli_utc: `${form.tli}:00Z`, tof_days: Number(form.tof), family: Number(form.family),
          lunar_inc_deg: Number(form.inc), periselene_alt_km: Number(form.alt) },
        (t) => setBusy(t), abort.current.signal);
      if (!res.converged || !res.row) {
        setMessage({ kind: "error", text: res.message ?? "The targeting did not converge." });
      } else {
        onDesigned(res);
        setMessage({ kind: "info", text: `Designed in ${fmtNum(res.solve_seconds, 1)} s with ${ephName(res.ephemeris)}.` });
      }
    } catch (err) {
      setMessage({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(null);
      abort.current = null;
    }
  }

  return (
    <section className="panel design-panel" aria-labelledby="design-title">
      <div className="panel-head">
        <h2 id="design-title">Design a transfer</h2>
        <span className="hint">Engine online, {ephName(health.ephemeris)}</span>
      </div>
      <form className="panel-body design-form" onSubmit={submit}>
        <label>TLI date and time (UTC)
          <input type="datetime-local" required value={form.tli} onChange={set("tli")} min="1950-01-01T00:00" max="2149-12-31T23:59" />
        </label>
        <label>Transit time (days)
          <input type="number" required min={3} max={14} step={0.25} value={form.tof} onChange={set("tof")} />
        </label>
        <label>Approach
          <select value={form.family} onChange={set("family")}>
            <option value="1">{familyName(1)}</option>
            <option value="-1">{familyName(-1)}</option>
          </select>
        </label>
        <label>Capture inclination (°)
          <input type="number" required min={0} max={180} step={1} value={form.inc} onChange={set("inc")} />
        </label>
        <label>Periselene altitude (km)
          <input type="number" required min={15} max={5000} step={5} value={form.alt} onChange={set("alt")} />
        </label>
        <div className="design-actions">
          {busy === null
            ? <button type="submit" className="primary">Design transfer</button>
            : <button type="button" onClick={() => abort.current?.abort()}>Cancel</button>}
          {busy === null && seed && (
            <button type="button" onClick={() => setForm(fromRow(seed))}>Copy selected transfer</button>
          )}
          <span className="status" role="status" aria-live="polite">
            {busy !== null ? `Designing… ${fmtNum(busy, 0)} s` : message?.text ?? "Takes a few seconds per transfer."}
          </span>
        </div>
        {message?.kind === "error" && <p className="error-text">{message.text}</p>}
      </form>
      {custom.length === 0 && (
        <div className="panel-body custom-list empty-list">
          <p>
            Transfers you design appear here and open in the detail panel, with a landing analysis for every site.
            Copy the selected transfer into the form to explore around it.
          </p>
        </div>
      )}
      {custom.length > 0 && (
        <div className="panel-body custom-list">
          <h3>Your transfers</h3>
          <ul>
            {custom.map((r) => (
              <li key={r.id}>
                <button aria-pressed={r.id === selectedId} onClick={() => onSelect(r.id)}>
                  {fmtDay(parseUtc(r.tli_utc))}, {fmtTof(r.tof_days)}, {familyName(r.family).toLowerCase()}, {fmtNum(r.lunar_inc_deg, 0)}°
                  <span className="num">, LOI {fmtNum(r.loi_dv_ms, 1)} m/s</span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}
