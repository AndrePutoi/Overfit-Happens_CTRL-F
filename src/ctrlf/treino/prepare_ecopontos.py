"""Prepara o export COCO do CVAT (Porto) para treinar o detetor de ecopontos: `contentor` (superfície) vs `subterraneo`.

    python -m ctrlf.treino.prepare_ecopontos data/annotations/<export_porto_completo> data/ecopontos_coco
    python -m ctrlf.treino.train_detector --dataset data/ecopontos_coco --size small --epochs 30

Entrada : pasta extraída do zip do CVAT (COCO 1.0): annotations/instances_*.json + images/
Saída   : <dst>/train/ , <dst>/valid/ , <dst>/test/  (cada um com _annotations.coco.json + imagens), formato do train_detector.py.

* Divisão 80/20 ALEATÓRIA mas POR PANORAMA: as 4 vistas `<pano>_y0/90/180/270` ficam sempre do mesmo lado
  (são quase a mesma cena; separá-las inflacionaria a validação).  Imagens sem caixas (negativos) entram na divisão.
* `test` é cópia de `valid`: o teste a sério será Aveiro, anotado à parte.
* Só mantém as classes pedidas (por omissão `contentor` e `subterraneo`).
"""
from __future__ import annotations

import argparse
import json
import random
import re
import shutil
from collections import Counter, defaultdict
from pathlib import Path

KEEP = ("contentor", "subterraneo")


def group_of(name: str) -> str:
    return re.sub(r"_y\d+(?=\.[A-Za-z]+$)", "", name).rsplit(".", 1)[0]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--val", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--classes", nargs="+", default=list(KEEP))
    a = ap.parse_args()

    js = sorted((a.src / "annotations").glob("instances_*.json"))
    if not js:
        raise SystemExit(f"sem annotations/instances_*.json em {a.src}")
    d = json.loads(js[0].read_text(encoding="utf-8"))
    cats = [c for c in d["categories"] if c["name"] in a.classes]
    missing = set(a.classes) - {c["name"] for c in cats}
    if missing:
        raise SystemExit(f"classes em falta no export: {missing}; há {[c['name'] for c in d['categories']]}")
    new_id = {c["id"]: i + 1 for i, c in enumerate(sorted(cats, key=lambda c: a.classes.index(c["name"])))}
    out_cats = [{"id": new_id[c["id"]], "name": c["name"]} for c in cats]

    by_img = defaultdict(list)
    for an in d["annotations"]:
        if an["category_id"] in new_id:
            by_img[an["image_id"]].append(an)

    groups = defaultdict(list)
    for im in d["images"]:
        groups[group_of(Path(im["file_name"]).name)].append(im)
    keys = sorted(groups)
    random.Random(a.seed).shuffle(keys)
    n_val = max(1, round(len(keys) * a.val))
    split = {"valid": keys[:n_val], "train": keys[n_val:]}

    img_dir = a.src / "images"
    if a.dst.exists():
        shutil.rmtree(a.dst)
    for name, ks in split.items():
        (a.dst / name).mkdir(parents=True)
        images, anns = [], []
        for k in ks:
            for im in groups[k]:
                base = Path(im["file_name"]).name           # o CVAT pode exportar "porto/xxx.jpg"
                src = next(img_dir.rglob(base), None)
                if src is None:
                    raise SystemExit(f"imagem em falta: {im['file_name']}")
                shutil.copy(src, a.dst / name / base)
                nid = len(images) + 1
                images.append({**im, "id": nid, "file_name": base})
                for an in by_img[im["id"]]:
                    anns.append({k2: v for k2, v in an.items() if k2 != "segmentation"} | {
                        "id": len(anns) + 1, "image_id": nid, "category_id": new_id[an["category_id"]]})
        (a.dst / name / "_annotations.coco.json").write_text(
            json.dumps({"categories": out_cats, "images": images, "annotations": anns}), encoding="utf-8")
        cnt = Counter(c["name"] for an in anns for c in out_cats if c["id"] == an["category_id"])
        print(f"{name:6s}: {len(ks):4d} panoramas | {len(images):4d} imagens | {len(anns):4d} caixas | {dict(cnt)} | "
              f"sem caixas: {sum(1 for i in images if not any(x['image_id'] == i['id'] for x in anns))}")
    shutil.copytree(a.dst / "valid", a.dst / "test")
    print(f"-> {a.dst}  (test = cópia de valid)")


if __name__ == "__main__":
    main()
