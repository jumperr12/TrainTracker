"""Route every consecutive station pair on the rail graph and store the track polylines.

    python -m scripts.build_segments --mock    # pairs from the mock timetable
    python -m scripts.build_segments           # pairs from cached real schedules (data/cache)
    python -m scripts.build_segments --rebuild # discard stored segments first
    python -m scripts.build_segments --retry-straight  # re-route pairs that fell back to straight lines

Needs rail_graph.pkl (scripts.build_rail_graph) and stations_geo.json (scripts.build_station_coords).
The backend also routes new pairs by itself while running, so this is mainly for the first build.
"""

import argparse
import csv
import time

from app.geo.rail import RailGraphData, RailRouter, SegmentStore, located_pairs, route_missing_pairs
from app.geo.stations import StationIndex
from scripts.common import settings_for, station_sequences


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--rebuild", action="store_true")
    parser.add_argument("--retry-straight", action="store_true")
    args = parser.parse_args()

    settings = settings_for(args.mock)
    if not settings.rail_graph_path.exists():
        raise SystemExit(f"{settings.rail_graph_path} missing. Run: python -m scripts.build_rail_graph")
    stations = StationIndex.load(settings.stations_geo_path, settings.overrides_path)
    if not len(stations):
        raise SystemExit(f"No station coordinates in {settings.stations_geo_path}. Run scripts.build_station_coords")

    store = SegmentStore(settings.segments_path)
    if args.rebuild:
        store.clear()
    else:
        if args.retry_straight:
            print(f"dropping {store.drop_fallbacks()} straight-line fallbacks")
        stale = store.drop_stale(stations.coords())
        if stale:
            print(f"dropping {stale} segments whose station coordinates changed")

    pairs = sorted(located_pairs(station_sequences(settings, args.mock), lambda s: s in stations))
    missing = [p for p in pairs if not store.has(*p)]
    print(f"{len(pairs)} station pairs, {len(missing)} to route")
    if not missing:
        return

    t0 = time.time()
    router = RailRouter(RailGraphData.load(settings.rail_graph_path))
    print(f"rail graph loaded in {time.time() - t0:.1f}s")

    issues = []
    names = {sid: (stations.get(sid).name if stations.get(sid) else str(sid)) for p in missing for sid in p}

    def on_issue(a, b, result):
        issues.append((a, b, names[a], names[b], round(result.straight_m), result.reason))
        print(f"  straight line: {names[a]} -> {names[b]} ({result.reason})")

    t1 = time.time()
    done = 0
    for i in range(0, len(missing), 50):
        batch = missing[i : i + 50]
        done += route_missing_pairs(router, store, batch, stations.coords(), on_issue=on_issue)
        store.save()
        print(f"  {min(i + 50, len(missing))}/{len(missing)} routed ({time.time() - t1:.0f}s)")

    settings.reports_dir.mkdir(parents=True, exist_ok=True)
    report = settings.reports_dir / ("segment_issues_mock.csv" if args.mock else "segment_issues.csv")
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(["from_id", "to_id", "from", "to", "straight_m", "reason"])
        w.writerows(issues)
    print(f"{done} segments added, {len(issues)} straight-line fallbacks -> {report}")


if __name__ == "__main__":
    main()
