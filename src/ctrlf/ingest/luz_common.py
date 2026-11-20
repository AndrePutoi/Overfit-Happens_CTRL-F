"""Partilhado pelos scripts que obtêm candeeiros/postes (OSM e Mapillary): zonas a consultar e escrita de GeoJSON.

As zonas vêm das posições das PRÓPRIAS imagens (data/raw/<cidade>/meta.jsonl): só se consultam as células de CELL graus
que têm pelo menos uma imagem (mais uma margem), em vez do retângulo todo da cidade.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

from ctrlf.paths import ROOT
REF = ROOT / "data" / "reference"
USER_AGENT = "ctrlf-hackathon-research/0.1"          # genérico: sem dados pessoais
from ctrlf.ingest.zonas import todas as _zonas_novas      # noqa: E402  (zonas criadas com `zona run`: data/zonas/<nome>/zona.json)
CITIES = ("porto", "lisboa", "aveiro") + tuple(n for n in _zonas_novas() if n not in ("porto", "lisboa", "aveiro"))


def points(city: str) -> list[tuple[float, float]]:
    f = ROOT / "data" / "raw" / city / "meta.jsonl"
    if not f.exists():
        raise SystemExit(f"{f} não existe")
    return [(m["lat"], m["lon"]) for m in map(json.loads, f.read_text(encoding="utf-8").splitlines()) if "lat" in m]


def occupied_cells(city: str, cell: float = 0.009, margin: float = 0.0015):
    """-> [(minLon, minLat, maxLon, maxLat)] das células com imagens, alargadas por `margin` graus."""
    seen = set()
    for lat, lon in points(city):
        seen.add((math.floor(lon / cell), math.floor(lat / cell)))
    return [(i * cell - margin, j * cell - margin, (i + 1) * cell + margin, (j + 1) * cell + margin)
            for i, j in sorted(seen)]


def write_geojson(path: Path, features: list[dict], extra: dict | None = None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection", **(extra or {}), "features": features}
    path.write_text(json.dumps(fc, ensure_ascii=False), encoding="utf-8")


def feature(lon: float, lat: float, props: dict) -> dict:
    return {"type": "Feature", "properties": props, "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}}
