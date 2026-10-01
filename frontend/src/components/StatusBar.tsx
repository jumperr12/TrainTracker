import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Disruption, Meta } from "../api/types";
import { ago } from "../lib/format";

interface Props {
  meta: Meta | null;
  trainsError: string | null;
  visibleCount: number;
  snapshotAtMs: number | null;
  stale: boolean;
  now: number;
}

export function StatusBar({ meta, trainsError, visibleCount, snapshotAtMs, stale, now }: Props) {
  const [showDisruptions, setShowDisruptions] = useState(false);
  const [disruptions, setDisruptions] = useState<Disruption[]>([]);
  const count = meta?.disruptionCount ?? 0;

  useEffect(() => {
    if (showDisruptions) api.disruptions().then(setDisruptions).catch(() => setDisruptions([]));
  }, [showDisruptions, count]);

  let problem: string | null = null;
  if (trainsError) problem = `Backend unreachable (${trainsError})`;
  else if (meta?.authError) problem = "PLK API key missing or rejected — set PLK_API_KEY in backend/.env (or MOCK_MODE=1)";
  else if (stale) problem = `Data is stale${meta?.lastError ? `: ${meta.lastError}` : ""}`;

  return (
    <footer className="status-bar">
      {showDisruptions && count > 0 && (
        <div className="disruption-list">
          <button className="close" onClick={() => setShowDisruptions(false)} aria-label="Close">×</button>
          <h3>Traffic disruptions</h3>
          {disruptions.map((d) => (
            <div key={d.id} className="disruption">
              <b>{d.type ?? "Disruption"}</b>
              {d.fromStation && (
                <span className="muted small">
                  {" "}
                  {d.fromStation}
                  {d.toStation && d.toStation !== d.fromStation ? ` – ${d.toStation}` : ""} · {d.affectedTrains} trains
                </span>
              )}
              {d.message && <div className="small">{d.message}</div>}
            </div>
          ))}
        </div>
      )}
      {problem && <div className="banner">{problem}</div>}
      <div className="status-line">
        {meta?.mode === "mock" && <span className="badge mock">MOCK DATA</span>}
        <span>
          {visibleCount} trains · updated {ago(snapshotAtMs, now)}
        </span>
        {count > 0 && (
          <button className="badge delay-minor disruption-toggle" onClick={() => setShowDisruptions((v) => !v)}>
            ⚠ {count} disruption{count === 1 ? "" : "s"}
          </button>
        )}
        <span className="spacer" />
        <span className="attribution">
          {(meta?.attribution ?? ["Źródło danych: PKP Polskie Linie Kolejowe S.A."]).join(" · ")}
        </span>
        <span className="muted" title={meta?.disclaimer}>
          Positions are estimates
        </span>
      </div>
    </footer>
  );
}
