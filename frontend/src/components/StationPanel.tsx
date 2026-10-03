import type { BoardEntry, StationBoard } from "../api/types";
import { delayText } from "../lib/format";
import { delayClass } from "../lib/icons";
import { Time } from "./Time";

interface Props {
  name: string;
  board: StationBoard | null;
  error: string | null;
  onPickTrain: (key: string) => void;
  onClose: () => void;
}

/** Timetable of one station: trains still to come and those that left a moment ago. */
export function StationPanel({ name, board, error, onPickTrain, onClose }: Props) {
  return (
    <aside className="panel train-panel">
      <button className="close" onClick={onClose} aria-label="Close">×</button>
      <header className="train-head">
        <h2>{board?.name ?? name}</h2>
      </header>

      {!board && <p className="muted">{error ? `Could not load timetable: ${error}` : "Loading…"}</p>}
      {board && board.entries.length === 0 && <p className="muted">No upcoming trains at this station.</p>}
      {board && board.entries.length > 0 && (
        <table className="stops board">
          <thead>
            <tr>
              <th>Arr</th>
              <th>Dep</th>
              <th>Train</th>
              <th />
              <th title="Platform / track">Pl.</th>
            </tr>
          </thead>
          <tbody>
            {board.entries.map((e, i) => (
              <tr key={`${e.key}-${i}`} onClick={() => onPickTrain(e.key)}>
                <td>
                  <Time planned={e.plannedArrivalMs} actual={reported(e, e.estArrivalMs)} est={e.estArrivalMs} />
                </td>
                <td>
                  <Time planned={e.plannedDepartureMs} actual={reported(e, e.estDepartureMs)} est={e.estDepartureMs} />
                </td>
                <td>
                  <button className="link">
                    <b>{e.number}</b>
                  </button>{" "}
                  {e.name}
                  <div className="muted small">
                    {e.origin} → {e.destination}
                  </div>
                </td>
                <td>
                  <span className={`badge small ${delayClass(e.delayMin)}`}>{delayText(e.delayMin)}</span>
                </td>
                <td className="muted">{[e.platform, e.track].filter(Boolean).join("/")}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="muted small">
        Times: planned, then <b>reported</b> or <i>estimated</i>. Click a train to follow it.
      </p>
    </aside>
  );
}

/** The board carries one time per event; it counts as reported once the train has reported at this stop. */
function reported(e: BoardEntry, ms: number | null): number | null {
  return e.reported ? ms : null;
}
