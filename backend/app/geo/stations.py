"""Runtime lookup of station coordinates (built by scripts/build_station_coords.py)."""

import csv
import json
from dataclasses import dataclass
from pathlib import Path

from app.geo.polyline import LatLon


@dataclass
class StationGeo:
    id: int
    name: str
    lat: float
    lon: float
    source: str


def read_overrides(path: Path) -> dict[int, StationGeo]:
    """CSV with header id,name,lat,lon — wins over any automatic match."""
    out: dict[int, StationGeo] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(line for line in f if not line.lstrip().startswith("#")):
            try:
                sid = int(row["id"])
                out[sid] = StationGeo(sid, row.get("name", "").strip(), float(row["lat"]), float(row["lon"]), "override")
            except (KeyError, TypeError, ValueError):
                continue
    return out


class StationIndex:
    def __init__(self, stations: dict[int, StationGeo] | None = None) -> None:
        self._by_id: dict[int, StationGeo] = stations or {}

    @classmethod
    def load(cls, geo_path: Path, overrides_path: Path | None = None) -> "StationIndex":
        stations: dict[int, StationGeo] = {}
        if geo_path.exists():
            data = json.loads(geo_path.read_text(encoding="utf-8"))
            for sid, s in data.get("stations", {}).items():
                stations[int(sid)] = StationGeo(int(sid), s["name"], s["lat"], s["lon"], s.get("source", "osm"))
        if overrides_path is not None:
            stations.update(read_overrides(overrides_path))
        return cls(stations)

    def __len__(self) -> int:
        return len(self._by_id)

    def __contains__(self, sid: int) -> bool:
        return sid in self._by_id

    def get(self, sid: int) -> StationGeo | None:
        return self._by_id.get(sid)

    def latlon(self, sid: int) -> LatLon | None:
        s = self._by_id.get(sid)
        return (s.lat, s.lon) if s else None

    def coords(self) -> dict[int, LatLon]:
        return {sid: (s.lat, s.lon) for sid, s in self._by_id.items()}
