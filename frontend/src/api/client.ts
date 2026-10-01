import type { LatLon, Meta, Station, TrainDetail, TrainsResponse } from "./types";

// Empty = same origin (the Vite dev server proxies /api to the backend).
const BASE = import.meta.env.VITE_API_BASE ?? "";

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const res = await fetch(BASE + path, { signal });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText} (${path})`);
  return (await res.json()) as T;
}

export const api = {
  trains: (signal?: AbortSignal) => getJson<TrainsResponse>("/api/trains", signal),
  train: (key: string, signal?: AbortSignal) =>
    getJson<TrainDetail>(`/api/trains/${encodeURIComponent(key)}`, signal),
  segments: (keys: string[]) =>
    getJson<Record<string, LatLon[]>>(`/api/segments?keys=${encodeURIComponent(keys.join(","))}`),
  stations: () => getJson<Station[]>("/api/stations"),
  meta: () => getJson<Meta>("/api/meta"),
};
