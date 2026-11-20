"""MTSD v2 -> COCO de DETEÇÃO com as 5 classes do router (não as ~300 classes), para treinar o RF-DETR.

    python -m ctrlf.treino.mtsd_detection_coco --n-train 8000 --n-val 1500
    python -m ctrlf.treino.train_detector --dataset data/mtsd_det --size small --resolution 768 \
        --batch 2 --accum 8 --epochs 10 --out models/detector_sinais

Classes: regulamentacao, perigo, informacao, complementar, orientacao_outros (= `other-sign` do MTSD, que inclui os
painéis de orientação).  `nao_sinal` não é classe de deteção: os negativos (lojas, publicidade...) vêm depois, das
correções do CVAT.  Mesmos filtros do mtsd_prepare.valid(): lado >= 24 px (na imagem original), sem `out-of-frame`,
`dummy` nem `ambiguous` em other-sign; panoramas 360° ficam de fora.

Subconjunto: --n-train / --n-val imagens, amostradas com preferência pelas que contêm grupos RAROS (complementar,
informacao, perigo), para o detetor não ser só `regulamentacao` e `orientacao_outros`.  Lê as imagens DIRETAMENTE dos zips,
reduz para no máximo --max-side px (os rótulos são reescalados) e grava em data/mtsd_det/{train,valid,test}/.
`test` são hard-links de `valid` (o teste a sério é Porto/Lisboa/Aveiro anotados no CVAT).
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import shutil
import sys
import zipfile
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

from PIL import Image, ImageOps

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.treino.mtsd_prepare import FAMILY, OTHER, ZIPS, load_annotations, valid  # noqa: E402

GROUPS = ["regulamentacao", "perigo", "informacao", "complementar", "orientacao_outros"]
OUT = ROOT / "data" / "mtsd_det"
_ZF: dict = {}


def group_of(label: str) -> str | None:
    raw = label.split("--")[0]
    return OTHER if raw == "other-sign" else FAMILY.get(raw)


def work(task):
    zpath, member, name, size, max_side, boxes, dst = task
    zf = _ZF.get(zpath) or _ZF.setdefault(zpath, zipfile.ZipFile(zpath))
    im = Image.open(io.BytesIO(zf.read(member)))
    if im.size != size:
        im = ImageOps.exif_transpose(im)
        if im.size != size:
            return name, None
    W, H = size
    s = min(1.0, max_side / max(W, H))
    out = (max(1, round(W * s)), max(1, round(H * s)))
    if s < 1.0:
        im.draft("RGB", out)                    # decodificação JPEG mais rápida (escala 1/2, 1/4...)
    im = im.convert("RGB")
    if im.size != out:
        im = im.resize(out, Image.LANCZOS)
    im.save(Path(dst) / name, quality=90)
    sx, sy = out[0] / W, out[1] / H
    return name, {"size": out, "boxes": [(g, (b[0] * sx, b[1] * sy, b[2] * sx, b[3] * sy)) for g, b in boxes]}


def pick(images, split, n, rng):
    """Amostra n imagens do split, favorecendo as que têm grupos raros."""
    cand = {}
    for key, (sp, W, H, objs) in images.items():
        if sp != split:
            continue
        bx = [(group_of(lab), b) for lab, b, pr in objs if valid(lab, b, pr) and group_of(lab)]
        if bx:
            cand[key] = bx
    freq = Counter(g for bx in cand.values() for g in {g for g, _ in bx})
    ks = list(cand)
    # Efraimidis-Spirakis: chave = u^(1/w); w = maior raridade (1/frequência) dos grupos da imagem
    w = {k: max(1.0 / freq[g] for g, _ in cand[k]) for k in ks}
    mw = max(w.values())
    ks.sort(key=lambda k: -(rng.random() ** (mw / w[k])))
    return {k: cand[k] for k in ks[:n]}, freq


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-train", type=int, default=8000)
    ap.add_argument("--n-val", type=int, default=1500)
    ap.add_argument("--max-side", type=int, default=1280)
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()

    rng = random.Random(a.seed)
    images = load_annotations()
    if OUT.exists():
        shutil.rmtree(OUT)
    plan = {}
    for split, name, n in (("train", "train", a.n_train), ("val", "valid", a.n_val)):
        (OUT / name).mkdir(parents=True)
        chosen, freq = pick(images, split, n, rng)
        plan[name] = chosen
        print(f"{name}: {len(chosen)} imagens escolhidas (imagens com cada grupo no split: {dict(freq)})")

    index = {}
    for z in sorted(ZIPS.glob("mtsd_v2_fully_annotated_images.*.zip")):
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                index[Path(n).stem] = (str(z), n)

    for name, chosen in plan.items():
        tasks, miss = [], 0
        for key, bx in chosen.items():
            if key not in index:
                miss += 1
                continue
            z, member = index[key]
            tasks.append((z, member, key + ".jpg", (images[key][1], images[key][2]), a.max_side, bx, str(OUT / name)))
        cats = [{"id": i + 1, "name": g} for i, g in enumerate(GROUPS)]
        coco_i, coco_a, bad = [], [], 0
        with Pool(a.workers) as pool:
            for n, (fname, r) in enumerate(pool.imap_unordered(work, tasks, chunksize=8), 1):
                if r is None:
                    bad += 1
                    continue
                iid = len(coco_i) + 1
                coco_i.append({"id": iid, "file_name": fname, "width": r["size"][0], "height": r["size"][1]})
                for g, (x1, y1, x2, y2) in r["boxes"]:
                    coco_a.append({"id": len(coco_a) + 1, "image_id": iid, "category_id": GROUPS.index(g) + 1,
                                   "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                                   "area": round((x2 - x1) * (y2 - y1), 1), "iscrowd": 0})
                if n % 500 == 0:
                    print(f"  {name}: {n}/{len(tasks)}", flush=True)
        (OUT / name / "_annotations.coco.json").write_text(
            json.dumps({"categories": cats, "images": coco_i, "annotations": coco_a}), encoding="utf-8")
        cnt = Counter(GROUPS[x["category_id"] - 1] for x in coco_a)
        print(f"{name}: {len(coco_i)} imagens | {len(coco_a)} caixas | {dict(cnt)} | sem zip: {miss} | tamanho inesperado: {bad}")

    (OUT / "test").mkdir()
    for f in (OUT / "valid").iterdir():
        os.link(f, OUT / "test" / f.name)
    print(f"-> {OUT}  (test = hard-links de valid)")


if __name__ == "__main__":
    main()
