// Icon manifest. The files in public/icons/ are transparent placeholders for now
// (backend/scripts/make_placeholder_icons.py). Replace them with real artwork of the same
// name and size; train icons must point up (north) because markers are rotated by bearing.

import L from "leaflet";
import type { Train } from "../api/types";

/** Draws a coloured dot + category label under each icon. Set to false once real icons are in place. */
export const SHOW_FALLBACK_LABEL = true;

export const TRAIN_ICON_SIZE = 48;
export const STATION_ICON_SIZE = 16;

const TRAIN_ICONS: Record<string, string> = {
  EIP: "/icons/train-eip.png",
  EIC: "/icons/train-eic.png",
  IC: "/icons/train-ic.png",
  TLK: "/icons/train-tlk.png",
  EC: "/icons/train-ec.png",
  EN: "/icons/train-en.png",
};
export const DEFAULT_TRAIN_ICON = "/icons/train-default.png";
export const STATION_ICON = "/icons/station.png";

export const KNOWN_CATEGORIES = Object.keys(TRAIN_ICONS);

export function trainIconUrl(category: string | null): string {
  return (category && TRAIN_ICONS[category.toUpperCase()]) || DEFAULT_TRAIN_ICON;
}

export type DelayClass = "delay-ok" | "delay-minor" | "delay-major";

export function delayClass(delayMin: number): DelayClass {
  if (delayMin <= 5) return "delay-ok";
  if (delayMin <= 20) return "delay-minor";
  return "delay-major";
}

const escapeHtml = (s: string) =>
  s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]!);

/** Parts of a train marker that require a new DivIcon when they change (position/rotation don't). */
export function trainIconSignature(t: Train, selected: boolean): string {
  return [t.category, delayClass(t.delayMin), t.status, selected].join("|");
}

export function trainDivIcon(t: Train, selected: boolean): L.DivIcon {
  const classes = ["train-marker", delayClass(t.delayMin), `status-${t.status}`, selected ? "selected" : ""];
  const label = SHOW_FALLBACK_LABEL ? `<span class="train-label">${escapeHtml(t.category ?? "?")}</span>` : "";
  const dot = SHOW_FALLBACK_LABEL ? `<span class="train-dot"></span>` : "";
  return L.divIcon({
    className: "",
    iconSize: [TRAIN_ICON_SIZE, TRAIN_ICON_SIZE],
    iconAnchor: [TRAIN_ICON_SIZE / 2, TRAIN_ICON_SIZE / 2],
    html:
      `<div class="${classes.join(" ")}">` +
      `<span class="train-ring"></span>${dot}` +
      `<img class="train-icon" src="${trainIconUrl(t.category)}" width="${TRAIN_ICON_SIZE}" height="${TRAIN_ICON_SIZE}" alt="" draggable="false" />` +
      `${label}</div>`,
  });
}

export function stationDivIcon(): L.DivIcon {
  const dot = SHOW_FALLBACK_LABEL ? `<span class="station-dot"></span>` : "";
  return L.divIcon({
    className: "",
    iconSize: [STATION_ICON_SIZE, STATION_ICON_SIZE],
    iconAnchor: [STATION_ICON_SIZE / 2, STATION_ICON_SIZE / 2],
    html:
      `<div class="station-marker">${dot}` +
      `<img src="${STATION_ICON}" width="${STATION_ICON_SIZE}" height="${STATION_ICON_SIZE}" alt="" draggable="false" /></div>`,
  });
}
