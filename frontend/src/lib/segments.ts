// Client-side cache of routed track polylines ("fromId-toId" -> path), fetched lazily in batches.

import { useSyncExternalStore } from "react";
import { api } from "../api/client";
import type { LatLon } from "../api/types";
import { cumulative } from "./interpolate";

export interface Segment {
  path: LatLon[];
  cum: number[];
  length: number;
}

const cache = new Map<string, Segment>();
const pending = new Set<string>();
const failed = new Map<string, number>(); // key -> time of failure, retried after a while
const listeners = new Set<() => void>();
let version = 0;

const BATCH = 100;
const RETRY_MS = 60_000;

export function getSegment(key: string): Segment | undefined {
  return cache.get(key);
}

export async function ensureSegments(keys: Iterable<string>): Promise<void> {
  const now = Date.now();
  const missing = [...new Set(keys)].filter(
    (k) => !cache.has(k) && !pending.has(k) && now - (failed.get(k) ?? 0) > RETRY_MS,
  );
  if (missing.length === 0) return;
  missing.forEach((k) => pending.add(k));
  for (let i = 0; i < missing.length; i += BATCH) {
    const batch = missing.slice(i, i + BATCH);
    try {
      const data = await api.segments(batch);
      for (const key of batch) {
        const path = data[key];
        if (path && path.length >= 2) {
          const cum = cumulative(path);
          cache.set(key, { path, cum, length: cum[cum.length - 1] });
        } else {
          failed.set(key, Date.now());
        }
      }
    } catch {
      batch.forEach((k) => failed.set(k, Date.now()));
    } finally {
      batch.forEach((k) => pending.delete(k));
    }
  }
  version++;
  listeners.forEach((fn) => fn());
}

function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

/** Re-renders the caller whenever new segments arrive. */
export function useSegmentsVersion(): number {
  return useSyncExternalStore(subscribe, () => version);
}
