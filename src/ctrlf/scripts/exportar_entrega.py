"""Gera o pacote de entrega de uma zona (zip + elementos.geojson, validado contra JSON Schema). O RESULTADO FINAL é elementos_unicos.geojson (ver extrair_resultado.py).

    python -m ctrlf.scripts.exportar_entrega aveiro                 # -> Entrega_C/entrega_aveiro_AAAA-MM-DD.zip
    python -m ctrlf.scripts.exportar_entrega aveiro --dup-radius 10 --sem-imagens

Parte de data/catalog/<cidade>/catalog_ajustado.geojson (posição ajustada à estrada; a original vai ao lado) + observacoes.json e das
pré-anotações COCO de cada família (TODAS as previsões, incluindo as que o pipeline deixou de fora do catálogo).

Esquema (chaves em inglês, como as tabelas image/detection/element de docs/Plano.md §9; valores de classe em português):
  elementos.geojson   FeatureCollection de pontos (WGS84 lon,lat): 1 por elemento candidato, com as suas observações ordenadas
                      por qualidade, a melhor sugerida e o grupo de duplicados
  deteccoes.json      TODAS as caixas previstas (uma por caixa e imagem), ligadas ao elemento quando entraram no catálogo
  imagens.json        as imagens referenciadas (posição da câmara, rumo, campo de visão, licença, atribuição)
  duplicados.json     grupos de elementos que podem ser o mesmo objeto (SUGESTÃO: o técnico decide)
  imagens/<id>.jpg    imagens ANONIMIZADAS (data/images_anon) referenciadas; recortes/<det_id>.jpg  recorte de cada deteção
  schema/*.json       JSON Schema de cada ficheiro; decisoes.exemplo.json  formato para DEVOLVER as escolhas do técnico
Nada é fundido de forma irreversível: as deteções ficam sempre todas.

Privacidade: só entram imagens listadas em data/images_anon/manifest.jsonl (verificadas pelo portão de privacidade). O script
recusa qualquer outra e verifica que cada ficheiro copiado é idêntico ao anonimizado.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import math
import os
import shutil
import subprocess
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.geometry.geometry import to_m  # noqa: E402

SCHEMA_VERSION = "1.3"       # 1.3 (aditiva): ilhas de reciclagem com o tipo dos caixotes e as imagens (corrigíveis), inventário `elementos_unicos` com a fusão automática, confiança calibrada e limiar automático. 1.2 (aditiva): duplicados recomendados com p e nível, posição recalculada (σ), sinal `clip_suspect`. 1.1: família `mobiliario` (class `banco`) e estado do sinal em detections[].extra
ANON = ROOT / "data" / "images_anon"
FAMILY_PREFIX = {"iluminacao": "lz", "residuos": "rs", "sinal": "sn", "mobiliario": "bc"}
PREANNOT = {"iluminacao": "luz", "residuos": "ecopontos", "sinal": "sinais", "mobiliario": "bancos"}
DUP_RADIUS = {"sinal": 5.0, "iluminacao": 8.0, "residuos": 8.0, "mobiliario": 5.0}      # m, sobre a posição ajustada (que tem ~15 m de erro)
BBOX_TOL = 0.6                                                         # px, para ligar a caixa COCO à observação do catálogo


# ------------------------------------------------------------------ utilitários
def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def iso(ms) -> str | None:
    try:
        return dt.datetime.fromtimestamp(int(ms) / 1000, tz=dt.timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def anon_names() -> set[str]:
    m = ANON / "manifest.jsonl"
    if not m.exists():
        sys.exit("data/images_anon/manifest.jsonl não existe: sem ele não há imagens anonimizadas verificadas.")
    return {json.loads(l)["file"] for l in m.read_text(encoding="utf-8").splitlines() if l.strip()}


def quality(score: float, bbox, size: tuple[int, int], img_q: float | None) -> float:
    """Qualidade da deteção para escolher a MELHOR imagem (sugestão): confiança x tamanho x centralidade x não-cortada x qualidade da imagem."""
    x1, y1, x2, y2 = bbox
    W, H = size
    size_f = max(0.2, min(1.0, math.sqrt(max(x2 - x1, 1) * max(y2 - y1, 1)) / 64.0))
    center_f = 1 - 0.4 * abs((x1 + x2) / 2 - W / 2) / (W / 2)
    edge_f = 0.7 if (x1 <= 2 or y1 <= 2 or x2 >= W - 2 or y2 >= H - 2) else 1.0
    img_f = 0.6 + 0.4 * img_q if img_q is not None else 1.0
    return round(float(score) * size_f * center_f * edge_f * img_f, 4)


# ------------------------------------------------------------------ recolha dos dados
def load_coco_all(city: str):
    """-> dets (todas as previsões), imagens {id: {file, width, height}}."""
    dets, images = [], {}
    for fam, folder in PREANNOT.items():
        p = ROOT / "data" / "preannot" / folder / city / "annotations" / "instances_default.json"
        if not p.exists():
            print(f"  aviso: sem {p}")
            continue
        d = json.loads(p.read_text(encoding="utf-8"))
        cats = {c["id"]: c["name"] for c in d["categories"]}
        imgs = {i["id"]: i for i in d["images"]}
        for a in d["annotations"]:
            im = imgs[a["image_id"]]
            iid = Path(im["file_name"]).stem
            images[iid] = {"file": im["file_name"], "width": im["width"], "height": im["height"]}
            x, y, w, h = a["bbox"]
            at = a.get("attributes") or {}
            dets.append({"id": f"det-{FAMILY_PREFIX[fam]}-{a['id']:05d}", "image_id": iid, "family": fam, "class": cats[a["category_id"]],
                         "subtype": at.get("tipo"), "score": round(float(a.get("score", 0.0)), 3),
                         "bbox": [round(x, 1), round(y, 1), round(x + w, 1), round(y + h, 1)],
                         "extra": {k: a[k] for k in ("p_papeleira", "p_simples", "p_decorativo", "p_rejeitar", "p_router", "score_tipo", "estado_desbotamento", "estado_desbotamento_idx", "estado_obstrucao", "estado_obstrucao_idx", "estado_motivos") if k in a}})
    return dets, images


def link_detections(dets, obs_by_elem, dropped_pap):
    """Liga cada deteção COCO ao elemento do catálogo (por imagem + caixa) e explica as que ficaram de fora."""
    idx = defaultdict(list)                                                    # image_id -> [(bbox, classe, elem_id, obs)]
    for eid, lst in obs_by_elem.items():
        for o in lst:
            idx[o["image_id"]].append((o["bbox"], o.get("cls"), eid, o))
    pap = defaultdict(list)
    for d in dropped_pap:
        pap[d["image_id"]].append(d["bbox"])
    close = lambda a, b: all(abs(p - q) <= BBOX_TOL for p, q in zip(a, b))      # noqa: E731
    claimed: set[int] = set()                                                   # cada observação liga a UMA deteção (a mesma caixa pode ter 2 previsões)
    for d in dets:
        d.update(element_id=None, in_catalog=False, excluded_reason=None, suggested_class=None, azimuth=None, est_distance=None)
        for bb, cls, eid, o in idx.get(d["image_id"], []):
            if id(o) not in claimed and cls == d["class"] and close(bb, d["bbox"]):
                claimed.add(id(o))
                d.update(element_id=eid, in_catalog=True, azimuth=o.get("az"), est_distance=o.get("dist_m"))
                break
        else:
            if any(close(bb, d["bbox"]) for bb in pap.get(d["image_id"], [])):
                d.update(excluded_reason="papeleira_filter", suggested_class="papeleira")
            else:
                d.update(excluded_reason="catalog_filter")           # distância estimada > 40 m ou outro filtro do pipeline
    return dets


def make_crop(src: Path, bbox, dest: Path, pad: float = 0.15, side: int = 192) -> None:
    from PIL import Image
    im = Image.open(src).convert("RGB")
    x1, y1, x2, y2 = bbox
    px, py = pad * (x2 - x1), pad * (y2 - y1)
    c = im.crop((int(max(0, x1 - px)), int(max(0, y1 - py)), int(min(im.width, x2 + px)), int(min(im.height, y2 + py))))
    c.thumbnail((side, side))
    c.save(dest, quality=85)


# ------------------------------------------------------------------ v1.2: deduplicação v2 e sinal do CLIP
def load_v2(base: Path):
    """Saída de scripts/deduplicar.py (grupos com p, posições recalculadas, pares pontuados) ou None."""
    d = base / "dedup_v2"
    if not (d / "grupos.json").exists() or not (d / "elementos.geojson").exists():
        return None
    g = json.loads((d / "grupos.json").read_text(encoding="utf-8"))
    el = {f["properties"]["id"]: f for f in json.loads((d / "elementos.geojson").read_text(encoding="utf-8"))["features"]}
    pares = [json.loads(l) for l in (d / "pares_p.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()] if (d / "pares_p.jsonl").exists() else []
    return {"grupos": g, "elementos": el, "pares": pares}


def load_clip(city: str):
    """Tabelas do verificador CLIP (só SINALIZA; nunca remove) -> {(image_id, família): [(bbox, estado, p_rejeitar, seria_removido)]}. Âmbito: sinais padrão e contentores (caixas elétricas)."""
    out = defaultdict(list)
    for fam, fn in (("sinal", f"{city}_sinais.json"), ("residuos", f"{city}_ecopontos.json")):
        p = ROOT / "data" / "clip_verif" / fn
        if p.exists():
            for r in json.loads(p.read_text(encoding="utf-8")):
                if r["estado"] != "fora_de_ambito":
                    out[(Path(r["file"]).stem, fam)].append((r["bbox"], r["estado"], r["p_rejeitar"], bool(r.get("seria_removido"))))
    return out


def attach_clip(dets, clip):
    close = lambda a, b: all(abs(p - q) <= BBOX_TOL for p, q in zip(a, b))      # noqa: E731
    for d in dets:
        for bb, est, pr, sr in clip.get((d["image_id"], d["family"]), []):
            if close(bb, d["bbox"]):
                d["extra"]["clip"] = {"state": est, "p_reject": round(float(pr), 3), "would_remove": sr}
                break


# ------------------------------------------------------------------ v1.3: tipo dos caixotes, ilhas de reciclagem, inventário único
def load_tipos(base: Path):
    """data/catalog/<cidade>/residuos_tipos.json (scripts/tipar_residuos_catalogo.py): tipo SUGERIDO por caixa de contentor/subterrâneo ('<imagem>|x1,y1,x2,y2')."""
    f = base / "residuos_tipos.json"
    return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}


def attach_tipos(dets, tipos):
    for d in dets:
        if d["family"] == "residuos" and d["class"] in ("contentor", "subterraneo"):
            k = f"{d['image_id']}|{d['bbox'][0]},{d['bbox'][1]},{d['bbox'][2]},{d['bbox'][3]}"
            if k in tipos:
                v = tipos[k]
                d["extra"]["fluxo"] = {"tipo": v["tipo"], "p_tipo": v["p_tipo"], "segundo": v["segundo"], "p_segundo": v["p_segundo"], "fonte": "modelo", "modelo": v.get("modelo")}


def tipo_do_elemento(props: dict, by_id: dict) -> None:
    """Resíduos: `subclass` = tipo (indiferenciado | papel | embalagens | vidro) SUGERIDO pelo modelo para a melhor deteção do elemento que tenha tipo (como nos sinais, em que `subclass` é o tipo).
    `subclass_source` = "modelo" (nunca validado: a interface mostra «sugestão» até um técnico corrigir) e `subclass_p` = probabilidade do tipo. Sem tipo em nenhuma observação: fica None."""
    if props.get("family") != "residuos":
        return
    ordem = [props["best_detection_id"]] + [o["detection_id"] for o in props["observations"]]
    for did in ordem:
        fl = (by_id[did].get("extra") or {}).get("fluxo") if did in by_id else None
        if fl and fl.get("tipo"):
            props["subclass"], props["subclass_source"], props["subclass_p"] = fl["tipo"], fl.get("fonte", "modelo"), fl.get("p_tipo")
            return
    props["subclass"], props["subclass_source"], props["subclass_p"] = None, None, None


def calibrar(p: float, lim: dict | None) -> float:
    """p -> confiança calibrada (logística de models/dedup/limiares.json); sem calibração, o próprio p."""
    c = (lim or {}).get("logistica")
    if not c:
        return round(float(p), 3)
    q = min(max(float(p), 1e-3), 1 - 1e-3)
    return round(1 / (1 + math.exp(-(c["a"] * math.log(q / (1 - q)) + c["b"]))), 3)


GRUPO_LIM = {"sinal": "sinais", "residuos": "contentores", "mobiliario": "bancos", "iluminacao": "luz"}


def circle(lat: float, lon: float, r: float, n: int = 24):
    dlat = r / 111320.0
    dlon = r / (111320.0 * math.cos(math.radians(lat)))
    pts = [[round(lon + dlon * math.cos(2 * math.pi * k / n), 7), round(lat + dlat * math.sin(2 * math.pi * k / n), 7)] for k in range(n)]
    return {"type": "Polygon", "coordinates": [pts + [pts[0]]]}


def build_unicos(feats, dup_groups, by_id, metas):
    """Inventário ÚNICO: aplica as fusões AUTOMÁTICAS (grupos `provavel` com auto_merge) e deixa o resto igual. Os elementos absorvidos continuam em `elementos.geojson` com `merged_into`.
    O elemento que fica é `suggested_keep`; observações = união (da melhor para a pior); posição = a fundida (se for fiável); confiança = 1 - prod(1 - c); classe do ecoponto por voto de pontuação; n_units = máximo."""
    import copy
    por_id = {f["properties"]["id"]: f for f in feats}
    absorvidos = {}
    unicos = []
    auto = [g for g in dup_groups if g.get("auto_merge")]
    for g in auto:
        keep = g["suggested_keep"]
        for e in g["members"]:
            if e != keep:
                absorvidos[e] = keep
    for f in feats:
        e = f["properties"]["id"]
        if e in absorvidos:
            continue
        nf = copy.deepcopy(f)
        nf["properties"].update(auto_merged=False, merged_from=None)
        unicos.append(nf)
    idx = {f["properties"]["id"]: f for f in unicos}
    for g in auto:
        keep = g["suggested_keep"]
        nf = idx[keep]; p = nf["properties"]
        mem = [por_id[e]["properties"] for e in g["members"] if e in por_id]
        obs = sorted({o["detection_id"]: o for m in mem for o in m["observations"]}.values(), key=lambda o: -o["quality"])
        obs = [{**o, "rank": r + 1} for r, o in enumerate(obs)]
        p["observations"], p["best_detection_id"] = obs, obs[0]["detection_id"]
        imgs = {o["image_id"] for o in obs}
        p["n_views"] = len({(metas.get(i, {}).get("extra") or {}).get("pano_id") or i for i in imgs})
        c = 1.0
        for m in mem:
            c *= 1 - min(max(m["confidence"], 0.0), 0.999)
        p["confidence"] = round(min(1 - c, 0.999), 3)
        if p["family"] == "residuos":
            soma = defaultdict(float)
            for o in obs:
                soma[by_id[o["detection_id"]]["class"]] += o["score"]
            p["class"] = max(soma, key=soma.get)
            p["n_units"] = max((m.get("n_units") or 1) for m in mem)
        mp = g.get("merged_position") or {}
        if mp.get("lat") is not None and (mp.get("metodo") == "triangulada" or (mp.get("sigma_m") or 99) <= 15):
            nf["geometry"] = {"type": "Point", "coordinates": [mp["lon"], mp["lat"]]}
            p["position_method"], p["position_sigma_m"] = ("fundida_" + mp["metodo"]), (round(mp["sigma_m"], 1) if mp.get("sigma_m") is not None else None)
            p["position_reliable"] = bool(mp["metodo"] == "triangulada" or p["position_reliable"])
        p["position_previous"] = p.get("position_previous")
        cs = [m.get("clip_suspect") for m in mem]
        p["clip_suspect"] = True if any(x is True for x in cs) else (False if any(x is False for x in cs) else None)
        p.update(auto_merged=True, merged_from=sorted(g["members"]), duplicate_group_id=g["id"], duplicate_level="provavel", duplicate_possible_group_id=None)
    return unicos, absorvidos


def build_ilhas(unicos, by_id, sem_imagens, max_imagens=12):
    """Uma ILHA de reciclagem por elemento de resíduos com >= 1 contentor/subterrâneo (a papeleira não forma ilha). Zona = círculo à volta da posição (raio por incerteza). Cada imagem lista as caixas com o tipo SUGERIDO
    (o técnico corrige com `fluxo_corrections`). Composição estimada = por tipo, o máximo de caixas desse tipo vistas numa só imagem (a mesma lógica do n_units)."""
    ilhas = []
    for f in unicos:
        p = f["properties"]
        if p["family"] != "residuos" or p["class"] not in ("contentor", "subterraneo"):
            continue
        por_img = defaultdict(list)
        for o in p["observations"]:
            d = by_id[o["detection_id"]]
            if d["class"] not in ("contentor", "subterraneo"):
                continue
            fx = d["extra"].get("fluxo") or {}
            por_img[d["image_id"]].append({"detection_id": d["id"], "bbox": d["bbox"], "class": d["class"], "score": d["score"], "fluxo_sugerido": fx.get("tipo"), "p_tipo": fx.get("p_tipo"),
                                           "segunda_opcao": fx.get("segundo"), "fluxo_corrigido": None, "crop_path": d.get("crop_path")})
        if not por_img:
            continue
        comp = defaultdict(int); ps = []
        for L in por_img.values():
            c = Counter(b["fluxo_sugerido"] for b in L if b["fluxo_sugerido"])
            for k, v in c.items():
                comp[k] = max(comp[k], v)
            ps += [b["p_tipo"] for b in L if b["p_tipo"] is not None]
        lon, lat = f["geometry"]["coordinates"]
        sg = p.get("position_sigma_m")
        r = round(min(max(6.0, 2 * sg), 25.0) if sg else 6.0, 1)
        ordem = sorted(por_img, key=lambda i: (-len(por_img[i]), i))[:max_imagens]
        ilhas.append({"id": "ilha-" + p["id"], "element_id": p["id"], "center": {"lat": lat, "lon": lon}, "radius_m": r, "zona": circle(lat, lon, r),
                      "n_unidades": p.get("n_units") or max(len(L) for L in por_img.values()), "composicao_estimada": dict(sorted(comp.items())), "confianca_tipo_media": round(sum(ps) / len(ps), 3) if ps else None,
                      "tipo_revisto_pelo_tecnico": False, "n_imagens": len(por_img),
                      "imagens": [{"image_id": i, "path": None if sem_imagens else f"imagens/{i}.jpg", "n_caixas": len(por_img[i]), "caixas": por_img[i]} for i in ordem]})
    return ilhas


# ------------------------------------------------------------------ duplicados
def duplicate_groups(feats, elem_images, radii):
    """Pares de elementos da mesma família a <= raio (posição ajustada), que NÃO partilham imagem (duas caixas na mesma imagem
    são, em regra, objetos distintos). Sinais: só se tiverem o mesmo subtipo. Componentes ligados = grupos."""
    pos = {f["properties"]["id"]: to_m(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) for f in feats}
    by_fam = defaultdict(list)
    for f in feats:
        by_fam[f["properties"]["family"]].append(f["properties"])
    parent: dict[str, str] = {}

    def find(a):
        while parent.setdefault(a, a) != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    pairs = []
    for fam, props in by_fam.items():
        r = radii.get(fam, 6.0)
        P = np.array([pos[p["id"]] for p in props])
        for i in range(len(props)):
            d = np.hypot(*(P[i + 1:] - P[i]).T) if i + 1 < len(props) else np.array([])
            for k in np.where(d <= r)[0]:
                a, b = props[i], props[i + 1 + k]
                if fam == "sinal" and (a.get("subclass") or "") != (b.get("subclass") or ""):
                    continue
                shared = bool(elem_images[a["id"]] & elem_images[b["id"]])
                pairs.append({"a": a["id"], "b": b["id"], "family": fam, "distance_m": round(float(d[k]), 1),
                              "same_class": a["class"] == b["class"], "shared_image": shared})
                if not shared:
                    parent[find(a["id"])] = find(b["id"])
    groups: dict[str, list[str]] = defaultdict(list)
    for eid in list(parent):
        groups[find(eid)].append(eid)
    return pairs, [m for m in groups.values() if len(m) > 1]


# ------------------------------------------------------------------ esquemas JSON
def schemas() -> dict[str, dict]:
    num, s, i = {"type": "number"}, {"type": "string"}, {"type": "integer"}
    nul = lambda t: {"type": [t, "null"]}                                      # noqa: E731
    bbox = {"type": "array", "items": num, "minItems": 4, "maxItems": 4}
    obs = {"type": "object", "required": ["detection_id", "image_id", "bbox", "score", "quality", "rank"],
           "properties": {"detection_id": s, "image_id": s, "bbox": bbox, "score": num, "quality": num, "rank": i}}
    element = {"type": "object", "required": ["type", "geometry", "properties"], "properties": {
        "type": {"const": "Feature"},
        "geometry": {"type": "object", "required": ["type", "coordinates"], "properties": {"type": {"const": "Point"}, "coordinates": {"type": "array", "items": num, "minItems": 2, "maxItems": 2}}},
        "properties": {"type": "object", "required": ["id", "family", "class", "confidence", "n_views", "status", "geo_method", "position_reliable",
                                                       "position_original", "observations", "best_detection_id", "duplicate_group_id"],
                       "properties": {"id": s, "family": {"enum": ["sinal", "iluminacao", "residuos", "mobiliario"]}, "class": s, "subclass": nul("string"),
                                      "confidence": num, "n_views": i, "status": {"enum": ["auto", "validado", "corrigido", "rejeitado"]},
                                      "geo_method": s, "geo_residual": nul("number"), "position_reliable": {"type": "boolean"},
                                      "position_original": {"type": "object", "required": ["lat", "lon"], "properties": {"lat": num, "lon": num}},
                                      "road_adjustment_m": nul("number"), "road_adjustment_method": nul("string"), "n_units": nul("integer"),
                                      "osm_ref_match": nul("boolean"), "observations": {"type": "array", "items": obs, "minItems": 1},
                                      "best_detection_id": s, "duplicate_group_id": nul("string"),
                                      # --- 1.2 (todos opcionais)
                                      "position_previous": {"type": ["object", "null"], "properties": {"lat": num, "lon": num}}, "position_method": nul("string"), "position_sigma_m": nul("number"),
                                      "duplicate_level": {"enum": [None, "provavel", "possivel"]}, "duplicate_possible_group_id": nul("string"),
                                      "clip_suspect": nul("boolean"), "clip": {"type": ["object", "null"]},
                                      # --- 1.3 (opcionais)
                                      "subclass_source": nul("string"), "subclass_p": nul("number"),
                                      "ilha_id": nul("string"), "merged_into": nul("string"), "auto_merged": {"type": "boolean"}, "merged_from": {"type": ["array", "null"], "items": s}}}}}
    det = {"type": "object", "required": ["id", "image_id", "family", "class", "score", "bbox", "quality", "element_id", "in_catalog", "excluded_reason", "crop_path"],
           "properties": {"id": s, "image_id": s, "family": s, "class": s, "subtype": nul("string"), "score": num, "bbox": bbox, "quality": num,
                          "azimuth": nul("number"), "est_distance": nul("number"), "element_id": nul("string"), "in_catalog": {"type": "boolean"},
                          "excluded_reason": {"enum": [None, "papeleira_filter", "catalog_filter"]}, "suggested_class": nul("string"),
                          "crop_path": nul("string"), "extra": {"type": "object"}}}
    img = {"type": "object", "required": ["id", "source", "lat", "lon", "heading", "width", "height", "license", "attribution", "path"],
           "properties": {"id": s, "source": s, "source_image_id": s, "lat": num, "lon": num, "heading": num, "hfov_deg": nul("number"), "camera_type": s,
                          "captured_at": nul("string"), "width": i, "height": i, "license": s, "attribution": s, "path": nul("string"),
                          "pano_id": nul("string"), "yaw": nul("number")}}
    dup = {"type": "object", "required": ["groups", "pairs"], "properties": {
        "groups": {"type": "array", "items": {"type": "object", "required": ["id", "family", "members", "suggested_keep"],
                                              "properties": {"id": s, "family": s, "members": {"type": "array", "items": s, "minItems": 2}, "suggested_keep": s, "max_distance_m": num,
                                                            # --- 1.2 (opcionais)
                                                            "level": {"enum": ["provavel", "possivel"]}, "recommendation": s, "p_mean_link": num, "p_min_edge": nul("number"),
                                                            "auto_merge": {"type": "boolean"}, "merged_position": {"type": "object"}, "evidence": s, "types": {"type": "object"}, "classes": {"type": "object"},
                                                            "confidence": num, "auto_threshold_p": nul("number")}}},
        "pairs": {"type": "array", "items": {"type": "object", "required": ["a", "b", "distance_m", "shared_image"], "properties": {"a": s, "b": s, "distance_m": num, "same_class": {"type": "boolean"}, "shared_image": {"type": "boolean"}, "p": num, "confidence": num}}}}}
    decisions = {"type": "object", "required": ["schema_version", "decisions"], "properties": {"schema_version": s, "decisions": {"type": "array", "items": {
        "type": "object", "required": ["element_id", "decided_by", "decided_at"], "properties": {
            "element_id": s, "decided_by": s, "decided_at": s, "status": {"enum": ["validado", "corrigido", "rejeitado"]},
            "best_detection_id": s, "merge_into": s, "split_detection_ids": {"type": "array", "items": s}, "class": s, "note": s,
            "group_id": s, "group_decision": {"enum": ["merge", "not_duplicate"]},
            "ilha_id": s, "fluxo_corrections": {"type": "array", "items": {"type": "object", "required": ["detection_id", "fluxo"], "properties": {
                "detection_id": s, "fluxo": {"enum": ["indiferenciado", "papel", "embalagens", "vidro", "organicos", "oleo", "pilhas", "desconhecido"]}}}},
            "n_unidades": i}}}}}
    colecao = {"type": "object", "required": ["type", "features"], "properties": {"type": {"const": "FeatureCollection"}, "features": {"type": "array", "items": element}}}
    caixa_ilha = {"type": "object", "required": ["detection_id", "bbox", "class"], "properties": {"detection_id": s, "bbox": bbox, "class": s, "score": num, "fluxo_sugerido": nul("string"), "p_tipo": nul("number"),
                                                                                              "segunda_opcao": nul("string"), "fluxo_corrigido": nul("string"), "crop_path": nul("string")}}
    ilha = {"type": "object", "required": ["id", "element_id", "center", "radius_m", "zona", "n_unidades", "composicao_estimada", "imagens"], "properties": {
        "id": s, "element_id": s, "center": {"type": "object", "required": ["lat", "lon"], "properties": {"lat": num, "lon": num}}, "radius_m": num, "zona": {"type": "object"},
        "n_unidades": i, "composicao_estimada": {"type": "object"}, "confianca_tipo_media": nul("number"), "tipo_revisto_pelo_tecnico": {"type": "boolean"}, "n_imagens": i,
        "imagens": {"type": "array", "items": {"type": "object", "required": ["image_id", "n_caixas", "caixas"], "properties": {"image_id": s, "path": nul("string"), "n_caixas": i, "caixas": {"type": "array", "items": caixa_ilha}}}}}}
    return {"elementos": colecao, "elementos_unicos": colecao, "ilhas": {"type": "array", "items": ilha},
            "deteccoes": {"type": "array", "items": det}, "imagens": {"type": "array", "items": img}, "duplicados": dup, "decisoes": decisions}


# ------------------------------------------------------------------ README
# Notas de cobertura: as de Aveiro descrevem o histórico DESSE catálogo (1824 vistas iniciais); uma zona gerada pela pipeline automática cobre todas as famílias em todas as vistas admitidas.
NOTAS_COBERTURA = {
    "aveiro": {"nota_sinais": "- **Mais sinais**: os panoramas novos de Aveiro foram passados pelo detetor de sinais (os ids `det-sn-` antigos não mudaram). Iluminação e resíduos continuam a cobrir só as 1824 vistas de antes.",
               "nota_cobertura": "- **Cobertura:** a iluminação continua a cobrir só as 1824 vistas iniciais neste ficheiro; as previsões de luz e de bancos para todas as vistas de Aveiro existem (`data/inference/`) mas ainda não entraram no catálogo."},
    "zona": {"nota_sinais": "- **Cobertura dos sinais**: todos os detetores correram sobre todas as vistas admitidas da zona (pipeline automática, `urban_mobile_search zona run`).",
             "nota_cobertura": "- **Cobertura:** sinais, resíduos, iluminação e bancos cobrem as mesmas vistas admitidas da zona; ver `manifest.json` e `estado.json` da zona para as versões dos modelos."},
}
README = """# Entrega de dados: {city} ({date})

Pacote de entrega de uma zona. Esquema versão **{ver}**. Gerado por `scripts/exportar_entrega.py`; commit `{commit}`.
Quando houver previsões novas ou anotações validadas, o ficheiro é regenerado com o **mesmo esquema** (e mais tarde servido por API com
as mesmas formas, ver o fim).

## Ficheiros

| Ficheiro | O que é |
|---|---|
| `elementos.geojson` | FeatureCollection de **pontos** (WGS84, `[lon, lat]`): um por elemento candidato. É o que vai no mapa. |
| `elementos_unicos.geojson` | **O inventário único** (1.3): igual a `elementos.geojson` mas com as **fusões automáticas** já aplicadas. Se a interface quer mostrar «quantos objetos há», é este. |
| `ilhas.json` | **Ilhas de reciclagem** (1.3): uma por ecoponto, com a zona, os caixotes, os tipos sugeridos e as imagens. O técnico corrige o tipo. |
| `deteccoes.json` | **Todas** as previsões (uma por caixa e imagem). {n_det} no total. |
| `imagens.json` | As imagens referenciadas: posição da câmara, rumo, campo de visão, licença e atribuição. |
| `duplicados.json` | Grupos de elementos que **podem ser o mesmo objeto**. É uma sugestão. |
| `imagens/<image_id>.jpg` | Imagens **anonimizadas** (rostos e matrículas desfocados). Opcionais, para o técnico ver o contexto. |
| `recortes/<detection_id>.jpg` | Recorte de cada deteção (com 15% de margem, lado máx. 192 px), para comparar depressa. |
| `schema/*.schema.json` | JSON Schema de cada ficheiro (os ficheiros foram validados contra eles). |
| `decisoes.exemplo.json` | Formato para **devolver** as escolhas do técnico. |
| `manifest.json` | Versão, data, contagens, parâmetros e sha256 de cada ficheiro. |
| `ATRIBUICOES.md` | Licenças e atribuições obrigatórias. |

## Como se liga tudo

```
element (elementos.geojson)  1 ──< N  detection (deteccoes.json)  N >── 1  image (imagens.json)
     properties.observations[]  = as deteções que formam o elemento (mesmos ids), da melhor para a pior
     properties.best_detection_id  = a melhor, SUGERIDA (o técnico pode escolher outra)
     properties.duplicate_group_id = grupo em duplicados.json (ou null)
```

- **Elemento** = um objeto que o sistema acha que existe na rua. Pode ter várias observações (o mesmo objeto visto em várias imagens).
- **Deteção** = uma caixa numa imagem. `in_catalog=false` quer dizer que **não entrou em nenhum elemento**; `excluded_reason` diz porquê
  (`papeleira_filter`: o filtro acha que é uma papeleira, ver `suggested_class`; `catalog_filter`: distância estimada > 40 m ou outro filtro do pipeline).
- `bbox` é `[x1, y1, x2, y2]` em **píxeis da imagem original** (tamanho em `imagens.json`: `width`, `height`).
- `class` (elemento): `sinal` | `poste_luz` | `candeeiro` | `contentor` | `subterraneo` | `banco` (família `mobiliario`, nova na versão 1.1). `subclass` do sinal é o tipo (ex. `regulatory_stop`).
  Nas deteções, `class` é a família do sinal (`regulamentacao`, `perigo`, …) e `subtype` o tipo.

## Novidades da versão 1.1 (aditivas: o que já lias continua igual)

- **Família `mobiliario`, classe `banco`**: detetor RF-DETR Medium pré-treinado em COCO (pesos oficiais Roboflow, sem treino nosso); prefixo de ids `det-bc-`, elementos `mob-<zona>-NNNNN`.
{nota_sinais}

## Novidades da versão 1.3 (aditivas: o que já lias continua igual)

- **Ilhas de reciclagem** (`ilhas.json`): cada elemento de resíduos com pelo menos um contentor ou subterrâneo dá uma **ilha** (a papeleira não forma ilha). Tem `center`, `radius_m` e `zona` (polígono GeoJSON, aproximado: raio de 6 m, ou 2× a incerteza da posição), `n_unidades`, `composicao_estimada` (por tipo, o máximo de caixotes desse tipo vistos numa só imagem) e `imagens`: as imagens da ilha (até 12, as que mostram mais caixotes) com **cada caixa e o tipo sugerido** (`fluxo_sugerido`, `p_tipo`, `segunda_opcao`).
  **O técnico corrige o tipo** devolvendo `fluxo_corrections` em `decisoes` (`detection_id` + `fluxo`) e, opcionalmente, `n_unidades`. O tipo vem de um classificador que acerta cerca de **40 %** em recortes novos do Porto (tende a dar `papel` ou `embalagens` a caixotes cinzentos): **mostra-o como sugestão** e destaca as de `p_tipo` baixo. Os tipos `fluxo` também estão em `deteccoes[].extra.fluxo`.
- **Inventário único** (`elementos_unicos.geojson`): aplica as **fusões automáticas**, só nos grupos `provavel` de **sinais**, **contentores** (como ilha) e **luz**, cuja confiança foi medida na ronda 4 (sinais 79 de 80 certos, contentores/ilha 34 de 35). O elemento que fica é `suggested_keep`; leva a união das observações e `merged_from` (os ids fundidos, para **desfazer**). Em `elementos.geojson` os absorvidos mantêm-se, com `merged_into`. **Bancos nunca se fundem sozinhos** (poucos casos medidos). **A luz funde-se ao mesmo limiar por decisão do utilizador**, com muito pouca evidência medida (6 de 6 na ronda 4): mostra estas fusões como as menos provadas e deixa desfazer.
- **Confiança e limiar automático** (`duplicados.json`): cada grupo tem `confidence` (probabilidade calibrada de serem o mesmo objeto; nos contentores, **a mesma ilha**) e `auto_threshold_p` (limiar de p médio de ligação a partir do qual se funde sozinho: 0,85 para sinais e contentores; `null` onde não há fusão automática). Os pares também têm `confidence`. **Mostra a `confidence` ao técnico** junto de cada sugestão, e deixa **desfazer** qualquer fusão automática.

## Novidades da versão 1.2 (aditivas: tudo o que já lias continua igual; os campos novos são opcionais)

- **Duplicados recomendados** (`duplicados.json`): cada grupo traz agora `level` (`provavel`: média de ligação >= 0,85; `possivel`: >= 0,5), `recommendation` (texto para mostrar),
  `p_mean_link` / `p_min_edge` (pontuação p(mesmo objeto), 0 a 1), `evidence` (o que se mediu para essa família), `merged_position` (posição se fundir, com `sigma_m`) e `auto_merge=false`:
  **nada se funde sozinho**. Os pares (`pairs`) têm `p`. Cada elemento tem `duplicate_group_id` (o grupo mais específico), `duplicate_level` e `duplicate_possible_group_id` (o grupo `possivel` que o contém).
  Método: ligação média com restrições (elementos da mesma imagem nunca se juntam; sinais: só a mesma família e o mesmo tipo, ou `desconhecido`), em vez de componentes ligados (já não há cadeias de 17).
  **Cuidado ao mostrar:** o p foi medido em pares de observações (AUC 0,90 em pares novos); ao nível do elemento ainda NÃO foi validado. Para sinais, na ronda 3, p >= 0,85 acertou 25 de 25; contentores 10 de 11; bancos e luz com poucos casos.
  Mostra o grau (`provavel`/`possivel`) e deixa sempre juntar e separar à mão.
- **Posição recalculada** (`geometry`): nos elementos de vista única a profundidade monocular parece sobrestimar a distância (desvio mediano de -0,6 da distância face à triangulação); a posição passou a usar a distância encolhida por k = 0,4.
  `position_method` (`triangulada_catalogo` | `vista_unica_k`), `position_sigma_m` (incerteza em metros, só nos de vista única) e `position_previous` (a posição que tinha na 1.1, para comparar). `road_adjustment_*` deixou de se aplicar.
  **Por confirmar com pontos de GPS no terreno**: contra o OSM, o erro mediano dos de vista única desceu de 12,6 para 6,3 m (15 pares), mas é uma amostra pequena.
- **Sinal do CLIP** (`clip_suspect`, `clip`; nas deteções `extra.clip`): `true` quando o melhor registo do elemento parece não ser o que o detetor diz (caixa elétrica no lugar de um contentor; objeto que não parece um sinal padrão) e uma segunda chave não o protege.
  `null` = fora de âmbito. **Só sinaliza, nunca remove.** Âmbito: sinais de regulamentação, perigo e informação; contentores e subterrâneos (só a confusão com caixas elétricas). **Não** se aplica a luz, bancos nem sinais de orientação/complementares. Os limiares ainda não foram calibrados com rótulos: mostrar como aviso, não como veredicto.
- **Decisões** (`decisoes`): campos opcionais `group_id` e `group_decision` (`merge` | `not_duplicate`) para devolver a decisão sobre um grupo recomendado; cada decisão serve de rótulo para recalibrar o p.
{nota_cobertura}
- **Tipo dos resíduos nos elementos** (novo, aditivo): em `elementos.geojson` e `elementos_unicos.geojson`, `subclass` dos contentores e subterrâneos passa a ser o **tipo sugerido** (`indiferenciado` | `papel` | `embalagens` | `vidro`), como nos sinais; `subclass_source` = `modelo` e `subclass_p` = probabilidade. É uma **sugestão** (o classificador acerta cerca de 40 % em recortes novos): mostrar como «sugestão» até o técnico corrigir (`fluxo_corrections` em `decisoes`). Até agora estava `null` nos elementos; o tipo só vinha em `deteccoes[].extra.fluxo` e em `ilhas[].composicao_estimada`.

## A melhor imagem

`quality` (0 a 1) = confiança × tamanho da caixa × centralidade × não estar cortada na margem × qualidade da imagem (do Mapillary).
Ordena as observações de cada elemento (`rank` 1 = melhor) e define `best_detection_id`. É uma **sugestão**: a escolha é do técnico.

## Duplicados

`duplicados.json` tem `groups` (elementos ligados) e `pairs` (cada par com `distance_m`, `same_class` e `shared_image`).
Entram na mesma família e a ≤ {radii} m (sinais: só do mesmo subtipo). Pares que **partilham imagem** (duas caixas diferentes na mesma
imagem) não formam grupo: em regra são objetos distintos. `suggested_keep` é o elemento com mais vistas e melhor qualidade.
**Nada foi fundido**: junta/separa na interface e devolve em `decisoes`. A posição tem erro de ~15 m, por isso há duplicados verdadeiros
que não aparecem (e grupos que não são). A interface deve deixar juntar e separar à mão.

## Fiabilidade da posição (avisa o utilizador)

- A posição (`geometry`) é a da **versão 1.2** (ver acima); a antiga está em `position_previous` e a original (sem ajuste à estrada) em `position_original`.
- `position_reliable=true` só nos elementos **triangulados** (≥2 câmaras). Os de vista única (`position_reliable=false`) têm erro típico de
  **~15 m** (medido contra o OSM). Mostrar com raio de incerteza ou marcar como "aproximado".
- `geo_residual` (m) é o resíduo da triangulação, quando existe.

## Devolver as decisões do técnico

Formato em `decisoes.exemplo.json` (schema em `schema/decisoes.schema.json`): por elemento, o `best_detection_id` escolhido, `merge_into`
(juntar a outro elemento), `split_detection_ids` (tirar estas deteções do elemento), `class` corrigida, `status` (`validado`,
`corrigido`, `rejeitado`), `decided_by`, `decided_at`. Corresponde a `PATCH /elements/{{id}}` + `edit_log` do `docs/Plano.md` §9.

## Imagens e licenças

- As imagens são do **Mapillary, CC BY-SA 4.0**: mostrar a atribuição de `imagens.json` (`attribution`) junto da imagem. Ver `ATRIBUICOES.md`.
- São as anonimizadas. A auditoria do desfoque ainda não foi feita: não as publiques fora do grupo.
- Caminhos **relativos** (`imagens/<id>.jpg`): serve a pasta onde quiseres.

## Exemplo (JavaScript)

```js
const els = await (await fetch('elementos.geojson')).json();
const dets = Object.fromEntries((await (await fetch('deteccoes.json')).json()).map(d => [d.id, d]));
const el = els.features[0].properties;
const best = dets[el.best_detection_id];            // {{image_id, bbox, crop_path, ...}}
// imagem: 'imagens/' + best.image_id + '.jpg'   recorte: best.crop_path
```

## Validar

```bash
python -c "import json,jsonschema; jsonschema.validate(json.load(open('elementos.geojson')), json.load(open('schema/elementos.schema.json')))"
```

## API (próximo passo)

A API devolverá as mesmas formas: `GET /elements` → `elementos.geojson`, `GET /elements/{{id}}` → uma feature,
`GET /detections?element_id=`, `GET /images/{{id}}`, `PATCH /elements/{{id}}` ← uma entrada de `decisoes`. Faz o template com estes ficheiros
e a troca para a API não muda o formato.

## Números

{counts}
"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?", default="aveiro")
    ap.add_argument("--out", type=Path, default=ROOT / "Entrega_C")
    ap.add_argument("--dup-radius", type=float, help="raio (m) de duplicados para TODAS as famílias (omissão: sinal 5, luz 8, resíduos 8)")
    ap.add_argument("--sem-imagens", action="store_true", help="não copiar as imagens completas (só os recortes)")
    ap.add_argument("--caminhos-completos", action="store_true", help="com --sem-imagens, mantém os caminhos `imagens/<id>.jpg` nos JSON (para um DELTA: quem recebe já tem as imagens); images_included continua False")
    ap.add_argument("--ignorar-sinais", action="store_true", help="ignora por completo as categorias de sinais de configs/sinais_ignorados.json (orientação e outros, painel de reboque, baliza de curva, painel de veículos pesados): "
                    "não entram no catálogo; ids dos restantes inalterados; deteções com excluded_reason=catalog_filter e extra.excluded_detail; lista em removidos.json")
    ap.add_argument("--remover-sinais-abaixo", type=float, default=None, metavar="SCORE",
                    help="sinais cuja MELHOR deteção tem score < SCORE não entram (ids dos restantes inalterados; as deteções ficam com excluded_reason=catalog_filter e extra.excluded_detail; "
                         "fusões automáticas que perdem um membro deixam de ser automáticas). Lista em removidos_baixa_confianca.json")
    a = ap.parse_args()

    base = ROOT / "data" / "catalog" / a.city
    cat_p = base / "catalog_ajustado.geojson"
    if not cat_p.exists():
        sys.exit(f"{cat_p} não existe: corre pipeline/ajustar_estrada.py {a.city}")
    cat = json.loads(cat_p.read_text(encoding="utf-8"))
    obs_all = json.loads((base / "observacoes.json").read_text(encoding="utf-8"))
    dropped = json.loads((base / "descartados_papeleiras.json").read_text(encoding="utf-8")) if (base / "descartados_papeleiras.json").exists() else []
    metas = {}
    for line in (ROOT / "data" / "raw" / f"{a.city}_vistas" / "meta.jsonl").read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        metas[m["source_image_id"]] = m
    ok_anon = anon_names()
    radii = {k: a.dup_radius for k in DUP_RADIUS} if a.dup_radius else DUP_RADIUS

    dets, imgs_coco = load_coco_all(a.city)
    dets = link_detections(dets, obs_all, dropped)
    by_id = {d["id"]: d for d in dets}
    bad = sorted({d["image_id"] for d in dets if f"{d['image_id']}.jpg" not in ok_anon})
    if bad:
        sys.exit(f"{len(bad)} imagens sem versão anonimizada verificada (ex.: {bad[:3]}): corre privacy/anon_cache.py")

    # qualidade de cada deteção
    for d in dets:
        im = imgs_coco[d["image_id"]]
        d["quality"] = quality(d["score"], d["bbox"], (im["width"], im["height"]), (metas.get(d["image_id"], {}).get("extra") or {}).get("quality_score"))

    # elementos
    det_of_obs = defaultdict(dict)                                              # elem_id -> {(image_id, bbox tuple): det}
    for d in dets:
        if d["element_id"]:
            det_of_obs[d["element_id"]][d["id"]] = d
    IGN = json.loads((ROOT / "configs" / "sinais_ignorados.json").read_text(encoding="utf-8"))
    feats, elem_images, removidos = [], {}, {}
    for f in cat["features"]:
        p = f["properties"]
        eid = p["id"]
        members = sorted(det_of_obs.get(eid, {}).values(), key=lambda d: -d["quality"])
        if not members:
            print(f"  aviso: elemento {eid} sem deteções ligadas; ignorado")
            continue
        motivo = None
        if p["family"] == "sinal":
            if a.ignorar_sinais and (members[0]["class"] in IGN["grupos"] or p.get("subclass") in IGN["tipos"]):
                nome = IGN["nomes_pt"].get(members[0]["class"] if members[0]["class"] in IGN["grupos"] else p.get("subclass"), "categoria ignorada")
                motivo = f"categoria_ignorada: {nome}"
            elif a.remover_sinais_abaixo is not None and max(d["score"] for d in members) < a.remover_sinais_abaixo:
                motivo = f"baixa_confianca: melhor deteção < {a.remover_sinais_abaixo:g}"
        if motivo:
            removidos[eid] = {"id": eid, "class": members[0]["class"], "subclass": p.get("subclass"), "best_score": max(d["score"] for d in members), "n_views": p["n_views"],
                              "detection_ids": sorted(d["id"] for d in members), "motivo": motivo}
            for d in members:                                                    # a deteção fica (mesmo id), mas deixa de estar no catálogo
                d.update(element_id=None, in_catalog=False, excluded_reason="catalog_filter")       # valor já previsto no esquema 1.3 (não se altera o contrato)
                d.setdefault("extra", {})["excluded_detail"] = motivo
            continue
        observations = [{"detection_id": d["id"], "image_id": d["image_id"], "bbox": d["bbox"], "score": d["score"], "quality": d["quality"], "rank": r + 1}
                        for r, d in enumerate(members)]
        elem_images[eid] = {d["image_id"] for d in members}
        lat0, lon0 = p["pos_original"]
        feats.append({"type": "Feature", "geometry": f["geometry"], "properties": {
            "id": eid, "family": p["family"], "class": p["class"], "subclass": p.get("subclass"), "confidence": p["confidence"], "n_views": p["n_views"],
            "status": p.get("status", "auto"), "geo_method": p["geo_method"], "geo_residual": p.get("geo_residual_m"),
            "position_reliable": p["geo_method"] == "triangulado", "position_original": {"lat": lat0, "lon": lon0},
            "road_adjustment_m": p.get("ajuste_m"), "road_adjustment_method": p.get("ajuste_metodo"), "n_units": p.get("n_unidades"),
            "osm_ref_match": p.get("ref_match"), "observations": observations, "best_detection_id": members[0]["id"], "duplicate_group_id": None}})

    # v1.3: tipo (fluxo) sugerido nos contentores e subterrâneos
    attach_tipos(dets, load_tipos(base))
    for f in feats:
        tipo_do_elemento(f["properties"], by_id)
    # v1.2: sinal do CLIP (só sinaliza)
    attach_clip(dets, load_clip(a.city))
    for f in feats:
        p = f["properties"]
        cl = [by_id[o["detection_id"]]["extra"].get("clip") for o in p["observations"]]
        chk = [c for c in cl if c]
        best = by_id[p["best_detection_id"]]["extra"].get("clip")
        p["clip_suspect"] = None if not chk else bool(best and best["state"] == "suspeito")
        p["clip"] = None if not chk else {"best_state": best["state"] if best else None, "n_suspect_obs": sum(c["state"] == "suspeito" for c in chk),
                                          "n_checked_obs": len(chk), "max_p_reject": max(c["p_reject"] for c in chk)}

    # v1.2: posição recalculada (σ) e duplicados recomendados com p (scripts/deduplicar.py); sem isso, mantém-se o método por raio da 1.1
    v2 = load_v2(base)
    f_lim = Path(os.environ.get("UMS_MODELS_DIR", ROOT / "models")) / "dedup" / "limiares.json"
    LIMITES = json.loads(f_lim.read_text(encoding="utf-8"))["grupos"] if f_lim.exists() else {}
    for f in feats:
        p = f["properties"]
        lon1, lat1 = f["geometry"]["coordinates"]
        p.update(position_previous={"lat": lat1, "lon": lon1}, position_method=None, position_sigma_m=None, duplicate_level=None, duplicate_possible_group_id=None,
                 ilha_id=None, merged_into=None, auto_merged=False, merged_from=None)
    if v2:
        for f in feats:
            p = f["properties"]
            e2 = v2["elementos"].get(p["id"])
            if e2:
                f["geometry"] = e2["geometry"]
                p["position_method"] = e2["properties"]["position_method_v2"]
                p["position_sigma_m"] = e2["properties"]["position_sigma_m"]
                p["road_adjustment_m"], p["road_adjustment_method"] = None, "removido_na_1.2"

    # duplicados
    if v2:
        ids_ok = {f["properties"]["id"] for f in feats}
        props = {f["properties"]["id"]: f["properties"] for f in feats}
        pos = {f["properties"]["id"]: to_m(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]) for f in feats}
        dup_groups = []
        for g in sorted(v2["grupos"]["grupos"], key=lambda g: g["grupo_id"]):
            mem = [e for e in g["elementos"] if e in ids_ok]
            if len(mem) < 2:
                continue
            perdeu = any(e in removidos for e in g["elementos"])              # perdeu um membro por baixa confiança: a posição fundida e a fusão automática deixam de valer
            if perdeu:
                g = {**g, "auto_merge": False, "posicao_fundida": {"metodo": "invalidada_por_remocao"},
                     "recomendacao": g["recomendacao"] + " [Um membro foi removido por baixa confiança: a fusão automática foi desfeita; confirmar à mão.]"}
            dup_groups.append({"id": g["grupo_id"], "family": g["familia"], "members": sorted(mem), "suggested_keep": g["manter_sugerido"] if g["manter_sugerido"] in mem else mem[0],
                               "max_distance_m": g["distancia_max_catalogo_m"], "level": g["nivel"], "recommendation": g["recomendacao"], "p_mean_link": g["p_medio_ligacao"],
                               "p_min_edge": g["p_min_aresta"], "auto_merge": bool(g.get("auto_merge")), "confidence": g.get("confianca", g["p_medio_ligacao"]), "auto_threshold_p": g.get("limiar_automatico_p"),
                               "merged_position": g["posicao_fundida"], "evidence": g["evidencia_da_familia"],
                               "types": g["tipos"], "classes": g["classes"]})
        for g in dup_groups:                                                    # o grupo PROVÁVEL (mais específico) manda no elemento; o POSSÍVEL fica em duplicate_possible_group_id
            for e in g["members"]:
                if g["level"] == "provavel":
                    props[e].update(duplicate_group_id=g["id"], duplicate_level="provavel")
                else:
                    props[e]["duplicate_possible_group_id"] = g["id"]
                    if props[e]["duplicate_group_id"] is None:
                        props[e].update(duplicate_group_id=g["id"], duplicate_level="possivel")
        pairs = []
        for r in v2["pares"]:
            if r["p"] >= 0.4 and r["a"] in ids_ok and r["b"] in ids_ok:
                pairs.append({"a": r["a"], "b": r["b"], "distance_m": round(float(np.hypot(*(pos[r["a"]] - pos[r["b"]]))), 1), "same_class": props[r["a"]]["class"] == props[r["b"]]["class"],
                              "shared_image": False, "p": r["p"], "confidence": calibrar(r["p"], LIMITES.get(GRUPO_LIM.get(props[r["a"]]["family"])))})
        gm = set()
        groups = []
    else:
        pairs, groups = duplicate_groups(feats, elem_images, radii)
        props = {f["properties"]["id"]: f["properties"] for f in feats}
        dup_groups = []
    for n, mem in enumerate(sorted(groups, key=lambda m: min(m)), 1):
        fam = props[mem[0]]["family"]
        gid = f"dup-{FAMILY_PREFIX[fam]}-{n:04d}"
        keep = max(mem, key=lambda e: (props[e]["n_views"], props[e]["observations"][0]["quality"]))
        for e in mem:
            props[e]["duplicate_group_id"] = gid
        mx = max((q["distance_m"] for q in pairs if q["a"] in mem and q["b"] in mem), default=0.0)
        dup_groups.append({"id": gid, "family": fam, "members": sorted(mem), "suggested_keep": keep, "max_distance_m": mx})
    if not v2:
        gm = {e for g in dup_groups for e in g["members"]}
        pairs = [q for q in pairs if q["a"] in gm or q["b"] in gm or q["shared_image"] is False]

    # v1.3: inventário único (fusões automáticas), ilhas de reciclagem e ligações nos elementos
    unicos, absorvidos = build_unicos(feats, dup_groups, by_id, metas) if v2 else ([__import__("copy").deepcopy(f) for f in feats], {})
    for f in unicos:
        tipo_do_elemento(f["properties"], by_id)
    ilhas = build_ilhas(unicos, by_id, a.sem_imagens and not a.caminhos_completos)
    ilha_de = {i["element_id"]: i["id"] for i in ilhas}
    for f in feats:
        e = f["properties"]["id"]
        f["properties"]["merged_into"] = absorvidos.get(e)
        f["properties"]["ilha_id"] = ilha_de.get(absorvidos.get(e, e))
    for f in unicos:
        f["properties"]["ilha_id"] = ilha_de.get(f["properties"]["id"])

    # imagens (todas as referenciadas por alguma deteção)
    used_imgs = sorted({d["image_id"] for d in dets})
    images = []
    for iid in used_imgs:
        m, c = metas[iid], imgs_coco[iid]
        ex = m.get("extra") or {}
        images.append({"id": iid, "source": m["source"], "source_image_id": m["source_image_id"], "lat": m["lat"], "lon": m["lon"], "heading": m["heading"],
                       "hfov_deg": m.get("hfov_deg"), "camera_type": m.get("camera_type", "perspective"), "captured_at": iso(m.get("captured_at")),
                       "width": c["width"], "height": c["height"], "license": m["license"], "attribution": m["attribution"],
                       "path": None if (a.sem_imagens and not a.caminhos_completos) else f"imagens/{iid}.jpg", "pano_id": ex.get("pano_id"), "yaw": ex.get("yaw")})

    # escrever o pacote
    today = dt.date.today().isoformat()
    stage = a.out / f"_pacote_{a.city}"
    if stage.exists():
        shutil.rmtree(stage)
    for sub in ("recortes", "schema") + (() if a.sem_imagens else ("imagens",)):
        (stage / sub).mkdir(parents=True)
    print(f"{len(dets)} deteções, {len(feats)} elementos, {len(images)} imagens: a gerar recortes{'' if a.sem_imagens else ' e a copiar imagens'}...")
    for d in dets:
        make_crop(ANON / f"{d['image_id']}.jpg", d["bbox"], stage / "recortes" / f"{d['id']}.jpg")
        d["crop_path"] = f"recortes/{d['id']}.jpg"
    if not a.sem_imagens:
        for iid in used_imgs:
            src, dst = ANON / f"{iid}.jpg", stage / "imagens" / f"{iid}.jpg"
            shutil.copy2(src, dst)
            assert sha256(src) == sha256(dst), f"cópia diferente de {iid}"

    if removidos:
        (stage / "removidos.json").write_text(json.dumps({"regra": "; ".join(r for r in (("categorias ignoradas (configs/sinais_ignorados.json)" if a.ignorar_sinais else ""), (f"melhor deteção < {a.remover_sinais_abaixo:g}" if a.remover_sinais_abaixo is not None else "")) if r), "n": len(removidos), "por_motivo": dict(Counter(r["motivo"] for r in removidos.values())), "removidos": sorted(removidos.values(), key=lambda r: r["id"]),
                                                                           "nota": "Os ids dos restantes elementos não mudaram. Se a interface tem decisões guardadas sobre estes ids, ficam sem elemento."}, ensure_ascii=False, indent=1), encoding="utf-8")
    out_det = [{k: d[k] for k in ("id", "image_id", "family", "class", "subtype", "score", "bbox", "quality", "azimuth", "est_distance", "element_id",
                                  "in_catalog", "excluded_reason", "suggested_class", "crop_path", "extra")} for d in dets]
    docs = {"elementos": {"type": "FeatureCollection", "name": f"elementos_{a.city}", "features": feats}, "deteccoes": out_det, "imagens": images,
            "duplicados": {"groups": dup_groups, "pairs": pairs},
            "elementos_unicos": {"type": "FeatureCollection", "name": f"elementos_unicos_{a.city}", "features": unicos}, "ilhas": ilhas}
    sch = schemas()
    for name, doc in docs.items():
        ext = "geojson" if name in ("elementos", "elementos_unicos") else "json"
        (stage / f"{name}.{ext}").write_text(json.dumps(doc, ensure_ascii=False, separators=(",", ":"), allow_nan=False), encoding="utf-8")
        (stage / "schema" / f"{name}.schema.json").write_text(json.dumps(sch[name], ensure_ascii=False, indent=1), encoding="utf-8")
    (stage / "schema" / "decisoes.schema.json").write_text(json.dumps(sch["decisoes"], ensure_ascii=False, indent=1), encoding="utf-8")
    ex_el = feats[0]["properties"]
    exemplo = {"schema_version": SCHEMA_VERSION, "decisions": [
        {"element_id": ex_el["id"], "best_detection_id": ex_el["observations"][-1]["detection_id"], "status": "validado",
         "decided_by": "tecnico@exemplo", "decided_at": "2026-11-17T10:00:00Z", "note": "escolhi outra imagem como a melhor"},
        {"element_id": "ELEMENTO_A_JUNTAR", "merge_into": ex_el["id"], "decided_by": "tecnico@exemplo", "decided_at": "2026-11-17T10:01:00Z"}]}
    (stage / "decisoes.exemplo.json").write_text(json.dumps(exemplo, ensure_ascii=False, indent=1), encoding="utf-8")

    # validar contra os esquemas
    import jsonschema
    for name, doc in docs.items():
        jsonschema.validate(json.loads((stage / f"{name}.{'geojson' if name in ('elementos', 'elementos_unicos') else 'json'}").read_text(encoding="utf-8")), sch[name])
    jsonschema.validate(exemplo, sch["decisoes"])
    ids = [f["properties"]["id"] for f in feats]
    assert len(ids) == len(set(ids)) and len({d["id"] for d in out_det}) == len(out_det), "ids repetidos"
    assert all(o["detection_id"] in by_id for f in feats for o in f["properties"]["observations"]), "observação sem deteção"
    assert all(f["properties"]["best_detection_id"] == f["properties"]["observations"][0]["detection_id"] for f in feats)

    fam = Counter(f["properties"]["family"] for f in feats)
    counts = (f"- elementos: {len(feats)} ({dict(fam)}); triangulados (posição fiável): {sum(f['properties']['position_reliable'] for f in feats)}\n"
              f"- deteções: {len(dets)} ({sum(d['in_catalog'] for d in dets)} em elementos; "
              f"{sum(d['excluded_reason'] == 'papeleira_filter' for d in dets)} filtradas como papeleira; "
              f"{sum(d['excluded_reason'] == 'catalog_filter' for d in dets)} fora do catálogo por outro filtro)\n"
              f"- imagens: {len(images)} · grupos de duplicados: {len(dup_groups)} (com {sum(len(g['members']) for g in dup_groups)} elementos)\n"
              f"- inventário único: {len(unicos)} elementos ({sum(1 for g in dup_groups if g.get('auto_merge'))} fusões automáticas) · ilhas de reciclagem: {len(ilhas)}")
    commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True).stdout.strip() or "?"
    (stage / "LEIA-ME.md").write_text(README.format(city=a.city.capitalize(), date=today, ver=SCHEMA_VERSION, commit=commit, n_det=len(dets), **NOTAS_COBERTURA["aveiro" if a.city == "aveiro" else "zona"],
                                                    radii=", ".join(f"{k} {v:g}" for k, v in radii.items()), counts=counts), encoding="utf-8")
    (stage / "ATRIBUICOES.md").write_text("# Atribuições\n\n- Imagens: " + sorted({i["attribution"] for i in images})[0] + " (licença CC BY-SA 4.0: https://creativecommons.org/licenses/by-sa/4.0/). "
                                          "Mostrar a atribuição junto de cada imagem; adaptações (recortes) herdam a licença.\n"
                                          "- Posições de referência e vias: © colaboradores do OpenStreetMap (ODbL, https://www.openstreetmap.org/copyright).\n"
                                          "- Previsões: geradas pelo projeto (Grounding DINO, RF-DETR/MTSD, CLIP). Ver `docs/licencas/` do projeto para os modelos.\n", encoding="utf-8")
    manifest = {"schema_version": SCHEMA_VERSION, "city": a.city, "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "commit": commit,
                "crs": "EPSG:4326 (GeoJSON: [lon, lat])", "position": "v1.2: triangulada, ou vista única com a profundidade encolhida por k (scripts/deduplicar.py); a da 1.1 em position_previous; sem ajuste à estrada",
                "adjustment": cat.get("ajuste"), "duplicate_radius_m": radii, "images_included": not a.sem_imagens,
                "removed_low_confidence": len(removidos), "counts": {"elements": len(feats), "unique_elements": len(unicos), "islands": len(ilhas), "auto_merged_groups": sum(1 for g in dup_groups if g.get("auto_merge")), "detections": len(dets), "images": len(images), "duplicate_groups": len(dup_groups)}, "files": {}}
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            manifest["files"][str(p.relative_to(stage))] = {"bytes": p.stat().st_size, "sha256": sha256(p)}
    (stage / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1, allow_nan=False), encoding="utf-8")

    # zip (as imagens e recortes são JPEG: sem recompressão) + elementos.geojson solto
    zp = a.out / f"entrega_{a.city}_{today}.zip"
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(stage.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(stage), compress_type=zipfile.ZIP_STORED if p.suffix == ".jpg" else zipfile.ZIP_DEFLATED)
    shutil.copy2(stage / "elementos.geojson", a.out / "elementos.geojson")
    shutil.rmtree(stage)
    print(counts)
    print(f"-> {zp} ({zp.stat().st_size / 1e6:.0f} MB) e {a.out / 'elementos.geojson'}")


if __name__ == "__main__":
    main()
