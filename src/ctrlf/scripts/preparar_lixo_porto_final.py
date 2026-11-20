"""Anotações FINAIS do lixo do Porto (final_lixo_annotations.zip) -> conjunto de deteção SÓ com o Porto: contentor / subterraneo (2 classes).

    python -m ctrlf.scripts.preparar_lixo_porto_final [--zip final_lixo_annotations.zip]   ->  data/porto_lixo_final_coco/{train,valid,test}

- SEM PAPELEIRAS (decisão do utilizador, 2026-11-20): todas as anotações `papeleira` são retiradas e a classe deixa de existir. As imagens ficam; a papeleira passa a ser fundo, como qualquer
  outro objeto que não é contentor nem subterrâneo (imagens que só tinham papeleiras viram negativos).
- Só o Porto: nada de Aveiro, Lisboa nem waste_container. Todas as imagens do zip entram; as SEM caixas são negativos (o utilizador entregou-as como anotações finais).
- Divisão por panorama com a MESMA regra e semente de prepare_ecopontos.py / preparar_lixo_v3.py (as 4 vistas no mesmo lado, 20 % para validação): os grupos de validação
  coincidem com os de ecopontos3_coco, logo os modelos antigo e novo comparam-se nas mesmas imagens (as ANOTAÇÕES da validação mudaram: são as finais). test = cópia de valid.
- As imagens vêm SEMPRE de data/images_anon e só se o sha256 bater com o manifesto de anonimização (falha fechada).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

from PIL import Image

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.treino.prepare_ecopontos import group_of  # noqa: E402

ANON = ROOT / "data" / "images_anon"
CLASSES = ["contentor", "subterraneo"]
EXCLUIR = {"papeleira"}                  # classes do zip que se ignoram (anotações retiradas)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", type=Path, default=ROOT / "final_lixo_annotations.zip")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "porto_lixo_final_coco")
    ap.add_argument("--val", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--recortes", action="store_true", help="além do conjunto de deteção, gera os RECORTES com tipo (fluxo) para o classificador: data/crops/fluxo4/porto_final/")
    a = ap.parse_args()
    manifest = {}
    for l in (ANON / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            d = json.loads(l); manifest[d["file"]] = d["sha256"]
    z = zipfile.ZipFile(a.zip)
    d = json.loads(z.read("annotations/instances_default.json"))
    cat = {c["id"]: c["name"] for c in d["categories"]}
    assert set(cat.values()) <= set(CLASSES) | EXCLUIR, f"classes inesperadas: {sorted(cat.values())}"
    nome = {i["id"]: Path(i["file_name"]).name for i in d["images"]}
    items = {n: [] for n in nome.values()}
    retiradas = Counter()
    for an in d["annotations"]:
        if cat[an["category_id"]] in EXCLUIR:
            retiradas[cat[an["category_id"]]] += 1
            continue
        items[nome[an["image_id"]]].append((cat[an["category_id"]], *an["bbox"]))
    print(f"anotações retiradas (classes excluídas): {dict(retiradas)}")
    falta = [n for n in items if n not in manifest or not (ANON / n).exists()]
    assert not falta, f"{len(falta)} imagens sem anonimização/manifesto: {falta[:3]}"
    print(f"{len(items)} imagens, {sum(1 for v in items.values() if not v)} sem caixas (negativos), caixas {dict(Counter(c for v in items.values() for c, *_ in v))}")

    groups = defaultdict(list)
    for n in sorted(items):
        groups[group_of(n)].append(n)
    keys = sorted(groups)
    random.Random(a.seed).shuffle(keys)
    n_val = max(1, round(len(keys) * a.val))
    split = {"valid": keys[:n_val], "train": keys[n_val:]}
    if a.out.exists():
        shutil.rmtree(a.out)
    for sp, ks in split.items():
        (a.out / sp).mkdir(parents=True)
        imgs, anns = [], []
        for k in ks:
            for n in groups[k]:
                src = ANON / n
                assert hashlib.sha256(src.read_bytes()).hexdigest() == manifest[n], f"{n}: sha256 não bate com o manifesto"
                shutil.copy(src, a.out / sp / n)
                w, h = Image.open(src).size
                iid = len(imgs) + 1
                imgs.append({"id": iid, "file_name": n, "width": w, "height": h})
                for c, x, y, bw, bh in items[n]:
                    anns.append({"id": len(anns) + 1, "image_id": iid, "category_id": CLASSES.index(c) + 1, "bbox": [round(x, 1), round(y, 1), round(bw, 1), round(bh, 1)], "area": round(bw * bh, 1), "iscrowd": 0})
        (a.out / sp / "_annotations.coco.json").write_text(json.dumps({"categories": [{"id": i + 1, "name": c} for i, c in enumerate(CLASSES)], "images": imgs, "annotations": anns}), encoding="utf-8")
        print(f"{sp:6s}: {len(imgs)} imagens | {len(anns)} caixas {dict(Counter(CLASSES[x['category_id'] - 1] for x in anns))} | {sum(1 for i in imgs if not any(x['image_id'] == i['id'] for x in anns))} negativas")
    shutil.copytree(a.out / "valid", a.out / "test")
    if a.recortes:
        TIPOS = ("indiferenciado", "papel", "embalagens", "vidro")
        dest = ROOT / "data" / "crops" / "fluxo4" / "porto_final"
        if dest.exists():
            shutil.rmtree(dest)
        man = []
        por_img = defaultdict(list)
        for an in d["annotations"]:
            if cat[an["category_id"]] in ("contentor", "subterraneo") and (an.get("attributes") or {}).get("fluxo") in TIPOS:
                por_img[nome[an["image_id"]]].append(an)
        for im, L in sorted(por_img.items()):
            img = Image.open(ANON / im).convert("RGB")
            for k, an in enumerate(L):
                x, y, w, h = an["bbox"]
                m = 0.08 * max(w, h)                                                 # a mesma margem de 8 % do classificador anterior
                crop = img.crop((max(0, int(x - m)), max(0, int(y - m)), min(img.width, int(x + w + m)), min(img.height, int(y + h + m))))
                tipo = an["attributes"]["fluxo"]
                (dest / tipo).mkdir(parents=True, exist_ok=True)
                fn = f"{Path(im).stem}_{k}.jpg"
                crop.save(dest / tipo / fn, quality=95)
                man.append({"file": f"{tipo}/{fn}", "imagem": im, "grupo": group_of(im), "bbox": [round(v, 1) for v in an["bbox"]], "tipo": tipo, "classe": cat[an["category_id"]]})
        (dest / "manifesto.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"recortes com tipo: {len(man)} em {len(por_img)} imagens {dict(Counter(m['tipo'] for m in man))} -> {dest.relative_to(ROOT)}")
    try:
        antigo = {i["file_name"] for i in json.loads((ROOT / "data" / "ecopontos3_coco" / "valid" / "_annotations.coco.json").read_text(encoding="utf-8"))["images"]}
        novo = {i["file_name"] for i in json.loads((a.out / "valid" / "_annotations.coco.json").read_text(encoding="utf-8"))["images"]}
        print("validação igual à de ecopontos3_coco:", antigo == novo, f"(comuns {len(antigo & novo)})")
    except FileNotFoundError:
        pass


if __name__ == "__main__":
    main()
