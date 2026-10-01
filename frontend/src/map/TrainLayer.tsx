import L from "leaflet";
import { useEffect, useRef } from "react";
import { useMap } from "react-leaflet";
import type { Train } from "../api/types";
import { delayText } from "../lib/format";
import { trainDivIcon, trainIconSignature } from "../lib/icons";
import { interpolateAlong } from "../lib/interpolate";
import { getSegment } from "../lib/segments";

interface Props {
  trains: Train[];
  clockOffset: number;
  selectedKey: string | null;
  onSelect: (key: string) => void;
}

interface Entry {
  marker: L.Marker;
  train: Train;
  signature: string;
}

const TICK_MS = 1000;
const MAX_FRACTION = 0.999; // wait at the next station for the server to confirm arrival

/**
 * Markers are managed imperatively: React re-renders only when the train list changes
 * (every poll), while a 1 s timer moves markers along their track segment in between.
 */
export function TrainLayer({ trains, clockOffset, selectedKey, onSelect }: Props) {
  const map = useMap();
  const group = useRef<L.LayerGroup | null>(null);
  const entries = useRef(new Map<string, Entry>());
  const offset = useRef(clockOffset);
  const onSelectRef = useRef(onSelect);
  offset.current = clockOffset;
  onSelectRef.current = onSelect;

  useEffect(() => {
    const g = L.layerGroup().addTo(map);
    group.current = g;
    const tracked = entries.current;
    const timer = window.setInterval(() => {
      for (const e of tracked.values()) place(e, offset.current);
    }, TICK_MS);
    return () => {
      window.clearInterval(timer);
      g.remove();
      tracked.clear();
    };
  }, [map]);

  useEffect(() => {
    const g = group.current;
    if (!g) return;
    const seen = new Set<string>();
    for (const t of trains) {
      seen.add(t.key);
      const selected = t.key === selectedKey;
      const signature = trainIconSignature(t, selected);
      let e = entries.current.get(t.key);
      if (!e) {
        const marker = L.marker([t.lat, t.lon], {
          icon: trainDivIcon(t, selected),
          keyboard: false,
          riseOnHover: true,
        });
        marker.on("click", () => onSelectRef.current(t.key));
        marker.bindTooltip("", { direction: "top", offset: [0, -18], opacity: 0.95 });
        g.addLayer(marker);
        e = { marker, train: t, signature };
        entries.current.set(t.key, e);
      } else if (e.signature !== signature) {
        e.marker.setIcon(trainDivIcon(t, selected));
        e.signature = signature;
      }
      e.train = t;
      e.marker.setZIndexOffset(selected ? 1000 : 0);
      e.marker.setTooltipContent(tooltip(t));
      place(e, offset.current);
    }
    for (const [key, e] of entries.current) {
      if (!seen.has(key)) {
        g.removeLayer(e.marker);
        entries.current.delete(key);
      }
    }
  }, [trains, selectedKey]);

  return null;
}

function tooltip(t: Train): string {
  const name = t.name ? ` ${t.name}` : "";
  const esc = (s: string) => s.replace(/[&<>]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" })[c]!);
  return `<b>${esc(t.number)}${esc(name)}</b><br>${esc(t.origin)} → ${esc(t.destination)}<br>${delayText(t.delayMin)}`;
}

function place(e: Entry, clockOffset: number): void {
  const t = e.train;
  let lat = t.lat;
  let lon = t.lon;
  let bearing = t.bearing;
  if (t.status === "moving" && t.segment) {
    const seg = getSegment(t.segment.key);
    if (seg) {
      const now = Date.now() + clockOffset;
      const span = t.segment.arrMs - t.segment.depMs;
      const f = span > 0 ? Math.min(Math.max((now - t.segment.depMs) / span, 0), MAX_FRACTION) : MAX_FRACTION;
      ({ lat, lon, bearing } = interpolateAlong(seg.path, seg.cum, f * seg.length));
    }
  }
  e.marker.setLatLng([lat, lon]);
  const img = e.marker.getElement()?.querySelector<HTMLElement>(".train-icon");
  if (img) img.style.transform = `rotate(${bearing}deg)`;
}
