import { useCallback, useEffect, useMemo, useState } from "react";
import type { LatLon, Train } from "./api/types";
import { Filters, OTHER, type FilterState } from "./components/Filters";
import { SearchBar } from "./components/SearchBar";
import { StatusBar } from "./components/StatusBar";
import { TrainPanel } from "./components/TrainPanel";
import { useLiveTrains, useMeta, useTrainDetail } from "./hooks/useLiveTrains";
import { KNOWN_CATEGORIES } from "./lib/icons";
import { TrainMap } from "./map/TrainMap";

const categoryOf = (t: Train) =>
  t.category && KNOWN_CATEGORIES.includes(t.category.toUpperCase()) ? t.category.toUpperCase() : OTHER;

export default function App() {
  const { data, error, clockOffset } = useLiveTrains();
  const { data: meta } = useMeta();
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const { data: detail, error: detailError } = useTrainDetail(selectedKey);
  const [flyTo, setFlyTo] = useState<{ at: LatLon; seq: number } | null>(null);
  const [filters, setFilters] = useState<FilterState>({
    hidden: new Set(),
    showStations: true,
    showRailOverlay: false,
    hideNotStarted: false,
  });
  const [now, setNow] = useState(Date.now());

  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), 5000);
    return () => window.clearInterval(id);
  }, []);

  const allTrains = useMemo(() => data?.trains ?? [], [data]);
  const trains = useMemo(
    () =>
      allTrains.filter(
        (t) => !filters.hidden.has(categoryOf(t)) && !(filters.hideNotStarted && t.status === "not_started"),
      ),
    [allTrains, filters],
  );
  const categories = useMemo(() => {
    const counts = new Map<string, number>();
    for (const t of allTrains) counts.set(categoryOf(t), (counts.get(categoryOf(t)) ?? 0) + 1);
    return [...KNOWN_CATEGORIES, OTHER].filter((c) => counts.has(c)).map((name) => ({ name, count: counts.get(name)! }));
  }, [allTrains]);

  const select = useCallback((key: string) => setSelectedKey(key), []);
  const pick = useCallback((t: Train) => {
    setSelectedKey(t.key);
    setFlyTo({ at: [t.lat, t.lon], seq: Date.now() });
  }, []);

  // A selected train that finished its run disappears from the list: close the panel.
  useEffect(() => {
    if (selectedKey && data && !data.trains.some((t) => t.key === selectedKey) && !detail) setSelectedKey(null);
  }, [data, selectedKey, detail]);

  return (
    <div className="app">
      <TrainMap
        trains={trains}
        clockOffset={clockOffset}
        selectedKey={selectedKey}
        detail={selectedKey && detail?.key === selectedKey ? detail : null}
        onSelect={select}
        showStations={filters.showStations}
        showRailOverlay={filters.showRailOverlay}
        flyTo={flyTo}
      />

      <section className="panel controls">
        <h1>
          ICtracker <span className="muted small">PKP Intercity live map</span>
        </h1>
        <SearchBar trains={allTrains} onPick={pick} />
        <Filters categories={categories} state={filters} onChange={setFilters} />
      </section>

      {selectedKey && (
        <TrainPanel
          detail={detail?.key === selectedKey ? detail : null}
          error={detailError}
          now={now + clockOffset}
          onClose={() => setSelectedKey(null)}
        />
      )}

      <StatusBar
        meta={meta}
        trainsError={error}
        visibleCount={trains.length}
        snapshotAtMs={data?.snapshotAtMs ?? null}
        stale={data?.stale ?? false}
        now={now + clockOffset}
      />
    </div>
  );
}
