"""OpenStreetMap (Overpass) -> camadas de REFERÊNCIA das zonas com imagens: luz, reciclagem, papeleiras, sinais.

    python -m ctrlf.ingest.osm_ref aveiro porto lisboa            # tudo; repetir o comando completa o que faltou
    python -m ctrlf.ingest.osm_ref aveiro --tile 0.003 --status   # só mostra a cobertura (não consulta nada)

Diferenças face a osm_luz.py (que deixou células por obter e podia aceitar respostas incompletas):
  * UMA consulta por mosaico devolve os 4 temas; mosaicos de ~500 m (0,0045 graus) em vez de ~1 km  -> menos timeouts;
  * cada mosaico fica em cache (data/reference/osm_cache/<cidade>/<tile>_<i>_<j>.json): reexecutar só pede os que faltam;
  * o Overpass responde 200 com `remark: runtime error ...` quando estoira o tempo/memória e devolve resultados PARCIAIS:
    isso conta como FALHA (não é guardado), em vez de passar como completo;
  * `out center`: contentores/áreas mapeados como caminho (way) ou relação entram com o centro (antes eram ignorados);
  * relatório de cobertura por cidade: mosaicos pedidos / obtidos / em falta.
Temas (etiquetas OSM):
  luz         highway=street_lamp | power=pole | man_made=utility_pole
  reciclagem  amenity=recycling | amenity=waste_disposal          (inclui location=underground, recycling:* quando existem)
  papeleiras  amenity=waste_basket
  sinais      traffic_sign=* | highway=stop | highway=give_way
Saída: data/reference/osm_<cidade>_<tema>.geojson (+ osm_<cidade>_cobertura.json).  Licença: ODbL (© colaboradores do OpenStreetMap).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.ingest.luz_common import CITIES, REF, USER_AGENT, feature, occupied_cells, write_geojson  # noqa: E402

URLS = ["https://overpass-api.de/api/interpreter", "https://overpass.private.coffee/api/interpreter",
        "https://overpass.kumi.systems/api/interpreter"]
LUZ_TAGS = ("highway", "power", "man_made", "lamp_type", "light_source", "support", "ref", "height", "operator", "lit",
            "design", "colour", "material", "lamp_mount")
THEMES = ("luz", "reciclagem", "papeleiras", "sinais")


def query(bb) -> str:
    x0, y0, x1, y1 = bb
    b = f"({y0:.6f},{x0:.6f},{y1:.6f},{x1:.6f})"
    return ("[out:json][timeout:60];("
            f'node["highway"="street_lamp"]{b};node["power"="pole"]{b};node["man_made"="utility_pole"]{b};'
            f'nwr["amenity"="recycling"]{b};nwr["amenity"="waste_disposal"]{b};'
            f'node["amenity"="waste_basket"]{b};'
            f'node["traffic_sign"]{b};node["highway"="stop"]{b};node["highway"="give_way"]{b};'
            ");out center tags;")


def post(q: str, tries: int = 6) -> dict | None:
    data = urllib.parse.urlencode({"data": q}).encode()
    for k in range(tries):
        url = URLS[k % len(URLS)]
        try:
            req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=120) as r:
                d = json.loads(r.read())
            if "runtime error" in str(d.get("remark", "")).lower():          # resultado parcial: NÃO aceitar
                raise TimeoutError(d["remark"][:80])
            return d
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
            wait = 4 * (k + 1)
            print(f"    tentativa {k + 1} em {url.split('/')[2]}: {getattr(e, 'code', None) or type(e).__name__}; espera {wait}s", flush=True)
            time.sleep(wait)
    return None


def theme_of(tags: dict) -> str | None:
    if tags.get("highway") == "street_lamp" or tags.get("power") == "pole" or tags.get("man_made") == "utility_pole":
        return "luz"
    if tags.get("amenity") in ("recycling", "waste_disposal"):
        return "reciclagem"
    if tags.get("amenity") == "waste_basket":
        return "papeleiras"
    if "traffic_sign" in tags or tags.get("highway") in ("stop", "give_way"):
        return "sinais"
    return None


def tipo_luz(tags: dict) -> str:
    if tags.get("highway") == "street_lamp":
        return "street_lamp"
    return "power_pole" if tags.get("power") == "pole" else "utility_pole"


def to_feature(e: dict, theme: str) -> dict:
    if "lat" in e:
        lon, lat, geom = e["lon"], e["lat"], "node"
    else:
        lon, lat, geom = e["center"]["lon"], e["center"]["lat"], e["type"] + "_centro"
    tags = e.get("tags", {})
    props = {"source": "osm", "osm_type": e["type"], "osm_id": e["id"], "geom": geom}
    if theme == "luz":
        props.update({"tipo_osm": tipo_luz(tags), **{k: v for k, v in tags.items() if k in LUZ_TAGS}})
    else:
        props.update(tags)
    return feature(lon, lat, props)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cities", nargs="+", choices=CITIES)
    ap.add_argument("--tile", type=float, default=0.0045, help="lado do mosaico em graus (~500 m)")
    ap.add_argument("--status", action="store_true", help="só mostra a cobertura da cache")
    ap.add_argument("--sleep", type=float, default=2.0, help="pausa entre pedidos (cortesia com o servidor público)")
    a = ap.parse_args()

    for city in a.cities:
        cells = occupied_cells(city, cell=a.tile)
        cache = REF / "osm_cache" / city
        cache.mkdir(parents=True, exist_ok=True)
        path = lambda k: cache / f"t{a.tile}_{k}.json"                                    # noqa: E731
        todo = [(k, bb) for k, bb in enumerate(cells) if not path(k).exists()]
        print(f"{city}: {len(cells)} mosaicos, {len(cells) - len(todo)} em cache, {len(todo)} por pedir", flush=True)
        if not a.status:
            for n, (k, bb) in enumerate(todo, 1):
                r = post(query(bb))
                if r is None:
                    print(f"  AVISO: mosaico {k} sem resposta completa (repete o comando para o completar)", flush=True)
                else:
                    path(k).write_text(json.dumps(r.get("elements", []), ensure_ascii=False), encoding="utf-8")
                if n % 10 == 0 or n == len(todo):
                    print(f"  {n}/{len(todo)} pedidos", flush=True)
                time.sleep(a.sleep)

        got = [k for k in range(len(cells)) if path(k).exists()]
        els: dict[tuple, dict] = {}
        for k in got:
            for e in json.loads(path(k).read_text(encoding="utf-8")):
                els[(e["type"], e["id"])] = e                                             # dedup por (tipo, id) entre mosaicos
        by: dict[str, list] = {t: [] for t in THEMES}
        for e in els.values():
            t = theme_of(e.get("tags", {}))
            if t:
                by[t].append(to_feature(e, t))
        for t in THEMES:
            write_geojson(REF / f"osm_{city}_{t}.geojson", by[t], {"attribution": "© colaboradores do OpenStreetMap, ODbL"})
        missing = [list(map(lambda v: round(v, 5), cells[k])) for k in range(len(cells)) if k not in set(got)]
        rep = {"tile_graus": a.tile, "mosaicos": len(cells), "obtidos": len(got), "em_falta": missing,
               "contagens": {t: len(by[t]) for t in THEMES},
               "reciclagem_por_geom": dict(Counter(f["properties"]["geom"] for f in by["reciclagem"])),
               "reciclagem_subterraneo": sum(f["properties"].get("location") == "underground" for f in by["reciclagem"]),
               "reciclagem_com_recycling_type": sum("recycling_type" in f["properties"] for f in by["reciclagem"])}
        (REF / f"osm_{city}_cobertura.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"{city}: cobertura {len(got)}/{len(cells)} | {rep['contagens']} | subterrâneos {rep['reciclagem_subterraneo']}", flush=True)


if __name__ == "__main__":
    main()
