// Mirrors backend/app/api/schemas.py (timestamps are epoch milliseconds).

/** Statuses of trains on the map (/api/trains). */
export type TrainStatus = "not_started" | "dwelling" | "moving" | "awaiting";
/** The detail endpoint can also describe trains that are no longer on the map. */
export type DetailStatus = TrainStatus | "finished" | "cancelled" | "out_of_coverage" | "unknown";

export interface SegmentRef {
  key: string;
  depMs: number;
  arrMs: number;
}

export interface NextStop {
  stationId: number;
  name: string;
  etaMs: number | null;
  delayMin: number;
}

export interface Disruption {
  id: number;
  type: string | null;
  message: string | null;
  fromStation: string | null;
  toStation: string | null;
  affectedTrains: number;
}

export interface Train {
  key: string;
  number: string;
  name: string | null;
  category: string | null;
  carrier: string | null;
  status: TrainStatus;
  delayMin: number;
  lat: number;
  lon: number;
  bearing: number;
  segment: SegmentRef | null;
  nextStop: NextStop | null;
  origin: string;
  destination: string;
  lastReportMs: number | null;
  /** Affected by at least one reported traffic disruption. */
  disrupted: boolean;
}

export interface TrainsResponse {
  generatedAtMs: number;
  snapshotAtMs: number | null;
  stale: boolean;
  trains: Train[];
}

export interface Stop {
  stationId: number;
  name: string;
  lat: number | null;
  lon: number | null;
  plannedArrivalMs: number | null;
  plannedDepartureMs: number | null;
  actualArrivalMs: number | null;
  actualDepartureMs: number | null;
  estArrivalMs: number | null;
  estDepartureMs: number | null;
  delayMin: number;
  platform: string | null;
  track: string | null;
  isStop: boolean;
  reported: boolean;
  passed: boolean;
}

export interface TrainDetail extends Omit<Train, "status" | "lat" | "lon"> {
  status: DetailStatus;
  lat: number | null;
  lon: number | null;
  operatingDate: string;
  trainStatus: string | null;
  stops: Stop[];
  segmentKeys: string[];
  currentSegmentIndex: number | null;
  disruptions: Disruption[];
}

export interface Station {
  id: number;
  name: string;
  lat: number;
  lon: number;
}

export interface Meta {
  mode: "live" | "mock";
  attribution: string[];
  disclaimer: string;
  carriers: string[];
  pollIntervalS: number | null;
  lastPollOkMs: number | null;
  snapshotAtMs: number | null;
  stale: boolean;
  /** Polling paused because nobody was viewing the map. */
  idle: boolean;
  lastError: string | null;
  authError: boolean;
  disruptionCount: number;
  quota: {
    hourlyLimit: number | null;
    hourlyRemaining: number | null;
    dailyLimit: number | null;
    dailyRemaining: number | null;
  };
  apiCalls: number;
  trainCount: number;
  visibleTrainCount: number;
  locatedStationCount: number;
  segmentCount: number;
}

export type LatLon = [number, number];
