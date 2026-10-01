import { useEffect } from "react";
import { MapContainer, TileLayer, ZoomControl, useMap } from "react-leaflet";
import type { LatLon, Train, TrainDetail } from "../api/types";
import { RouteOverlay } from "./RouteOverlay";
import { StationLayer } from "./StationLayer";
import { TrainLayer } from "./TrainLayer";

const POLAND_CENTER: LatLon = [52.0, 19.4];

interface Props {
  trains: Train[];
  clockOffset: number;
  selectedKey: string | null;
  detail: TrainDetail | null;
  onSelect: (key: string) => void;
  showStations: boolean;
  showRailOverlay: boolean;
  flyTo: { at: LatLon; seq: number } | null;
}

export function TrainMap(p: Props) {
  return (
    <MapContainer center={POLAND_CENTER} zoom={6} minZoom={5} maxZoom={18} zoomControl={false} className="map">
      <ZoomControl position="bottomright" />
      <TileLayer
        url="https://tile.openstreetmap.org/{z}/{x}/{y}.png"
        attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
        maxZoom={19}
      />
      {p.showRailOverlay && (
        <TileLayer
          url="https://{s}.tiles.openrailwaymap.org/standard/{z}/{x}/{y}.png"
          subdomains="abc"
          attribution='<a href="https://www.openrailwaymap.org/">OpenRailwayMap</a> (CC-BY-SA)'
          opacity={0.6}
          maxZoom={19}
        />
      )}
      <StationLayer visible={p.showStations} />
      <RouteOverlay detail={p.detail} />
      <TrainLayer trains={p.trains} clockOffset={p.clockOffset} selectedKey={p.selectedKey} onSelect={p.onSelect} />
      <FlyTo target={p.flyTo} />
    </MapContainer>
  );
}

function FlyTo({ target }: { target: { at: LatLon; seq: number } | null }) {
  const map = useMap();
  useEffect(() => {
    if (target) map.flyTo(target.at, Math.max(map.getZoom(), 10), { duration: 0.8 });
  }, [target, map]);
  return null;
}
