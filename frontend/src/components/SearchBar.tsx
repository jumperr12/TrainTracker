import { useMemo, useState } from "react";
import type { Train } from "../api/types";
import { delayText } from "../lib/format";
import { delayClass } from "../lib/icons";

const MAX_RESULTS = 8;

export function SearchBar({ trains, onPick }: { trains: Train[]; onPick: (t: Train) => void }) {
  const [q, setQ] = useState("");
  const results = useMemo(() => {
    const needle = q.trim().toLowerCase();
    if (!needle) return [];
    return trains
      .filter((t) =>
        [t.number, t.name ?? "", t.origin, t.destination, t.nextStop?.name ?? ""].some((f) =>
          f.toLowerCase().includes(needle),
        ),
      )
      .slice(0, MAX_RESULTS);
  }, [q, trains]);

  return (
    <div className="search">
      <input
        type="search"
        placeholder="Train number, name or station…"
        value={q}
        onChange={(e) => setQ(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && results[0]) {
            onPick(results[0]);
            setQ("");
          }
        }}
        aria-label="Search trains"
      />
      {results.length > 0 && (
        <ul className="results">
          {results.map((t) => (
            <li key={t.key}>
              <button
                onClick={() => {
                  onPick(t);
                  setQ("");
                }}
              >
                <b>{t.number}</b> {t.name}
                <span className="muted small">
                  {" "}
                  {t.origin} → {t.destination}
                </span>
                <span className={`badge small ${delayClass(t.delayMin)}`}>{delayText(t.delayMin)}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
