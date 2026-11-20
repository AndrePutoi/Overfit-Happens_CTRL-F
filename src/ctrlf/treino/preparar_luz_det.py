"""Exportação COCO do CVAT (tarefa de luz anotada pelo utilizador) -> conjunto de DETEÇÃO para o RF-DETR (train/valid/test).

    python -m ctrlf.treino.preparar_luz_det data/antacoes_luz/Lisboa_A.zip [outro.zip ...] --out data/luz_det

- As caixas vêm da exportação; as IMAGENS vêm sempre de data/images_anon (anonimizadas e verificadas no manifesto SHA-256), nunca da exportação.
- Classes: candeeiro (1), poste_luz (2). O atributo `certeza` NÃO é verdade: é a confiança da pré-anotação antiga; descarta-se.
- Imagens revistas SEM caixas ficam como exemplos negativos (a tarefa A foi toda revista).
- Divisão por PANORAMA (as 4 vistas do mesmo poste ficam do mesmo lado), ~20 % para validação, com mínimo de caixas de cada classe na validação.
  `test` = ligações da validação (o teste a sério é outra cidade/zona).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import random
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from ctrlf.paths import ROOT
ANON = ROOT / "data" / "images_anon"
CLASSES = ["candeeiro", "poste_luz"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("zips", nargs="+", type=Path)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "luz_det")
    ap.add_argument("--val", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--val-fixo", type=Path, default=None,
                    help="pasta `valid` de um conjunto anterior: as imagens dela ficam SEMPRE na validação (comparar modelos novo e antigo sem fuga de dados); a validação das restantes faz-se como de costume")
    a = ap.parse_args()
    manifest = {}
    for l in (ANON / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            d = json.loads(l)
            manifest[d["file"]] = d["sha256"]

    items: dict[str, list] = {}                                  # nome -> caixas [(classe, x, y, w, h)]
    for z in a.zips:
        d = json.loads(zipfile.ZipFile(z).read("annotations/instances_default.json"))
        cat = {c["id"]: c["name"] for c in d["categories"]}
        unknown = set(cat.values()) - set(CLASSES)
        if unknown:
            print(f"  aviso: classes ignoradas em {z.name}: {sorted(unknown)}")
        names = {i["id"]: Path(i["file_name"]).name for i in d["images"]}
        for n in names.values():
            items.setdefault(n, [])
        for an in d["annotations"]:
            if cat[an["category_id"]] in CLASSES:
                items[names[an["image_id"]]].append((cat[an["category_id"]], *an["bbox"]))
    for n in items:
        assert n in manifest, f"{n} não está no manifesto de imagens anonimizadas"
        assert hashlib.sha256((ANON / n).read_bytes()).hexdigest() == manifest[n], f"{n}: sha256 não bate com o manifesto"
    total = Counter(c for v in items.values() for c, *_ in v)
    print(f"{len(items)} imagens ({sum(1 for v in items.values() if not v)} sem caixas), caixas: {dict(total)}")

    fixas = {p.name for p in a.val_fixo.glob("*.jpg")} & set(items) if a.val_fixo else set()
    if a.val_fixo:
        print(f"{len(fixas)} imagens fixas na validação (de {a.val_fixo})")
    groups = defaultdict(list)
    for n in items:
        if n not in fixas:
            groups[n.rsplit("_y", 1)[0] if "_y" in n else n].append(n)
    keys = sorted(groups)
    resto = Counter(c for k in keys for n in groups[k] for c, *_ in items[n])
    need = {"candeeiro": 0.15 * resto["candeeiro"], "poste_luz": 0.15 * resto["poste_luz"]}
    n_resto = sum(len(groups[k]) for k in keys)
    for s in range(a.seed, a.seed + 200):
        random.Random(s).shuffle(keys)
        val, cnt = [], Counter()
        for k in keys:
            if sum(len(groups[g]) for g in val) >= a.val * n_resto:
                break
            val.append(k)
            cnt.update(c for n in groups[k] for c, *_ in items[n])
        if all(cnt[c] >= need[c] for c in CLASSES):
            break
    val_names = {n for k in val for n in groups[k]} | fixas
    print(f"validação: {len(val_names)} imagens de {len(val)} panoramas, caixas {dict(cnt)} (semente {s})")

    shutil.rmtree(a.out, ignore_errors=True)
    for split in ("train", "valid", "test"):
        (a.out / split).mkdir(parents=True)
    for split, names in (("train", sorted(set(items) - val_names)), ("valid", sorted(val_names))):
        imgs, anns = [], []
        from PIL import Image
        for n in names:
            shutil.copy(ANON / n, a.out / split / n)
            w, h = Image.open(a.out / split / n).size
            iid = len(imgs) + 1
            imgs.append({"id": iid, "file_name": n, "width": w, "height": h})
            for c, x, y, bw, bh in items[n]:
                anns.append({"id": len(anns) + 1, "image_id": iid, "category_id": CLASSES.index(c) + 1, "bbox": [round(x, 1), round(y, 1), round(bw, 1), round(bh, 1)],
                             "area": round(bw * bh, 1), "iscrowd": 0})
        (a.out / split / "_annotations.coco.json").write_text(json.dumps({"categories": [{"id": i + 1, "name": c} for i, c in enumerate(CLASSES)], "images": imgs, "annotations": anns}), encoding="utf-8")
        print(f"{split}: {len(imgs)} imagens, {len(anns)} caixas {dict(Counter(CLASSES[x['category_id'] - 1] for x in anns))}")
    for n in sorted(val_names):
        os.link(a.out / "valid" / n, a.out / "test" / n)
    shutil.copy(a.out / "valid" / "_annotations.coco.json", a.out / "test" / "_annotations.coco.json")


if __name__ == "__main__":
    main()
