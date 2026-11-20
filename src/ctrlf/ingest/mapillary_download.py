"""Mapillary API v4: contar cobertura e descarregar imagens + metadados (https://www.mapillary.com/developer/api-documentation).

TOKEN (Client Token de https://mapillary.com/dashboard/developers). Nunca no código nem no git:
    export MAPILLARY_TOKEN="MLY|..."            ou, no ficheiro .env da raiz (ignorado pelo git):
    MAPILLARY_TOKEN=MLY|...

Modos
  --bbox minLon minLat maxLon maxLat    caixa; a API só aceita caixas MENORES que 0.01° de lado, por isso a caixa
                                        é partida em células de <= 0.009° (e subdividida se uma célula devolver 2000)
  --points ficheiro.geojson [--radius 25 --per-point 5]
                                        procura as melhores imagens num raio (máx. 50 m) de cada ponto conhecido
                                        (ex.: ecoilhas subterrâneas de Lisboa/Porto/Aveiro)
  --since 2023-06-01                    só imagens capturadas depois (ex.: Avenida requalificada em maio de 2023)
  --stride N                            1 imagem em cada N (ordenadas por sequência e hora), para zonas muito redundantes
  --count-only                          só conta (por ano, panoramas) e não descarrega

    python -m ctrlf.ingest.mapillary_download --bbox -8.6560 40.6405 -8.6440 40.6460 --since 2023-06-01 --count-only
    python -m ctrlf.ingest.mapillary_download --points data/external/lisboa_opendata/ecoilhas_subterraneas.geojson --per-point 3

As imagens vão para data/raw/mapillary (TEMPORÁRIO). Passam pelo portão de privacidade (privacy/gate.py) antes de
qualquer deteção. Imagens sob CC BY-SA 4.0: guardar a atribuição por imagem (meta.jsonl).
Câmaras fisheye são ignoradas (o contrato ImageMeta só admite perspective | equirectangular).
NÃO TESTADO com token real (não havia token quando foi escrito); a parte offline está em tests/unit/10_test_mapillary_offline.py.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from collections import Counter
from pathlib import Path

import requests

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.common.contract import ImageMeta  # noqa: E402

API = "https://graph.mapillary.com/images"
FIELDS = ("id,geometry,computed_geometry,compass_angle,computed_compass_angle,captured_at,camera_type,"
          "camera_parameters,is_pano,quality_score,width,height,sequence,thumb_original_url,thumb_2048_url,thumb_1024_url")
LICENSE = "CC BY-SA 4.0"
ATTRIBUTION = "Imagens © colaboradores do Mapillary, CC BY-SA 4.0 (mapillary.com)"
MAX_SIDE = 0.009          # a API exige < 0.01° de lado
LIMIT = 2000              # máximo por pedido (sem paginação com bbox)


def load_token() -> str | None:
    t = os.environ.get("MAPILLARY_TOKEN")
    env = ROOT / ".env"
    if not t and env.exists():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("MAPILLARY_TOKEN="):
                t = line.split("=", 1)[1].strip().strip("\"'")
    return t or None


def cells(bbox, max_side=MAX_SIDE):
    """Parte (minLon, minLat, maxLon, maxLat) em células de lado <= max_side."""
    x0, y0, x1, y1 = bbox
    nx, ny = max(1, math.ceil((x1 - x0) / max_side)), max(1, math.ceil((y1 - y0) / max_side))
    dx, dy = (x1 - x0) / nx, (y1 - y0) / ny
    return [(x0 + i * dx, y0 + j * dy, x0 + (i + 1) * dx, y0 + (j + 1) * dy) for j in range(ny) for i in range(nx)]


def _get(params: dict, token: str) -> list[dict]:
    for attempt in range(5):
        r = requests.get(API, params=params, headers={"Authorization": f"OAuth {token}"}, timeout=60)
        if r.status_code == 200:
            return r.json().get("data", [])
        if r.status_code in (429, 500, 502, 503):                 # limite de pedidos ou erro transitório
            time.sleep(2 ** attempt)
            continue
        sys.exit(f"Mapillary respondeu {r.status_code}: {r.text[:300]}")
    sys.exit("Mapillary: demasiadas tentativas falhadas")


def fetch_bbox(bbox, token, since=None, depth=0):
    p = {"fields": FIELDS, "bbox": ",".join(f"{v:.6f}" for v in bbox), "limit": LIMIT}
    if since:
        p["start_captured_at"] = f"{since}T00:00:00Z"
    data = _get(p, token)
    if len(data) >= LIMIT and depth < 3:                          # truncado: subdividir
        half = max(bbox[2] - bbox[0], bbox[3] - bbox[1]) / 2 + 1e-9
        out = []
        for c in cells(bbox, half):
            out += fetch_bbox(c, token, since, depth + 1)
        return out
    return data


def fetch_points(points, token, radius, per_point, since=None):
    out = []
    for lon, lat in points:
        p = {"fields": FIELDS, "lat": f"{lat:.6f}", "lng": f"{lon:.6f}", "radius": min(radius, 50),
             "limit": min(per_point, 100)}
        out += _get(p, token)                                     # a doc não combina lat/lng com start_captured_at
    if since:
        ms = int(time.mktime(time.strptime(since, "%Y-%m-%d")) * 1000)
        out = [i for i in out if i.get("captured_at", 0) >= ms]
    return out


def load_points(path: Path):
    d = json.loads(path.read_text(encoding="utf-8"))
    return [tuple(f["geometry"]["coordinates"][:2]) for f in d["features"] if f.get("geometry")]


def hfov_from_params(item) -> float | None:
    """Campo de visão horizontal a partir de camera_parameters[0] (foco normalizado pela MAIOR dimensão, convenção
    OpenSfM; A CONFIRMAR com imagens reais). Só para câmaras em perspetiva e imagens horizontais."""
    cp, w, h = item.get("camera_parameters"), item.get("width"), item.get("height")
    if not cp or not w or not h or cp[0] <= 0:
        return None
    f = cp[0] * max(w, h) / w            # foco em unidades da largura
    return round(math.degrees(2 * math.atan(0.5 / f)), 1)


def camera_type(it) -> str | None:
    """'perspective' | 'equirectangular' | None (fisheye: não suportado pelo contrato)."""
    t = it.get("camera_type")
    if t in ("equirectangular", "spherical") or it.get("is_pano"):
        return "equirectangular"
    if t == "fisheye":
        return None
    return "perspective"


def to_meta(it, dest: Path) -> ImageMeta:
    geo = it.get("computed_geometry") or it["geometry"]
    lon, lat = geo["coordinates"]
    heading = it.get("computed_compass_angle", it.get("compass_angle"))
    ctype = camera_type(it)
    hfov = None if ctype != "perspective" else (hfov_from_params(it) or 65.0)
    return ImageMeta(source="mapillary", source_image_id=str(it["id"]), lat=lat, lon=lon, heading=float(heading),
                     captured_at=str(it.get("captured_at", "")), camera_type=ctype, hfov_deg=hfov, path=str(dest),
                     license=LICENSE, attribution=ATTRIBUTION,
                     extra={"sequence": it.get("sequence"), "quality_score": it.get("quality_score"),
                            "width": it.get("width"), "height": it.get("height"),
                            "hfov_from_camera_parameters": hfov_from_params(it) is not None})


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("MINLON", "MINLAT", "MAXLON", "MAXLAT"))
    ap.add_argument("--points", type=Path)
    ap.add_argument("--radius", type=int, default=25)
    ap.add_argument("--per-point", type=int, default=3)
    ap.add_argument("--since", help="AAAA-MM-DD")
    ap.add_argument("--min-quality", type=float, default=0.0)
    ap.add_argument("--stride", type=int, default=1, help="1 imagem em cada N (por sequência e hora): zonas muito redundantes")
    ap.add_argument("--max", type=int, default=300, help="máximo de imagens a descarregar (as primeiras por sequência e hora: ficam contíguas, úteis para associar vistas)")
    ap.add_argument("--max-panoramas", type=int, default=None, help="dentro de --max, reserva até N lugares para panoramas 360° (o resto são imagens planas); omissão: sem reserva")
    ap.add_argument("--count-only", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "raw" / "mapillary"))
    args = ap.parse_args()
    if bool(args.bbox) == bool(args.points):
        sys.exit("Indica --bbox OU --points")

    token = load_token()
    if not token:
        sys.exit("Falta o token: export MAPILLARY_TOKEN='MLY|...' ou MAPILLARY_TOKEN=... no ficheiro .env da raiz.")

    if args.bbox:
        cs = cells(tuple(args.bbox))
        print(f"caixa partida em {len(cs)} célula(s) de <= {MAX_SIDE}°")
        items = {i["id"]: i for c in cs for i in fetch_bbox(c, token, args.since)}
    else:
        pts = load_points(args.points)
        print(f"{len(pts)} pontos, raio {args.radius} m, {args.per_point} imagem(ns) por ponto")
        items = {i["id"]: i for i in fetch_points(pts, token, args.radius, args.per_point, args.since)}
    items = [i for i in items.values() if (i.get("quality_score") if i.get("quality_score") is not None else 1.0) >= args.min_quality]
    n_fish = sum(1 for i in items if camera_type(i) is None)
    items = [i for i in items if camera_type(i) is not None]

    items.sort(key=lambda i: (str(i.get("sequence")), i.get("captured_at", 0)))          # sequência e hora: o corte de --max fica contíguo, não espalhado
    if args.stride > 1:
        items = items[:: args.stride]
    n_pano = sum(1 for i in items if i.get("is_pano"))
    print(f"{len(items)} imagens únicas ({n_pano} panoramas 360°; {n_fish} fisheye ignoradas).")
    if items:
        years = Counter(time.gmtime(i["captured_at"] / 1000).tm_year for i in items if i.get("captured_at"))
        print("por ano de captura:", dict(sorted(years.items())))
    if args.count_only or not items:
        return

    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    done = failed = 0
    with open(out / "meta.jsonl", "a", encoding="utf-8") as mf:
        sel = items
        if args.max_panoramas is not None:
            panos = [i for i in items if i.get("is_pano")][: args.max_panoramas]
            planas = [i for i in items if not i.get("is_pano")][: max(0, args.max - len(panos))]
            sel = sorted(planas + panos, key=lambda i: (str(i.get("sequence")), i.get("captured_at", 0)))
            print(f"seleção: {len(planas)} planas + {len(panos)} panoramas")
        for it in sel[: args.max]:
            url = it.get("thumb_original_url") or it.get("thumb_2048_url") or it.get("thumb_1024_url")
            if not url or ("compass_angle" not in it and "computed_compass_angle" not in it):
                continue
            dest = out / f"{it['id']}.jpg"
            if not dest.exists():
                content = None
                for attempt in range(1, 6):                      # o servidor das imagens dá timeouts: repetir com espera crescente
                    try:
                        resp = requests.get(url, timeout=120)
                        if resp.status_code == 200:
                            content = resp.content
                            break
                        if resp.status_code not in (429, 500, 502, 503, 504):
                            break
                    except requests.exceptions.RequestException as e:
                        print(f"  {it['id']}: {type(e).__name__} (tentativa {attempt}/5)", flush=True)
                    time.sleep(2 * attempt)
                if content is None:
                    failed += 1
                    continue
                tmp = dest.with_suffix(".part")                  # escrita atómica: um corte não deixa um .jpg truncado
                tmp.write_bytes(content)
                tmp.replace(dest)
                time.sleep(0.05)
            mf.write(json.dumps(to_meta(it, dest).__dict__, ensure_ascii=False) + "\n")
            done += 1
    print(f"{done} imagens em {out}  |  metadados: {out / 'meta.jsonl'}" + (f"  |  {failed} FALHARAM (voltar a correr retoma)" if failed else ""))


if __name__ == "__main__":
    main()
