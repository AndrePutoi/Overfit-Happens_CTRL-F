"""Deteção + classificação de TODAS as vistas admitidas de uma zona, com os modelos de produção do registo (`urban_mobile_search`). Substitui os `prever_*_aveiro.py`.

    python -m ctrlf.scripts.detetar_zona <zona> [--familias sinal residuos iluminacao mobiliario] [--bloco 150] [--refazer]

Entrada : data/raw/<zona>_vistas/meta.jsonl  (vistas já ADMITIDAS e ANONIMIZADAS no cache: o `Pipeline` pede a imagem a `privacy.anon_cache`, que falha fechado se o sha256 não bater)
Saídas  : data/zonas/<zona>/deteccoes/bloco_NNNN.jsonl   FORMATO ÚNICO de deteções (1 linha = 1 imagem; retoma por bloco)
          data/preannot/{sinais,ecopontos,luz,bancos}/<zona>/annotations/instances_default.json   COCO que o catálogo (pipeline/export_geojson.py) lê
          data/zonas/<zona>/deteccoes/modelos.json   versão/pesos de cada detetor e classificador usados (rastreio)
Famílias em blocos de `--bloco` vistas: dentro de cada bloco o `Pipeline` carrega um módulo de cada vez e liberta a GPU (6 GB) antes do seguinte; o bloco limita a memória (RAM) em zonas grandes.
Campos escritos (os mesmos que a cadeia de Aveiro): sinais -> categoria = grupo, attributes.tipo, score, p_router, score_tipo;
contentores -> contentor/subterraneo (+ p_papeleira se o filtro CLIP estiver ativo); com o detetor de 3 classes as papeleiras vão para `papeleiras.json` e NÃO entram no COCO.
O tipo do caixote (fluxo) NÃO vai no COCO: sai de scripts/tipar_residuos_catalogo.py, como em Aveiro.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))

PREANNOT = {"sinal": "sinais", "residuos": "ecopontos", "iluminacao": "luz", "mobiliario": "bancos"}
CATEGORIAS = {"sinal": ["regulamentacao", "perigo", "informacao", "complementar", "orientacao_outros"],
              "residuos": ["contentor", "subterraneo"], "iluminacao": ["candeeiro", "poste_luz"], "mobiliario": ["banco"]}


def _clf(d, task):
    return next((c for c in d.classifications if c.task == task), None)


def atributos(d) -> dict:
    """Campos extra de uma deteção, com os nomes que a cadeia de Aveiro usa."""
    out = {}
    if d.family == "sinal":
        t = _clf(d, "sign_type")
        if t:
            out["tipo"] = t.label
            out["p_router"] = t.extra.get("p_router")
            out["score_tipo"] = round(float(t.score), 3)
    elif d.family == "residuos":
        p = _clf(d, "papeleira")
        if p:
            out["p_papeleira"] = p.extra.get("p_papeleira")
        f = _clf(d, "container_flux")
        if f:
            out["fluxo_sugerido"] = f.label
    return out


def processar_blocos(zona: str, familias, bloco: int, refazer: bool) -> dict:
    from PIL import Image  # noqa: F401  (o Pipeline usa-o)
    from ctrlf.urban_mobile_search import Pipeline, Settings
    s = Settings.from_env()
    s.families = tuple(familias)
    # a admissão já foi feita (ingest/admissao.py --aplicar) e re-corrê-la rejeitaria tudo como `duplicada`: aqui confia-se no meta.jsonl admitido
    pipe = Pipeline(s, admit=lambda p, meta: {"status": "aprovada", "meta": dict(meta), "id": Path(p).stem, "motivos": []})
    metas = [json.loads(l) for l in (ROOT / "data" / "raw" / f"{zona}_vistas" / "meta.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    pasta = ROOT / "data" / "zonas" / zona / "deteccoes"
    pasta.mkdir(parents=True, exist_ok=True)
    if refazer:
        for f in pasta.glob("bloco_*.jsonl"):
            f.unlink()
    n_blocos = (len(metas) + bloco - 1) // bloco
    t0 = time.time()
    for b in range(n_blocos):
        f = pasta / f"bloco_{b:04d}.jsonl"
        if f.exists():
            continue                                                       # retoma: bloco já feito
        lote = metas[b * bloco:(b + 1) * bloco]
        res = pipe.process_many([(ROOT / m["path"], m) for m in lote], persist=False)
        tmp = f.with_suffix(".part")
        with open(tmp, "w", encoding="utf-8") as fo:
            for m, r in zip(lote, res):
                fo.write(json.dumps({"image": Path(m["path"]).name, "image_id": m["source_image_id"], "skipped": r.skipped,
                                     "detections": [{"id": d.id, "family": d.family, "cls": d.cls, "score": round(d.score, 4), "bbox": [round(v, 1) for v in d.bbox],
                                                     "status": d.status, "attrs": atributos(d), "detector": d.extra.get("detector"), "model_version": d.model_version,
                                                     "classifications": [{"task": c.task, "label": c.label, "score": round(float(c.score), 4), "extra": c.extra} for c in d.classifications]}
                                                    for d in r.detections]}, ensure_ascii=False, default=str) + "\n")
        tmp.replace(f)
        print(f"bloco {b + 1}/{n_blocos}: {len(lote)} vistas, {sum(len(r.detections) for r in res)} deteções, {time.time() - t0:.0f}s", flush=True)
    versoes = {"detetores": {fam: [{"nome": sp.name, "versao": sp.version, "pesos": str(sp.weights) if sp.weights else None} for sp in pipe.registry.detectors(fam)] for fam in familias},
               "classificadores": {fam: [{"nome": sp.name, "versao": sp.version, "pesos": str(sp.weights) if sp.weights else None} for sp in pipe.registry.classifiers(fam)] for fam in familias}}
    return versoes


def escrever_coco(zona: str, familias, versoes: dict) -> dict:
    pasta = ROOT / "data" / "zonas" / zona / "deteccoes"
    linhas = [json.loads(l) for f in sorted(pasta.glob("bloco_*.jsonl")) for l in f.read_text(encoding="utf-8").splitlines() if l.strip()]
    IGN = json.loads((ROOT / "configs" / "sinais_ignorados.json").read_text(encoding="utf-8"))        # categorias de sinais ignoradas por completo (decisão do utilizador)
    contagens, papeleiras, ignoradas = {}, [], {}
    for fam in familias:
        cats = CATEGORIAS[fam]
        imgs, anns = [], []
        meta_w = {}
        for m in (json.loads(l) for l in (ROOT / "data" / "raw" / f"{zona}_vistas" / "meta.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()):
            meta_w[Path(m["path"]).name] = m.get("extra", {})
        for ln in linhas:
            if ln["skipped"]:
                continue
            w = meta_w.get(ln["image"], {}).get("width")
            h = meta_w.get(ln["image"], {}).get("height")
            iid = len(imgs) + 1
            imgs.append({"id": iid, "file_name": ln["image"], "width": w, "height": h})
            for d in ln["detections"]:
                if d["family"] != fam or d["status"] == "rejeitado":
                    continue
                if d["cls"] == "papeleira":
                    papeleiras.append({"image_id": ln["image_id"], "bbox": d["bbox"], "cls": "papeleira", "score": d["score"], "p_papeleira": 1.0})
                    continue
                if d["cls"] not in cats:
                    continue
                if fam == "sinal" and (d["cls"] in IGN["grupos"] or d["attrs"].get("tipo") in IGN["tipos"]):
                    k = IGN["nomes_pt"].get(d["cls"] if d["cls"] in IGN["grupos"] else d["attrs"].get("tipo"), "ignorada")
                    ignoradas[k] = ignoradas.get(k, 0) + 1                  # fica no JSONL (formato único), mas não entra no COCO nem no catálogo
                    continue
                x1, y1, x2, y2 = d["bbox"]
                a = {"id": len(anns) + 1, "image_id": iid, "category_id": cats.index(d["cls"]) + 1, "bbox": [x1, y1, round(x2 - x1, 1), round(y2 - y1, 1)],
                     "area": round((x2 - x1) * (y2 - y1), 1), "iscrowd": 0, "score": d["score"], "attributes": {"occluded": False}}
                for k, v in d["attrs"].items():
                    if k == "tipo":
                        a["attributes"]["tipo"] = v
                    elif k != "fluxo_sugerido":
                        a[k] = v
                anns.append(a)
        out = ROOT / "data" / "preannot" / PREANNOT[fam] / zona / "annotations" / "instances_default.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"categories": [{"id": i + 1, "name": c} for i, c in enumerate(cats)], "images": imgs, "annotations": anns}), encoding="utf-8")
        contagens[fam] = {"imagens": len(imgs), "deteccoes": len(anns)}
    if ignoradas:
        contagens["sinais_ignorados_por_categoria"] = ignoradas
    if papeleiras:
        (ROOT / "data" / "preannot" / PREANNOT["residuos"] / zona / "papeleiras.json").write_text(json.dumps(papeleiras, ensure_ascii=False), encoding="utf-8")
        contagens["papeleiras_do_detetor"] = len(papeleiras)
    (pasta / "modelos.json").write_text(json.dumps({**versoes, "contagens": contagens, "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S")}, ensure_ascii=False, indent=1), encoding="utf-8")
    return contagens


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zona")
    ap.add_argument("--familias", nargs="+", default=["sinal", "residuos", "iluminacao", "mobiliario"], choices=list(PREANNOT))
    ap.add_argument("--bloco", type=int, default=150)
    ap.add_argument("--refazer", action="store_true", help="ignora os blocos já feitos")
    a = ap.parse_args()
    versoes = processar_blocos(a.zona, a.familias, a.bloco, a.refazer)
    print("contagens:", json.dumps(escrever_coco(a.zona, a.familias, versoes), ensure_ascii=False))


if __name__ == "__main__":
    main()
