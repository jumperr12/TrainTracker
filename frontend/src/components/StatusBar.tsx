import type { Meta } from "../api/types";
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
  let problem: string | null = null;
  if (trainsError) problem = `Backend unreachable (${trainsError})`;
  else if (meta?.authError) problem = "PLK API key missing or rejected — set PLK_API_KEY in backend/.env (or MOCK_MODE=1)";
  else if (stale) problem = `Data is stale${meta?.lastError ? `: ${meta.lastError}` : ""}`;

  return (
    <footer className="status-bar">
      {problem && <div className="banner">{problem}</div>}
      <div className="status-line">
        {meta?.mode === "mock" && <span className="badge mock">MOCK DATA</span>}
        <span>
          {visibleCount} trains · updated {ago(snapshotAtMs, now)}
        </span>
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
