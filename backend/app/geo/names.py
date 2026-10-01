"""Matching PLK station names to OpenStreetMap railway features."""

from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from rapidfuzz import fuzz, process

from app.geo.polyline import LatLon, haversine_m

# Abbreviations and gendered adjective forms are folded to one token so that
# "Kraków Gł." == "Kraków Główny" and "Opole Główne" == "Opole Gł.".
_TOKEN_MAP = {
    "glowny": "gl", "glowna": "gl", "glowne": "gl", "gl": "gl",
    "centralny": "centr", "centralna": "centr", "centralne": "centr", "centr": "centr",
    "wschodni": "wsch", "wschodnia": "wsch", "wschodnie": "wsch", "wsch": "wsch",
    "zachodni": "zach", "zachodnia": "zach", "zachodnie": "zach", "zach": "zach",
    "polnocny": "pn", "polnocna": "pn", "polnocne": "pn", "pn": "pn", "pln": "pn",
    "poludniowy": "pd", "poludniowa": "pd", "poludniowe": "pd", "pd": "pd", "pld": "pd",
    "mazowiecki": "maz", "mazowiecka": "maz", "mazowieckie": "maz", "maz": "maz",
    "wielkopolski": "wlkp", "wielkopolska": "wlkp", "wielkopolskie": "wlkp", "wlkp": "wlkp",
    "slaski": "sl", "slaska": "sl", "slaskie": "sl", "sl": "sl",
    "miasto": "m", "miasta": "m", "m": "m",
    "osiedle": "osiedle", "os": "osiedle",
    "przystanek": "", "stacja": "", "st": "", "pkp": "", "dworzec": "",
}

# Preference when several OSM features share a name: real passenger stations first.
_KIND_RANK = {"station": 0, "halt": 1, "stop": 2, "junction": 3, "service_station": 3, "spur_junction": 4}


def fold(text: str) -> str:
    text = text.replace("ł", "l").replace("Ł", "L")
    text = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def normalize(name: str) -> str:
    tokens = re.split(r"[^a-z0-9]+", fold(name))
    out = []
    for tok in tokens:
        if not tok:
            continue
        tok = _TOKEN_MAP.get(tok, tok)
        if tok:
            out.append(tok)
    return " ".join(out)


@dataclass
class OsmFeature:
    osm_id: str
    lat: float
    lon: float
    kind: str
    names: list[str]  # primary names first, then old/alternative names


@dataclass
class Match:
    plk_id: int
    plk_name: str
    lat: float
    lon: float
    source: str  # osm | osm-fuzzy | osm-context | nominatim | override
    osm_id: str | None = None
    osm_name: str | None = None
    score: float | None = None


def features_from_overpass(elements: Iterable[dict]) -> list[OsmFeature]:
    feats = []
    for el in elements:
        tags = el.get("tags", {})
        primary = [tags.get(k) for k in ("name", "name:pl", "official_name", "short_name")]
        alt = []
        for k in ("alt_name", "old_name", "railway:name"):
            if tags.get(k):
                alt.extend(tags[k].split(";"))
        names = [n.strip() for n in primary + alt if n and n.strip()]
        if not names:
            continue
        kind = tags.get("railway") or ("station" if tags.get("train") == "yes" else "other")
        feats.append(OsmFeature(el["id"], el["lat"], el["lon"], kind, list(dict.fromkeys(names))))
    return feats


class NameIndex:
    def __init__(self, features: Sequence[OsmFeature]) -> None:
        self.by_norm: dict[str, list[OsmFeature]] = defaultdict(list)
        for f in features:
            for n in {normalize(x) for x in f.names}:
                if n:
                    self.by_norm[n].append(f)
        self._choices = list(self.by_norm.keys())

    def exact(self, name: str) -> list[OsmFeature]:
        return self._dedupe(self.by_norm.get(normalize(name), []))

    def fuzzy(self, name: str, cutoff: float = 88.0) -> tuple[list[OsmFeature], float] | None:
        norm = normalize(name)
        if not norm:
            return None
        hit = process.extractOne(norm, self._choices, scorer=fuzz.token_sort_ratio, score_cutoff=cutoff)
        if hit is None:
            return None
        return self._dedupe(self.by_norm[hit[0]]), float(hit[1])

    @staticmethod
    def _dedupe(feats: list[OsmFeature]) -> list[OsmFeature]:
        """Collapse features of the same place (e.g. a station node and its area) and rank by kind."""
        feats = sorted(feats, key=lambda f: _KIND_RANK.get(f.kind, 9))
        out: list[OsmFeature] = []
        for f in feats:
            if all(haversine_m(f.lat, f.lon, g.lat, g.lon) > 1500 for g in out):
                out.append(f)
        return out


def match_stations(
    plk: dict[int, str],
    index: NameIndex,
    neighbours: dict[int, set[int]] | None = None,
    fuzzy_cutoff: float = 88.0,
) -> tuple[dict[int, Match], list[tuple[int, str, str]]]:
    """Match PLK {id: name} to OSM. Returns matches and a list of (id, name, problem) for review.

    When a name is ambiguous (several distant features, e.g. many villages called "Kolonia"),
    `neighbours` (station ids adjacent on some timetable route) is used to pick the candidate
    closest to already-located neighbours.
    """
    matches: dict[int, Match] = {}
    ambiguous: dict[int, tuple[list[OsmFeature], str, float | None]] = {}
    problems: list[tuple[int, str, str]] = []

    for pid, name in plk.items():
        cands, source, score = index.exact(name), "osm", None
        if not cands:
            fz = index.fuzzy(name, fuzzy_cutoff)
            if fz:
                (cands, score), source = fz, "osm-fuzzy"
        if not cands:
            problems.append((pid, name, "no match"))
            continue
        if len(cands) == 1:
            f = cands[0]
            matches[pid] = Match(pid, name, f.lat, f.lon, source, f.osm_id, f.names[0], score)
        else:
            ambiguous[pid] = (cands, source, score)

    # Resolve ambiguous names using located route neighbours; repeat while progress is made.
    for _ in range(3):
        resolved = []
        for pid, (cands, source, score) in ambiguous.items():
            near: list[LatLon] = [
                (matches[n].lat, matches[n].lon) for n in (neighbours or {}).get(pid, ()) if n in matches
            ]
            if not near:
                continue
            f = min(cands, key=lambda c: min(haversine_m(c.lat, c.lon, la, lo) for la, lo in near))
            matches[pid] = Match(pid, plk[pid], f.lat, f.lon, "osm-context", f.osm_id, f.names[0], score)
            resolved.append(pid)
        for pid in resolved:
            del ambiguous[pid]
        if not resolved:
            break

    for pid, (cands, _source, _score) in ambiguous.items():
        problems.append((pid, plk[pid], f"ambiguous ({len(cands)} candidates)"))
    return matches, problems
