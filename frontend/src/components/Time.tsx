import { hhmm } from "../lib/format";
import { delayClass } from "../lib/icons";

interface Props {
  planned: number | null;
  /** Reported time, shown bold. */
  actual: number | null;
  /** Estimated time, shown in italics when nothing is reported. */
  est: number | null;
}

/** Planned time, struck through and followed by the reported or estimated one when the train is late. */
export function Time({ planned, actual, est }: Props) {
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
