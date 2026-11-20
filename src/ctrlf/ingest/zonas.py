"""Registo de ZONAS: uma zona nova = uma pasta `data/zonas/<nome>/zona.json` com a caixa e os parâmetros de descarga.

    {"nome": "lisboa_teste", "bbox": [minLon, minLat, maxLon, maxLat], "since": "2023-01-01", "max": 20, "stride": 1, "max_panoramas": 4}

Aveiro, Porto e Lisboa continuam a existir como antes (configs/admissao.yaml, ingest/osm_vias.py); este módulo acrescenta as zonas novas SEM os editar à mão, para os scripts
de ingestão e de referência (OSM) as aceitarem. `bbox` segue a ordem do Mapillary (O, S, E, N); `caixa_swne` devolve a ordem (S, O, N, E) que o resto do código usa.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from ctrlf.paths import ROOT
ZONAS_DIR = ROOT / "data" / "zonas"
NOME_VALIDO = re.compile(r"^[a-z0-9][a-z0-9_]{1,40}$")


def validar_nome(nome: str) -> str:
    if not NOME_VALIDO.match(nome):
        raise ValueError(f"nome de zona inválido {nome!r}: minúsculas, dígitos e _ (2 a 41 caracteres); usa-se em caminhos de ficheiros")
    return nome


def pasta(nome: str) -> Path:
    return ZONAS_DIR / validar_nome(nome)


def carregar(nome: str) -> dict | None:
    f = pasta(nome) / "zona.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else None


def todas() -> dict[str, dict]:
    out = {}
    if ZONAS_DIR.exists():
        for f in sorted(ZONAS_DIR.glob("*/zona.json")):
            try:
                out[f.parent.name] = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
    return out


def caixa_swne(z: dict) -> tuple[float, float, float, float]:
    o, s, e, n = z["bbox"]
    return (s, o, n, e)


def guardar(z: dict) -> Path:
    validar_nome(z["nome"])
    o, s, e, n = z["bbox"]
    if not (-180 <= o < e <= 180 and -90 <= s < n <= 90):
        raise ValueError(f"caixa inválida {z['bbox']}: esperado [minLon, minLat, maxLon, maxLat]")
    f = pasta(z["nome"]) / "zona.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8")
    try:                                                    # ao definir uma zona, cria logo o mapa dela (pré-visualização da caixa); nunca impede guardar a zona
        mapa_zona(z)
    except Exception:
        pass
    return f


MAPA_ZONA = """<!doctype html><html lang="pt"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Zona __NOME__</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>html,body,#m{height:100%;margin:0}.b{position:absolute;z-index:1000;top:10px;right:10px;background:#fff;padding:8px 12px;border-radius:6px;font:13px system-ui;box-shadow:0 1px 4px #0006;max-width:280px}</style></head><body>
<div id="m"></div><div class="b"><b>__NOME__</b><br>caixa: __BBOX__<br>raio: __RAIO__<br><small>Só a caixa definida. Depois de <code>zona run</code>, o mapa com as deteções fica em data/catalog/__NOME__/mapa.html.<br>© colaboradores do OpenStreetMap (ODbL)</small></div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>const B=__CAIXA__;const map=L.map('m');L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png',{maxZoom:19,attribution:'© OpenStreetMap'}).addTo(map);
const r=L.rectangle(B,{color:'#d62728',weight:2,fillOpacity:.08}).addTo(map);map.fitBounds(r.getBounds(),{padding:[30,30]});</script></body></html>"""


def mapa_zona(z: dict) -> Path:
    """data/zonas/<nome>/mapa_zona.html: a caixa da zona sobre o OpenStreetMap (ficheiro único; os mosaicos só carregam se a página for servida por http: `python -m http.server`)."""
    s, o, n, e = caixa_swne(z)
    html = (MAPA_ZONA.replace("__NOME__", z["nome"]).replace("__BBOX__", f"[{z['bbox'][0]}, {z['bbox'][1]}, {z['bbox'][2]}, {z['bbox'][3]}]")
            .replace("__RAIO__", f"{z['raio_m']:g} m" if z.get("raio_m") else "—").replace("__CAIXA__", f"[[{s},{o}],[{n},{e}]]"))
    f = pasta(z["nome"]) / "mapa_zona.html"
    f.write_text(html, encoding="utf-8")
    return f


# ---------------------------------------------------------------------------- criar uma zona a partir de um nome de sítio (OpenStreetMap / Nominatim) ou de um ponto
NOMINATIM = "https://nominatim.openstreetmap.org/search"
USER_AGENT = "ctrlf-hackathon-research/0.1"            # genérico: sem dados pessoais (política de uso do Nominatim: identificar a aplicação, máx. 1 pedido por segundo)


def caixa_em_torno(lat: float, lon: float, raio_m: float) -> list[float]:
    """Caixa [minLon, minLat, maxLon, maxLat] com `raio_m` metros a cada lado do ponto (aproximação plana, boa para raios de centenas de metros)."""
    import math
    dlat = raio_m / 111_320.0
    dlon = raio_m / (111_320.0 * max(math.cos(math.radians(lat)), 1e-6))
    return [round(lon - dlon, 6), round(lat - dlat, 6), round(lon + dlon, 6), round(lat + dlat, 6)]


def geocodificar(lugar: str, http_get=None) -> dict:
    """Nome de sítio -> {lat, lon, nome, osm} pelo Nominatim (só o texto do sítio vai à rede). `http_get(url, params, headers)` permite testar sem rede."""
    if http_get is None:
        import requests
        http_get = lambda u, p, h: requests.get(u, params=p, headers=h, timeout=30).json()          # noqa: E731
    res = http_get(NOMINATIM, {"q": lugar, "format": "jsonv2", "limit": 1}, {"User-Agent": USER_AGENT})
    if not res:
        raise ValueError(f"o OpenStreetMap não encontrou {lugar!r}")
    r = res[0]
    return {"lat": float(r["lat"]), "lon": float(r["lon"]), "nome": r.get("display_name", lugar), "osm": f"{r.get('osm_type', '?')}/{r.get('osm_id', '?')}"}


def criar(nome: str, lugar: str | None = None, centro: tuple[float, float] | None = None, raio_m: float = 250.0, since: str = "2023-01-01",
          max_imagens: int = 20, max_panoramas: int = 4, http_get=None) -> dict:
    """Cria data/zonas/<nome>/zona.json para uma zona-piloto pequena. Dá o centro por `lugar` (OSM) ou por `centro=(lat, lon)`. Devolve o dicionário gravado."""
    validar_nome(nome)
    if bool(lugar) == bool(centro):
        raise ValueError("indica o sítio (lugar) OU o centro (lat, lon)")
    if not (50 <= raio_m <= 1500):
        raise ValueError("raio entre 50 e 1500 m (uma zona-piloto é pequena; a API do Mapillary também limita a caixa)")
    fonte = {"tipo": "ponto"}
    if lugar:
        g = geocodificar(lugar, http_get)
        centro, fonte = (g["lat"], g["lon"]), {"tipo": "osm_nominatim", "consulta": lugar, "encontrado": g["nome"], "osm": g["osm"], "licenca": "© colaboradores do OpenStreetMap (ODbL)"}
    z = {"nome": nome, "bbox": caixa_em_torno(centro[0], centro[1], raio_m), "centro": {"lat": centro[0], "lon": centro[1]}, "raio_m": raio_m, "since": since,
         "max": max_imagens, "max_panoramas": max_panoramas, "stride": 1, "fonte_da_caixa": fonte}
    guardar(z)
    return z

