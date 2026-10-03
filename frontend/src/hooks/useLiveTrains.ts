import { useEffect, useRef, useState } from "react";
import { api } from "../api/client";
import type { Meta, StationBoard, TrainDetail, TrainsResponse } from "../api/types";
import { ensureSegments } from "../lib/segments";

const TRAINS_POLL_MS = 15_000;
const DETAIL_POLL_MS = 15_000;
const META_POLL_MS = 30_000;
const BOARD_POLL_MS = 30_000;

/** Polls fn every `ms` while `enabled`; keeps the last good value and the last error. */
function usePolling<T>(fn: (signal: AbortSignal) => Promise<T>, ms: number, deps: unknown[], enabled = true) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const fnRef = useRef(fn);
  fnRef.current = fn;

  useEffect(() => {
    if (!enabled) {
      setData(null);
      return;
    }
    let timer: number | undefined;
    const ctrl = new AbortController();
    const run = async () => {
      try {
        setData(await fnRef.current(ctrl.signal));
        setError(null);
      } catch (e) {
        if (!ctrl.signal.aborted) setError(e instanceof Error ? e.message : String(e));
      }
      if (!ctrl.signal.aborted) timer = window.setTimeout(run, ms);
    };
    run();
    return () => {
      ctrl.abort();
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, enabled, ms]);

  return { data, error };
}

export interface LiveTrains {
  data: TrainsResponse | null;
  error: string | null;
  /** serverNow - clientNow in ms; add to Date.now() when animating against server timestamps. */
  clockOffset: number;
}

export function useLiveTrains(): LiveTrains {
  const [clockOffset, setClockOffset] = useState(0);
  const { data, error } = usePolling(
    async (signal) => {
      const t0 = Date.now();
      const res = await api.trains(signal);
      const t1 = Date.now();
      setClockOffset(res.generatedAtMs - (t0 + t1) / 2);
      ensureSegments(res.trains.flatMap((t) => (t.segment ? [t.segment.key] : [])));
      return res;
    },
    TRAINS_POLL_MS,
    [],
  );
  return { data, error, clockOffset };
}

export function useTrainDetail(key: string | null) {
  return usePolling(
    async (signal) => {
      const detail = await api.train(key!, signal);
      ensureSegments(detail.segmentKeys);
      return detail;
    },
    DETAIL_POLL_MS,
    [key],
    key !== null,
  ) as { data: TrainDetail | null; error: string | null };
}

export function useStationBoard(id: number | null) {
  return usePolling((signal) => api.stationBoard(id!, signal), BOARD_POLL_MS, [id], id !== null) as {
    data: StationBoard | null;
    error: string | null;
  };
}

export function useMeta() {
  return usePolling(() => api.meta(), META_POLL_MS, []) as { data: Meta | null; error: string | null };
}
