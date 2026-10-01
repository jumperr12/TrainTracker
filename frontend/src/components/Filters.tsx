import { useState } from "react";

export const OTHER = "other";

export interface FilterState {
  hidden: Set<string>; // categories switched off
  showStations: boolean;
  showRailOverlay: boolean;
  hideNotStarted: boolean;
}

interface Props {
  categories: { name: string; count: number }[];
  state: FilterState;
  onChange: (s: FilterState) => void;
}

const startOpen = () => !window.matchMedia("(max-width: 720px)").matches;

export function Filters({ categories, state, onChange }: Props) {
  const [initiallyOpen] = useState(startOpen); // collapsed on phones; afterwards the user decides
  const toggle = (name: string) => {
    const hidden = new Set(state.hidden);
    if (hidden.has(name)) hidden.delete(name);
    else hidden.add(name);
    onChange({ ...state, hidden });
  };

  return (
    <details className="filters" open={initiallyOpen}>
      <summary>Filters &amp; layers</summary>
      <div className="chips" role="group" aria-label="Train categories">
        {categories.map((c) => (
          <button
            key={c.name}
            className={`chip ${state.hidden.has(c.name) ? "off" : "on"}`}
            onClick={() => toggle(c.name)}
            aria-pressed={!state.hidden.has(c.name)}
          >
            {c.name} <span className="count">{c.count}</span>
          </button>
        ))}
      </div>
      <label>
        <input
          type="checkbox"
          checked={state.showStations}
          onChange={(e) => onChange({ ...state, showStations: e.target.checked })}
        />
        Stations (zoom in)
      </label>
      <label>
        <input
          type="checkbox"
          checked={state.showRailOverlay}
          onChange={(e) => onChange({ ...state, showRailOverlay: e.target.checked })}
        />
        Railway overlay
      </label>
      <label>
        <input
          type="checkbox"
          checked={state.hideNotStarted}
          onChange={(e) => onChange({ ...state, hideNotStarted: e.target.checked })}
        />
        Hide trains not yet departed
      </label>
    </details>
  );
}
