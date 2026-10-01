"""Build the contracted rail graph from the downloaded OSM ways.

    python -m scripts.build_rail_graph

Reads backend/data/osm/rail/*.json (from scripts.fetch_osm), deduplicates ways by id and writes
backend/data/rail_graph.pkl.
"""

import json
import time

from app.config import get_settings
from app.geo.rail import build_graph_from_ways


def main() -> None:
    settings = get_settings()
    rail_dir = settings.data_dir / "osm" / "rail"
    files = sorted(rail_dir.glob("*.json"))
    if not files:
        raise SystemExit(f"No OSM rail files in {rail_dir}. Run: python -m scripts.fetch_osm --rail")

    t0 = time.time()
    ways: dict[int, tuple[list[int], list[tuple[float, float]]]] = {}
    for f in files:
        for w in json.loads(f.read_text(encoding="utf-8")):
            ways[w["id"]] = (w["nodes"], [tuple(p) for p in w["geometry"]])
    print(f"{len(ways)} unique ways from {len(files)} files ({time.time() - t0:.1f}s)")

    graph = build_graph_from_ways(ways.values())
    graph.save(settings.rail_graph_path)
    print(
        f"graph: {graph.n_edges} edges, {len(graph.pt_lat)} geometry points "
        f"-> {settings.rail_graph_path} ({time.time() - t0:.1f}s)"
    )


if __name__ == "__main__":
    main()
