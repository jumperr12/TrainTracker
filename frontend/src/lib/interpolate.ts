// TS port of backend/app/geo/polyline.py (haversine, cumulative, interpolate_along, bearing).
// Both are checked against backend/tests/fixtures/interp_cases.json.

import type { LatLon } from "../api/types";

const EARTH_RADIUS_M = 6_371_008.8;
const rad = (d: number) => (d * Math.PI) / 180;
const deg = (r: number) => (r * 180) / Math.PI;

export function haversineM(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const dp = p2 - p1;
  const dl = rad(lon2 - lon1);
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.min(1, Math.sqrt(a)));
}

export function bearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const p1 = rad(lat1);
  const p2 = rad(lat2);
  const dl = rad(lon2 - lon1);
  const x = Math.sin(dl) * Math.cos(p2);
  const y = Math.cos(p1) * Math.sin(p2) - Math.sin(p1) * Math.cos(p2) * Math.cos(dl);
  return (deg(Math.atan2(x, y)) + 360) % 360;
}

export function cumulative(path: LatLon[]): number[] {
  const out = [0];
  for (let i = 1; i < path.length; i++) {
    out.push(out[i - 1] + haversineM(path[i - 1][0], path[i - 1][1], path[i][0], path[i][1]));
  }
  return out;
}

/** Point `dist` metres along `path` (clamped) and the local bearing. */
export function interpolateAlong(path: LatLon[], cum: number[], dist: number): { lat: number; lon: number; bearing: number } {
  if (path.length === 0) throw new Error("empty path");
  if (path.length === 1) return { lat: path[0][0], lon: path[0][1], bearing: 0 };
  const total = cum[cum.length - 1];
  const d = Math.max(0, Math.min(dist, total));
  // Last index i with cum[i] <= d (same as Python's bisect_right - 1).
  let lo = 0;
  let hi = cum.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] <= d) lo = mid + 1;
    else hi = mid;
  }
  let i = Math.min(Math.max(lo - 1, 0), path.length - 2);
  while (i < path.length - 2 && cum[i + 1] - cum[i] <= 0) i++;
  const seg = cum[i + 1] - cum[i];
  const t = seg <= 0 ? 0 : (d - cum[i]) / seg;
  const [aLat, aLon] = path[i];
  const [bLat, bLon] = path[i + 1];
  return {
    lat: aLat + (bLat - aLat) * t,
    lon: aLon + (bLon - aLon) * t,
    bearing: bearingDeg(aLat, aLon, bLat, bLon),
  };
}
