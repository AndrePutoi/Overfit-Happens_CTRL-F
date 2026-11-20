"""Estradas do OpenStreetMap (Overpass) para a zona piloto -> data/reference/osm_<cidade>_vias.json (cache).

    python -m ctrlf.ingest.osm_vias aveiro            # usa a cache se existir
    python -m ctrlf.ingest.osm_vias aveiro --refresh

Só vias de circulação (não passeios, ciclovias, escadas, caminhos, serviços): é onde as câmaras andam e junto de onde ficam
sinais e contentores. Cada via = linha de pontos (lat, lon). Dados © colaboradores do OpenStreetMap (ODbL). O pedido só leva a
caixa da zona piloto e um nome de cliente genérico.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

from ctrlf.paths import ROOT
BBOX = {"aveiro": (40.6405, -8.6560, 40.6460, -8.6440)}          # S, O, N, E (docs/zona-piloto-e-treino)
MARGIN = 0.002                                                    # ~200 m, para estradas que passam mesmo fora da caixa
HIGHWAYS = ("motorway|trunk|primary|secondary|tertiary|unclassified|residential|living_street|pedestrian|road|"
            "motorway_link|trunk_link|primary_link|secondary_link|tertiary_link")
URLS = ("https://overpass-api.de/api/interpreter", "https://overpass.kumi.systems/api/interpreter",
        "https://overpass.private.coffee/api/interpreter")


def _bbox(city: str) -> tuple:
    """Caixa (S, O, N, E): as zonas fixas daqui ou, para uma zona nova, a de data/zonas/<nome>/zona.json."""
    if city in BBOX:
        return BBOX[city]
    if str(ROOT) not in sys.path:                           # corrido como `python -m ctrlf.ingest.osm_vias`, só ingest/ está no caminho
        sys.path.insert(0, str(ROOT))
    from ctrlf.ingest.zonas import caixa_swne, carregar
    z = carregar(city)
    if z is None:
        raise SystemExit(f"zona {city!r} desconhecida: não está em BBOX nem em data/zonas/")
    return caixa_swne(z)


def fetch(city: str) -> dict:
    s, w, n, e = _bbox(city)
    q = f'[out:json][timeout:90];way["highway"~"^({HIGHWAYS})$"]({s - MARGIN},{w - MARGIN},{n + MARGIN},{e + MARGIN});out geom tags;'
    js, last = None, ""
    for attempt in range(6):                                          # 502/429/504 = servidor sobrecarregado: espera e troca de espelho
        url = URLS[attempt % len(URLS)]
        try:
            r = requests.post(url, data={"data": q}, headers={"User-Agent": "ctrlf-hackathon-research/0.1"}, timeout=120)
            if r.status_code == 200:
                js = r.json()
                break
            last = f"{url.split('/')[2]} HTTP {r.status_code}"
        except (requests.RequestException, ValueError) as e:
            last = f"{url.split('/')[2]} {type(e).__name__}"
        print(f"  tentativa {attempt + 1} falhou ({last}); a esperar...", flush=True)
        time.sleep(5 * (attempt + 1))
    if js is None:
        sys.exit(f"Overpass indisponível: {last}")
    if "remark" in js and "error" in js["remark"].lower():            # o Overpass responde 200 com resultados parciais
        sys.exit(f"Overpass devolveu resultados parciais: {js['remark']}")
    ways = [{"id": el["id"], "highway": el["tags"].get("highway"), "name": el["tags"].get("name"),
             "pts": [[g["lat"], g["lon"]] for g in el["geometry"]]} for el in js["elements"] if el.get("type") == "way" and el.get("geometry")]
    return {"cidade": city, "bbox": _bbox(city), "fonte": "OpenStreetMap (ODbL)", "n": len(ways), "vias": ways}


def load(city: str, refresh: bool = False) -> dict:
    p = ROOT / "data" / "reference" / f"osm_{city}_vias.json"
    if p.exists() and not refresh:
        return json.loads(p.read_text(encoding="utf-8"))
    d = fetch(city)
    p.parent.mkdir(parents=True, exist_ok=True)               # num código acabado de extrair data/reference/ ainda não existe
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return d


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?", default="aveiro")
    ap.add_argument("--refresh", action="store_true")
    a = ap.parse_args()
    d = load(a.city, a.refresh)
    from collections import Counter
    print(f"{d['n']} vias em {a.city}:", dict(Counter(v["highway"] for v in d["vias"])))
