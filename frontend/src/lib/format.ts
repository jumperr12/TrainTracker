const timeFmt = new Intl.DateTimeFormat("pl-PL", {
  hour: "2-digit",
  minute: "2-digit",
  timeZone: "Europe/Warsaw",
});

export function hhmm(ms: number | null | undefined): string {
  return ms == null ? "" : timeFmt.format(new Date(ms));
}

export function delayText(min: number): string {
  if (min <= 0) return "on time";
  return `+${min} min`;
}

export function ago(ms: number | null | undefined, now: number): string {
  if (ms == null) return "never";
  const s = Math.max(0, Math.round((now - ms) / 1000));
  if (s < 60) return `${s}s ago`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  return `${Math.round(m / 60)} h ago`;
}

export const STATUS_TEXT: Record<string, string> = {
  not_started: "Departing soon",
  dwelling: "At station",
  moving: "Running",
  awaiting: "Awaiting report",
  finished: "Arrived",
  cancelled: "Cancelled",
  out_of_coverage: "Outside mapped area",
  unknown: "Position unknown",
};
