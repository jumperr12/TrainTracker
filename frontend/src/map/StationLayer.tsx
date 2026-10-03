import { useEffect, useMemo, useState } from "react";
import { Marker, Tooltip, useMapEvents } from "react-leaflet";
import { api } from "../api/client";
import type { Station } from "../api/types";
import { stationDivIcon } from "../lib/icons";

const MIN_ZOOM = 8;
const REFRESH_MS = 10 * 60_000;

/** Stations served by the tracked trains, shown once zoomed in enough to not clutter the map. */
export function StationLayer({ visible, onSelect }: { visible: boolean; onSelect: (s: Station) => void }) {
  const [stations, setStations] = useState<Station[]>([]);
  const [zoom, setZoom] = useState<number | null>(null);
  const map = useMapEvents({ zoomend: () => setZoom(map.getZoom()) });
  const icon = useMemo(() => stationDivIcon(), []);

  useEffect(() => {
    let alive = true;
    const load = () =>
      api
        .stations()
        .then((s) => alive && setStations(s))
        .catch(() => undefined);
    load();
    const id = window.setInterval(load, REFRESH_MS);
    return () => {
      alive = false;
      window.clearInterval(id);
    };
  }, []);

  if (!visible || (zoom ?? map.getZoom()) < MIN_ZOOM) return null;
  return (
    <>
      {stations.map((s) => (
        <Marker
          key={s.id}
          position={[s.lat, s.lon]}
          icon={icon}
          keyboard={false}
          eventHandlers={{ click: () => onSelect(s) }}
        >
          <Tooltip direction="right" offset={[8, 0]}>
            {s.name}
          </Tooltip>
        </Marker>
      ))}
    </>
  );
}
