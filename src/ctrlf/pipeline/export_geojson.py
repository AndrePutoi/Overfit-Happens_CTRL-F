"""Deteções (COCO) + posição da câmara -> catálogo GeoJSON por família, sem duplicados, pronto para a API/frontend de C.

    python -m ctrlf.pipeline.export_geojson --city lisboa --meta data/raw/lisboa_vistas/meta.jsonl \
        --luz data/preannot/luz/lisboa/annotations/instances_default.json \
        --residuos data/preannot/ecopontos/lisboa/annotations/instances_default.json \
        --sinal data/preannot/sinais/lisboa/annotations/instances_default.json \
        --reference data/reference/lisboa_luz.geojson --anon-dir data/images_anon --out data/catalog/lisboa

Aceita tanto as pré-anotações dos modelos como o export COCO 1.0 do CVAT já corrigido (use --status validado).
Cada COCO é uma família: --luz (poste_luz, candeeiro), --residuos (contentor, subterraneo), --sinal (as 5 famílias de sinal).

Passos: posição da vista (azimute = rumo + ângulo da coluna; distância FIXA por omissão, ver --dist: sem profundidade a posição de vista única tem erro de vários metros) -> agrupar o MESMO
elemento visto em várias imagens (pipeline/dedup.py, raios em metros por classe) -> triangular quando há >= 2 imagens ->
confiança c_e (geometry.confidence) -> GeoJSON.  Regras de duplicados (docs/Plano.md §8):
  * iluminação: poste_luz e candeeiro agrupam JUNTOS (o mesmo candeeiro pode sair simples numa vista e decorativo noutra);
    a classe do elemento é a de maior pontuação somada.  Um candeeiro num poste é UM elemento.
  * resíduos: agrupa por classe; `n_unidades` = maior nº de contentores desse grupo numa só imagem (uma ilha = 1 elemento
    com N unidades, para não inflacionar a contagem).
  * sinais: agrupa por tipo; dois sinais de tipos diferentes na mesma haste são elementos diferentes.
Saída em --out: iluminacao.geojson, residuos.geojson, sinal.geojson, catalog.geojson (todas), referencia_<família>.geojson (OSM/Mapillary
e se foram encontrados), images_index.json (imagem -> posição, licença, URL) e manifest.json.
`image_url` aponta para /images/<image_id>.jpg: C serve a pasta --anon-dir (imagens ANONIMIZADAS) nessa rota.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.geometry.geometry import (Ray, bearing_offset_perspective, confidence, object_azimuth,  # noqa: E402
                               single_view_position, to_deg, to_m, triangulate)
from ctrlf.pipeline.assoc_rays import Params, associate  # noqa: E402
from ctrlf.pipeline.dedup import Obs, cluster  # noqa: E402

SIGNAL_GROUPS = {"regulamentacao", "perigo", "informacao", "complementar", "orientacao_outros"}
FAMILY = {"poste_luz": "iluminacao", "candeeiro": "iluminacao", "contentor": "residuos", "subterraneo": "residuos", "banco": "mobiliario"}
EPS_KEY = {"iluminacao": "candeeiro", "residuos": "contentor", "sinal": "sinal", "mobiliario": "contentor"}     # raio de pipeline.dedup.EPS_M
CATCH_ALL = {"orientacao_outros", "desconhecido"}        # tipos "saco": agrupam placas MUITO diferentes -> tolerâncias apertadas
STRICT = Params(perp_tol=1.5, eps=1.5, depth_abs=4.0, depth_rel=0.3, min_angle=12.0, single_eps=1.5)
MAX_DIST_M = 40.0                                                                    # como em run_pipeline: mais longe = descartado


def make_embed_fn(store: Path):
    """Embedding DINOv2-small (384) do recorte de uma caixa, sobre a imagem ANONIMIZADA: serve para desempatar placas parecidas."""
    from PIL import Image
    import torch
    from torchvision import transforms
    from transformers import AutoModel
    from ctrlf.detection.postfilter.papeleiras import crop_box
    from ctrlf.privacy.anon_cache import anonymized_cached
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained("facebook/dinov2-small").to(dev).eval()
    tf = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(),
                             transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))])
    cache: dict = {}

    @torch.no_grad()
    def fn(m, bbox):
        k = m["source_image_id"]
        if k not in cache:
            if len(cache) >= 4:
                cache.clear()
            cache[k] = Image.fromarray(np.asarray(anonymized_cached(ROOT / m["path"], store)))
        x = tf(crop_box(cache[k], bbox).convert("RGB"))[None].to(dev)
        e = model(pixel_values=x).pooler_output[0].float().cpu().numpy()
        return e / (np.linalg.norm(e) + 1e-9)
    return fn


def make_pap_fn(store: Path):
    """p(papeleira) de cada caixa de contentor, por CLIP sobre o recorte da imagem ANONIMIZADA (detection/postfilter/papeleiras.py)."""
    from PIL import Image
    import torch
    from ctrlf.detection.postfilter.papeleiras import PapeleiraFilter, crop_box
    from ctrlf.privacy.anon_cache import anonymized_cached
    flt, cache = PapeleiraFilter("cuda" if torch.cuda.is_available() else "cpu"), {}

    def fn(m, bbox):
        k = m["source_image_id"]
        if k not in cache:
            if len(cache) >= 4:
                cache.clear()
            cache[k] = Image.fromarray(np.asarray(anonymized_cached(ROOT / m["path"], store)))
        return flt.scores([crop_box(cache[k], bbox)])[0][0]
    return fn


def make_depth_fn(store: Path):
    """Distância (m) à caixa por profundidade métrica (Depth Anything V2) sobre a imagem ANONIMIZADA, 1 mapa por imagem."""
    from PIL import Image
    from ctrlf.geometry.depth import DepthEstimator
    from ctrlf.privacy.anon_cache import anonymized_cached
    est, cache = DepthEstimator(), {}

    def fn(m, im, bbox):
        k = m["source_image_id"]
        if k not in cache:
            if len(cache) >= 4:
                cache.clear()                                   # as anotações vêm agrupadas por imagem; poupa memória
            img = Image.fromarray(np.asarray(anonymized_cached(ROOT / m["path"], store)))
            cache[k] = (img, est.depth_map(img))
        img, dmap = cache[k]
        off = bearing_offset_perspective((bbox[0] + bbox[2]) / 2, im["width"], m.get("hfov_deg") or 65.0)
        return float(est.distance_in_bbox(img, bbox, off, dmap))
    return fn


def load_obs(coco_path: Path, family: str, metas: dict, min_score: float, dist_m: float, dep, cache, dist_scale: float = 1.0,
             pap=None, pap_thr=(0.80, 0.97), dropped: list | None = None, emb_fn=None) -> list[dict]:
    d = json.loads(coco_path.read_text(encoding="utf-8"))
    cat = {c["id"]: c["name"] for c in d["categories"]}
    img = {i["id"]: i for i in d["images"]}
    obs, no_meta, too_far = [], 0, 0
    for a in d["annotations"]:
        name = cat[a["category_id"]]
        fam = "sinal" if name in SIGNAL_GROUPS else FAMILY.get(name)
        if fam != family:
            continue
        im = img[a["image_id"]]
        m = metas.get(im["file_name"])
        if m is None:
            no_meta += 1
            continue
        score = float(a.get("score", a.get("score_gdino", 1.0)))
        if score < min_score:
            continue
        x, y, w, h = a["bbox"]
        bbox = (x, y, x + w, y + h)
        if pap is not None and family == "residuos":
            pp = pap(m, bbox)
            if pp >= (pap_thr[0] if name == "contentor" else pap_thr[1]):       # papeleira: fora ANTES de agrupar
                if dropped is not None:
                    dropped.append({"image_id": m["source_image_id"], "bbox": [round(v, 1) for v in bbox], "cls": name,
                                    "score": round(score, 3), "p_papeleira": round(float(pp), 3)})
                continue
        az = object_azimuth((bbox[0] + bbox[2]) / 2, im["width"], m["heading"], "perspective", m.get("hfov_deg") or 65.0)
        dist, method = dist_m, "vista_unica_distancia_fixa"
        if dep is not None:
            dist, method = dep(m, im, bbox) * dist_scale, "vista_unica_profundidade"
            if not (dist <= MAX_DIST_M):                        # inclui NaN
                too_far += 1
                continue
        lat, lon = single_view_position(m["lat"], m["lon"], az, dist)
        sub = (a.get("attributes") or {}).get("tipo") if family == "sinal" else None
        emb = emb_fn(m, bbox) if (emb_fn is not None and family == "sinal" and (sub in CATCH_ALL or not sub)) else None
        obs.append({"emb": emb, "cls": name, "sub": sub, "score": score, "bbox": bbox, "az": az, "dist": dist, "xy": to_m(lat, lon),
                    "meta": m, "image_id": m["source_image_id"], "method": method,
                    "W": im["width"], "H": im["height"]})
    if no_meta:
        print(f"  aviso: {no_meta} anotações sem meta.jsonl correspondente (ignoradas)")
    if too_far:
        print(f"  {too_far} observações a mais de {MAX_DIST_M:.0f} m descartadas")
    return obs


def quality(r: dict) -> float:
    """Quão boa é esta observação para MOSTRAR o elemento: pontuação do detetor x tamanho da caixa x não cortada pelo bordo
    x perto do centro (menos distorção) x distância útil (4 a 25 m)."""
    x1, y1, x2, y2 = r["bbox"]
    W, H = r["W"], r["H"]
    size = math.sqrt(min(1.0, ((x2 - x1) * (y2 - y1)) / (W * H) / 0.004))
    edge = 0.5 if (x1 <= 3 or y1 <= 3 or x2 >= W - 3 or y2 >= H - 3) else 1.0
    center = 1.0 - 0.3 * abs((x1 + x2) / 2 - W / 2) / (W / 2)
    dist = 1.0 if 4.0 <= r["dist"] <= 25.0 else 0.7
    return r["score"] * size * edge * center * dist


def bucket_key(family: str, o: dict, bucket: str = "type") -> str:
    if family == "iluminacao":
        return "todos"
    if family == "sinal":
        return o["cls"] if bucket == "family" else (o["sub"] or o["cls"])      # family: agrupa pela família; o tipo vota-se depois
    return o["cls"]


def vote_type(rs: list[dict]) -> str:
    """Tipo de um grupo de sinais = o mais votado (pontuação do detetor), ignorando 'desconhecido'; só é desconhecido se todos o forem."""
    c = Counter()
    for r in rs:
        if r["sub"] and r["sub"] != "desconhecido":
            c[r["sub"]] += r["score"]
    return c.most_common(1)[0][0] if c else "desconhecido"


def build(family: str, obs: list[dict], eps_scale: float, status: str, city: str, bucket: str = "type",
          assoc: str = "dbscan", catchall: str = "strict", emb_thr: float = 0.35) -> list[dict]:
    buckets = defaultdict(list)
    for o in obs:
        # com raios, todos os contentores (superfície e subterrâneos) entram no MESMO balde: um elemento = um ECOPONTO,
        # e o rótulo escolhe-se por voto entre as vistas
        buckets["ecoponto" if (assoc == "rays" and family == "residuos") else bucket_key(family, o, bucket)].append(o)
    feats = []
    for key, rows in sorted(buckets.items()):
        if assoc == "rays":
            cams: dict = {}
            cam_id = np.array([cams.setdefault((round(r["meta"]["lat"], 6), round(r["meta"]["lon"], 6)), len(cams)) for r in rows])
            origin = np.array([to_m(r["meta"]["lat"], r["meta"]["lon"]) for r in rows])
            is_catch = family == "sinal" and key in CATCH_ALL
            if is_catch and catchall == "none":                         # nunca fundir tipos "saco": cada observação é um elemento
                labels = np.arange(len(rows))
            else:
                labels, _ = associate(origin, np.array([r["az"] for r in rows]), np.array([r["dist"] for r in rows]), cam_id,
                                      np.array([r["xy"] for r in rows]), STRICT if (is_catch and catchall == "strict") else None)
                if is_catch and catchall == "appearance" and all(r["emb"] is not None for r in rows):
                    # dentro de cada grupo geométrico, só ficam juntos os recortes que se PARECEM (distância cosseno média <= emb_thr)
                    from sklearn.cluster import AgglomerativeClustering
                    new, nxt_l = labels.copy(), int(labels.max()) + 1
                    for g in np.unique(labels):
                        idx = np.where(labels == g)[0]
                        if len(idx) < 2:
                            continue
                        sub_l = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                                        distance_threshold=emb_thr).fit_predict(np.array([rows[i]["emb"] for i in idx]))
                        for sl in np.unique(sub_l)[1:]:
                            new[idx[sub_l == sl]] = nxt_l
                            nxt_l += 1
                    labels = new
        else:
            labels = cluster([Obs(EPS_KEY[family], r["xy"], None, r["score"]) for r in rows], eps_scale=eps_scale)
        groups = defaultdict(list)
        for r, g in zip(rows, labels):
            groups[int(g)].append(r)
        for rs in groups.values():
            imgs = {r["image_id"] for r in rs}
            # vistas "independentes" = posições de câmara distintas (as 4 vistas de um panorama partilham a posição)
            pos_best: dict = {}
            for r in rs:
                k = (round(r["meta"]["lat"], 6), round(r["meta"]["lon"], 6))
                pos_best[k] = max(pos_best.get(k, 0.0), r["score"])
            xy, residual, method = np.mean([r["xy"] for r in rs], axis=0), None, rs[0]["method"]
            if len(pos_best) >= 2:
                t = triangulate([Ray.from_obs(r["meta"]["lat"], r["meta"]["lon"], r["az"]) for r in rs])
                if t is not None:
                    xy, residual, _ = t
                    method = "triangulado"
            lat, lon = to_deg(xy)
            by_cls = Counter()
            for r in rs:
                by_cls[r["cls"]] += r["score"]
            cls = by_cls.most_common(1)[0][0]
            best = max(rs, key=quality)                           # a MELHOR imagem para mostrar, não só a de maior pontuação
            per_img = Counter(r["image_id"] for r in rs if (assoc == "rays" or r["cls"] == cls))
            q_by_img: dict = {}
            for r in rs:
                q_by_img[r["image_id"]] = max(q_by_img.get(r["image_id"], 0.0), quality(r))
            ordered = sorted(imgs, key=lambda i: -q_by_img[i])
            props = {"family": family, "class": "sinal" if family == "sinal" else cls,
                     "subclass": ((vote_type(rs) if bucket == "family" else best["sub"]) if family == "sinal" else None),
                     "confidence": round(confidence(list(pos_best.values()), residual), 3),
                     "n_views": len(pos_best), "confirmado": len(pos_best) >= 2, "geo_method": method,
                     "geo_residual_m": None if residual is None else round(float(residual), 2),
                     "image_id": best["image_id"], "image_url": f"/images/{best['image_id']}.jpg",
                     "image_quality": round(quality(best), 3),
                     "image_ids": ordered[:6], "bbox": [round(v) for v in best["bbox"]],
                     "source": best["meta"].get("source"), "license": best["meta"].get("license"),
                     "attribution": best["meta"].get("attribution"), "status": status, "layer": "deteccao"}
            if family == "sinal":
                props["grupo"] = cls
            if family == "residuos":
                props["n_unidades"] = max(per_img.values()) if per_img else 1
                props["votos"] = {k: round(v, 2) for k, v in by_cls.most_common()}       # peso de cada rótulo entre as vistas
            members = [{"image_id": r["image_id"], "bbox": [round(v, 1) for v in r["bbox"]], "score": round(r["score"], 3),
                        "cls": r["cls"], "tipo": r["sub"], "cam": [r["meta"]["lat"], r["meta"]["lon"]],
                        "az": round(r["az"], 1), "dist_m": round(float(r["dist"]), 1)} for r in rs]
            feats.append({"type": "Feature", "properties": props, "_obs": members,
                          "geometry": {"type": "Point", "coordinates": [round(lon, 7), round(lat, 7)]}})
    feats.sort(key=lambda f: (f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]))
    for n, f in enumerate(feats, 1):
        f["properties"]["id"] = f"{family[:3]}-{city}-{n:05d}"
    return feats


def load_ref(path: Path) -> list[dict]:
    """GeoJSON, ou JSON bruto do Overpass (elements), -> lista de Features de ponto."""
    d = json.loads(path.read_text(encoding="utf-8"))
    if "features" in d:
        return d["features"]
    return [{"type": "Feature", "properties": {"source": "osm", "osm_id": e["id"], **e.get("tags", {})},
             "geometry": {"type": "Point", "coordinates": [e["lon"], e["lat"]]}} for e in d["elements"] if e.get("type") == "node"]


def in_zone(ref: list[dict], metas, margin_deg: float = 0.001) -> list[dict]:
    """Só os pontos de referência dentro da zona coberta pelas imagens (+ margem), não a cidade inteira."""
    la, lo = [m["lat"] for m in metas], [m["lon"] for m in metas]
    x0, x1, y0, y1 = min(lo) - margin_deg, max(lo) + margin_deg, min(la) - margin_deg, max(la) + margin_deg
    return [r for r in ref if x0 <= r["geometry"]["coordinates"][0] <= x1 and y0 <= r["geometry"]["coordinates"][1] <= y1]


def match_reference(feats: list[dict], ref: list[dict], radius: float) -> list[dict]:
    """Marca `ref_match` nos elementos e devolve a camada de referência com `detetado` sim/não (ponto com elemento a <= radius)."""
    pts = [(to_m(f["geometry"]["coordinates"][1], f["geometry"]["coordinates"][0]), f) for f in feats]
    out = []
    for r in ref:
        lon, lat = r["geometry"]["coordinates"]
        rm = to_m(lat, lon)
        best = min(((float(np.linalg.norm(rm - p)), f) for p, f in pts), key=lambda t: t[0], default=(1e9, None))
        det = best[0] <= radius
        if det:
            best[1]["properties"]["ref_match"] = True
        out.append({"type": "Feature", "geometry": r["geometry"],
                    "properties": {**r["properties"], "layer": "referencia", "detetado": det,
                                   "dist_deteccao_m": None if best[1] is None else round(best[0], 1)}})
    for f in feats:
        f["properties"].setdefault("ref_match", False)
    return out


def anonymize_best(feats, index, anon_dir: Path) -> int:
    """Garante, na cache de imagens anonimizadas, as imagens usadas pelos elementos (as já feitas não se repetem)."""
    from ctrlf.privacy.anon_cache import anonymized_cached
    before = (anon_dir / "manifest.jsonl").read_text().count("\n") if (anon_dir / "manifest.jsonl").exists() else 0
    for iid in sorted({f["properties"]["image_id"] for f in feats}):
        anonymized_cached(ROOT / index[iid]["file"], anon_dir)
    return (anon_dir / "manifest.jsonl").read_text().count("\n") - before


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--city", required=True)
    ap.add_argument("--meta", type=Path, required=True)
    ap.add_argument("--luz", type=Path)
    ap.add_argument("--residuos", type=Path)
    ap.add_argument("--sinal", type=Path)
    ap.add_argument("--banco", type=Path, help="COCO dos bancos (preannotate_bancos.py): família mobiliario")
    ap.add_argument("--reference", type=Path, help="GeoJSON de referência (OSM/Mapillary) da iluminação")
    ap.add_argument("--ref-residuos", type=Path, help="referência dos contentores: GeoJSON ou JSON do Overpass (ex.: data/reference/osm_aveiro_recycling.json)")
    ap.add_argument("--ref-radius-residuos", type=float, default=15.0, help="m; o nó OSM é a ilha, não cada contentor")
    ap.add_argument("--depth", action="store_true", help="distância por profundidade (Depth Anything V2); sem isto, --dist fixo")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--anon-dir", type=Path, help="grava aqui as imagens ANONIMIZADAS usadas (C serve-as em /images)")
    ap.add_argument("--status", default="auto", choices=["auto", "validado", "corrigido"])
    ap.add_argument("--min-score", type=float, default=0.0)
    ap.add_argument("--dist", type=float, default=12.0, help="distância fixa (m) quando não há profundidade")
    ap.add_argument("--eps-scale", type=float, default=2.5, help=">1 alarga os raios de agrupamento (vista única)")
    ap.add_argument("--match-radius", type=float, default=6.0)
    ap.add_argument("--bucket", choices=["type", "family"], default="type",
                    help="sinais: agrupar por tipo (omissão) ou por família com voto de tipo (resolve o mesmo sinal com tipos diferentes)")
    ap.add_argument("--assoc", choices=["dbscan", "rays"], default="dbscan",
                    help="dbscan = agrupa posições de vista única (antigo); rays = associa pela geometria dos raios (pipeline/assoc_rays.py)")
    ap.add_argument("--catchall", choices=["strict", "normal", "none", "appearance"], default="strict",
                    help="tipos 'saco' (orientacao_outros, desconhecido): tolerâncias apertadas (strict), iguais (normal) ou sem fundir (none)")
    ap.add_argument("--emb-thr", type=float, default=0.35, help="catchall=appearance: distância cosseno máxima para ficarem juntos")
    ap.add_argument("--filtro-papeleiras", action="store_true", help="descarta caixotes de rua (CLIP) antes de agrupar os contentores")
    ap.add_argument("--pap-contentor", type=float, default=0.80)
    ap.add_argument("--pap-subterraneo", type=float, default=0.97)
    ap.add_argument("--dist-scale", type=float, default=1.0, help="fator de calibração da distância por profundidade")
    a = ap.parse_args()

    metas = {}
    for line in a.meta.read_text(encoding="utf-8").splitlines():
        m = json.loads(line)
        metas[Path(m["path"]).name] = m
    a.out.mkdir(parents=True, exist_ok=True)
    depth_fn = make_depth_fn(a.anon_dir or ROOT / "data" / "images_anon") if a.depth else None

    obs_index: dict = {}
    dropped: list = []
    emb_fn = make_embed_fn(a.anon_dir or ROOT / "data" / "images_anon") if a.catchall == "appearance" else None
    pap_fn = make_pap_fn(a.anon_dir or ROOT / "data" / "images_anon") if a.filtro_papeleiras else None
    all_feats, manifest, used = [], {"city": a.city, "params": {k: str(v) for k, v in vars(a).items()}, "families": {}}, {}
    for family, path in (("iluminacao", a.luz), ("residuos", a.residuos), ("sinal", a.sinal), ("mobiliario", a.banco)):
        if not path:
            continue
        print(f"{family}: {path}")
        obs = load_obs(path, family, metas, a.min_score, a.dist, depth_fn, None, a.dist_scale, pap_fn, (a.pap_contentor, a.pap_subterraneo), dropped, emb_fn)
        feats = build(family, obs, a.eps_scale, a.status, a.city, a.bucket, a.assoc, a.catchall, a.emb_thr)
        for f in feats:
            obs_index[f["properties"]["id"]] = f.pop("_obs")
        manifest["families"][family] = {"observacoes": len(obs), "elementos": len(feats),
                                       "classes": dict(Counter(f["properties"]["class"] for f in feats)),
                                       "com_varias_vistas": sum(1 for f in feats if f["properties"]["n_views"] > 1)}
        print(f"  {len(obs)} observações -> {len(feats)} elementos {manifest['families'][family]['classes']}")
        for o in obs:
            used[o["image_id"]] = o["meta"]
        refp, rad = {"iluminacao": (a.reference, a.match_radius), "residuos": (a.ref_residuos, a.ref_radius_residuos)}.get(family, (None, 0))
        if refp and refp.exists():
            ref = in_zone(load_ref(refp), [m for m in metas.values()])
            layer = match_reference(feats, ref, rad)
            (a.out / f"referencia_{family}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": layer}, ensure_ascii=False), encoding="utf-8")
            det = sum(1 for r in layer if r["properties"]["detetado"])
            manifest.setdefault("referencia", {})[family] = {"pontos_na_zona": len(layer), "raio_m": rad, "com_elemento_perto": det,
                                                             "elementos_sem_referencia": sum(1 for f in feats if not f["properties"].get("ref_match"))}
            print(f"  referência: {len(layer)} pontos na zona, {det} com elemento a <= {rad} m; "
                  f"{manifest['referencia'][family]['elementos_sem_referencia']} elementos sem referência")
        (a.out / f"{family}.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": feats}, ensure_ascii=False), encoding="utf-8")
        all_feats += feats

    index = {iid: {"image_id": iid, "lat": m["lat"], "lon": m["lon"], "heading": m["heading"], "hfov_deg": m.get("hfov_deg"),
                   "captured_at": m.get("captured_at"), "source": m.get("source"), "license": m.get("license"),
                   "attribution": m.get("attribution"), "url": f"/images/{iid}.jpg", "file": m["path"]} for iid, m in used.items()}
    if a.filtro_papeleiras:
        (a.out / "descartados_papeleiras.json").write_text(json.dumps(dropped, ensure_ascii=False), encoding="utf-8")
        manifest["papeleiras_descartadas"] = len(dropped)
        print(f"{len(dropped)} caixas de papeleira descartadas (ver descartados_papeleiras.json)")
    (a.out / "observacoes.json").write_text(json.dumps(obs_index, ensure_ascii=False), encoding="utf-8")   # membros de cada elemento
    (a.out / "images_index.json").write_text(json.dumps(index, ensure_ascii=False), encoding="utf-8")
    (a.out / "catalog.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": all_feats}, ensure_ascii=False), encoding="utf-8")
    if a.anon_dir:
        needed = {f["properties"]["image_id"] for f in all_feats}
        n = anonymize_best([f for f in all_feats], {k: v for k, v in index.items() if k in needed}, a.anon_dir)
        manifest["imagens_anonimizadas_novas"] = n
        print(f"{n} imagens anonimizadas -> {a.anon_dir}")
    manifest["total_elementos"] = len(all_feats)
    (a.out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"-> {a.out}  ({len(all_feats)} elementos)")


if __name__ == "__main__":
    main()
