import { useState } from "react";
import type { Stop, TrainDetail } from "../api/types";
import { STATUS_TEXT, ago, delayText, hhmm } from "../lib/format";
import { delayClass, trainIconUrl } from "../lib/icons";

interface Props {
  detail: TrainDetail | null;
  error: string | null;
  now: number;
  onClose: () => void;
}

export function TrainPanel({ detail, error, now, onClose }: Props) {
  const [showPassing, setShowPassing] = useState(false);

  if (!detail) {
    return (
      <aside className="panel train-panel">
        <button className="close" onClick={onClose} aria-label="Close">×</button>
        <p className="muted">{error ? `Could not load train: ${error}` : "Loading…"}</p>
      </aside>
    );
  }

  const stops = showPassing ? detail.stops : detail.stops.filter((s) => s.isStop);
  const passingCount = detail.stops.length - detail.stops.filter((s) => s.isStop).length;

  return (
    <aside className="panel train-panel">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <header className="train-head">
        <img className="train-head-icon" src={trainIconUrl(detail.category)} width={32} height={32} alt="" />
        <div>
          <h2>
            {detail.number} {detail.name && <span className="train-name">{detail.name}</span>}
          </h2>
          <div className="muted">
            {detail.origin} → {detail.destination}
          </div>
        </div>
      </header>

      <div className="train-status">
        <span className={`badge ${delayClass(detail.delayMin)}`}>{delayText(detail.delayMin)}</span>
        <span>{STATUS_TEXT[detail.status] ?? detail.status}</span>
        {detail.nextStop && (
          <span className="muted">
            next: <b>{detail.nextStop.name}</b> {hhmm(detail.nextStop.etaMs)}
          </span>
        )}
      </div>
      <div className="muted small">
        Last report {ago(detail.lastReportMs, now)} · running date {detail.operatingDate}
      </div>

      {detail.disruptions.map((d) => (
        <div key={d.id} className="disruption" role="note">
          <b>⚠ {d.type ?? "Traffic disruption"}</b>
          {d.fromStation && (
            <span className="muted small">
              {" "}
              {d.fromStation}
              {d.toStation && d.toStation !== d.fromStation ? ` – ${d.toStation}` : ""}
            </span>
          )}
          {d.message && <div className="small">{d.message}</div>}
        </div>
      ))}

      <table className="stops">
        <thead>
          <tr>
            <th />
            <th>Station</th>
            <th>Arr</th>
            <th>Dep</th>
            <th title="Platform / track">Pl.</th>
          </tr>
        </thead>
        <tbody>
          {stops.map((s, i) => (
            <tr key={`${s.stationId}-${i}`} className={rowClass(s)}>
              <td className="dot">{s.passed ? "●" : "○"}</td>
              <td>
                {s.name}
                {!s.isStop && <span className="muted small"> (passing)</span>}
                {s.lat == null && <span className="muted small" title="No coordinates for this point"> *</span>}
              </td>
              <td>
                <Time planned={s.plannedArrivalMs} actual={s.actualArrivalMs} est={s.estArrivalMs} />
              </td>
              <td>
                <Time planned={s.plannedDepartureMs} actual={s.actualDepartureMs} est={s.estDepartureMs} />
              </td>
              <td className="muted">{[s.platform, s.track].filter(Boolean).join("/")}</td>
            </tr>
          ))}
        </tbody>
      </table>

      {passingCount > 0 && (
        <label className="small toggle">
          <input type="checkbox" checked={showPassing} onChange={(e) => setShowPassing(e.target.checked)} />
          show {passingCount} passing points
        </label>
      )}
      <p className="muted small">
        Times: planned, then <b>reported</b> or <i>estimated</i>. Positions between reports are estimates.
      </p>
    </aside>
  );
}

function rowClass(s: Stop): string {
  return [s.passed ? "passed" : "", s.isStop ? "" : "passing"].join(" ").trim();
}

function Time({ planned, actual, est }: { planned: number | null; actual: number | null; est: number | null }) {
  if (planned == null) return null;
  const shown = actual ?? est;
  const late = shown != null ? Math.round((shown - planned) / 60_000) : 0;
  return (
    <span className="time">
      <span className={late > 0 ? "planned struck" : "planned"}>{hhmm(planned)}</span>
      {late > 0 && shown != null && (
        <span className={`${actual != null ? "reported" : "estimated"} ${delayClass(late)}`}> {hhmm(shown)}</span>
      )}
    </span>
  );
}
