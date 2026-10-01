import { CircleMarker, Polyline, Tooltip } from "react-leaflet";
import type { LatLon, Stop, TrainDetail } from "../api/types";
import { hhmm } from "../lib/format";
import { getSegment, useSegmentsVersion } from "../lib/segments";

/** Full route of the selected train along the track: travelled part grey, remaining part blue. */
export function RouteOverlay({ detail }: { detail: TrainDetail | null }) {
  useSegmentsVersion(); // redraw as segments arrive
  if (!detail) return null;

  const located = detail.stops.filter((s): s is Stop & { lat: number; lon: number } => s.lat != null && s.lon != null);
  const passed: LatLon[][] = [];
  const ahead: LatLon[][] = [];
  for (let i = 0; i + 1 < located.length; i++) {
    const a = located[i];
    const b = located[i + 1];
    if (a.stationId === b.stationId) continue;
    const seg = getSegment(`${a.stationId}-${b.stationId}`);
    const path: LatLon[] = seg ? seg.path : [[a.lat, a.lon], [b.lat, b.lon]];
    (b.passed ? passed : ahead).push(path);
  }

  return (
    <>
      <Polyline positions={passed} pathOptions={{ color: "#8a8f98", weight: 4, opacity: 0.8, dashArray: "6 6" }} />
      <Polyline positions={ahead} pathOptions={{ color: "#1f6feb", weight: 5, opacity: 0.85 }} />
      {located
        .filter((s) => s.isStop)
        .map((s, i) => (
          <CircleMarker
            key={`${s.stationId}-${i}`}
            center={[s.lat, s.lon]}
            radius={5}
            pathOptions={{
              color: s.passed ? "#8a8f98" : "#1f6feb",
              weight: 2,
              fillColor: "#ffffff",
              fillOpacity: 1,
            }}
          >
            <Tooltip direction="top" offset={[0, -4]}>
              <b>{s.name}</b>
              <br />
              {stopTimes(s)}
            </Tooltip>
          </CircleMarker>
        ))}
    </>
  );
}

function stopTimes(s: Stop): string {
  const arr = s.plannedArrivalMs ? `arr ${hhmm(s.plannedArrivalMs)}` : "";
  const dep = s.plannedDepartureMs ? `dep ${hhmm(s.plannedDepartureMs)}` : "";
  const delay = s.delayMin > 0 ? ` (+${s.delayMin})` : "";
  return [arr, dep].filter(Boolean).join(" · ") + delay;
}
