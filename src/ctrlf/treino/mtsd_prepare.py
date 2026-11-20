"""Prepara os recortes do MTSD v2 (totalmente anotado) para o classificador hierárquico de sinais (Plano B).

    python -m ctrlf.treino.mtsd_prepare \
        [--aveiro-dets .../detections.json --aveiro-images .../images/kartaview]

Lê as anotações em data/external/mapillary_mtsd/extracted/ e as imagens DIRETAMENTE dos zips em
data/external/mapillary_mtsd/_zips/ (não é preciso extrair os ~36 GB).  Escreve:

    data/crops/mtsd/router/{train,val}/<grupo>/*.jpg                 grupos: regulamentacao, perigo, informacao,
                                                                      complementar, orientacao_outros, nao_sinal
    data/crops/mtsd/esp_<familia>/{train,val}/<tipo>/*.jpg           um especialista por família com tipos
    data/crops/mtsd/meta.json                                        rótulos, contagens e parâmetros
    models/hier_sinal_mtsd/manifest.json                             manifesto do HierClassifier (checkpoints vêm do treino)

Decisões (ver docs/PLANO_B.md §3):
  * Família = prefixo do rótulo MTSD (regulatory / warning / information / complementary / other-sign).
  * Tipo = rótulo sem a variante gráfica "--gN" (257 tipos).  Tipos com poucos exemplos
    (treino < TYPE_MIN_TRAIN ou val < TYPE_MIN_VAL) agrupam-se em "<familia>_outro".
  * `other-sign` -> grupo `orientacao_outros` (inclui pórticos de orientação).  Os marcados `ambiguous` ficam de fora.
  * `nao_sinal` = (a) regiões de fundo das próprias imagens MTSD sem nenhum objeto anotado e (b) opcionalmente recortes
    de candeeiros/postes/contentores de Aveiro (negativos difíceis, a mesma distribuição do deployment).
  * Ignora caixas com lado < MIN_SIDE px, `out-of-frame`, `dummy` e panoramas 360°.
  * Treino usa o split train do MTSD; val usa o split val.  O split test do MTSD não tem anotações.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import random
import re
import shutil
import zipfile
from collections import Counter, defaultdict
from multiprocessing import Pool
from pathlib import Path

from PIL import Image, ImageOps

from ctrlf.paths import ROOT
MTSD = ROOT / "data" / "external" / "mapillary_mtsd"
ZIPS = MTSD / "_zips"
ANN = MTSD / "extracted" / "mtsd_v2_fully_annotated"
OUT = ROOT / "data" / "crops" / "mtsd"
MODEL_DIR = ROOT / "models" / "hier_sinal_mtsd"

FAMILY = {"regulatory": "regulamentacao", "warning": "perigo", "information": "informacao",
          "complementary": "complementar"}
OTHER, NEG = "orientacao_outros", "nao_sinal"
SEED, MIN_SIDE, PAD, MAX_SIDE = 0, 24, 0.15, 256
TYPE_MIN_TRAIN, TYPE_MIN_VAL = 50, 5
TYPE_CAP = {"train": 800, "val": 250}          # recortes por tipo
ROUTER_CAP = {"train": 9000, "val": 1500}      # recortes por grupo do router


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def load_annotations():
    split_of = {}
    for s in ("train", "val"):
        for k in (ANN / "splits" / f"{s}.txt").read_text().split():
            split_of[k] = s
    images, n_pano = {}, 0
    for f in sorted((ANN / "annotations").glob("*.json")):
        sp = split_of.get(f.stem)
        if sp is None:
            continue
        d = json.loads(f.read_text())
        if d.get("ispano"):
            n_pano += 1
            continue
        objs = [(o["label"], (o["bbox"]["xmin"], o["bbox"]["ymin"], o["bbox"]["xmax"], o["bbox"]["ymax"]),
                 o.get("properties", {})) for o in d["objects"]]
        images[f.stem] = (sp, d["width"], d["height"], objs)
    print(f"anotações: {len(images)} imagens (panoramas ignorados: {n_pano})")
    return images


def valid(label, box, pr):
    w, h = box[2] - box[0], box[3] - box[1]
    if w <= 0 or h <= 0 or min(w, h) < MIN_SIDE or pr.get("out-of-frame") or pr.get("dummy"):
        return False
    return not (label == "other-sign" and pr.get("ambiguous"))


def inter(a, b):
    return max(0.0, min(a[2], b[2]) - max(a[0], b[0])) * max(0.0, min(a[3], b[3]) - max(a[1], b[1]))


def area(a):
    return max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])


def plan(images, rng):
    """Devolve {(key, idx): {"box":..., "dests":[relpath...]}} e o resumo."""
    cand = defaultdict(list)                     # (split, grupo) -> [(key, idx, tipo|None)]
    tcount = {"train": Counter(), "val": Counter()}
    sizes = []
    for key, (sp, w, h, objs) in sorted(images.items()):
        for i, (lab, box, pr) in enumerate(objs):
            if not valid(lab, box, pr):
                continue
            raw = lab.split("--")[0]
            sizes.append((box[2] - box[0], box[3] - box[1]))
            if raw == "other-sign":
                cand[(sp, OTHER)].append((key, i, None))
            elif raw in FAMILY:
                t = norm("--".join(lab.split("--")[:2]))
                cand[(sp, FAMILY[raw])].append((key, i, (raw, t)))
                tcount[sp][(raw, t)] += 1

    keep = {k for k, n in tcount["train"].items() if n >= TYPE_MIN_TRAIN and tcount["val"][k] >= TYPE_MIN_VAL}
    crops: dict = {}

    def add(key, idx, box, rel):
        crops.setdefault((key, idx), {"box": box, "dests": []})["dests"].append(rel)

    spec_pool = defaultdict(list)                # (split, grupo) -> [(key, idx, label)]
    for (sp, fam), items in cand.items():
        if fam == OTHER:
            continue
        by_label = defaultdict(list)
        for key, i, (raw, t) in items:
            lab = t if (raw, t) in keep else f"{raw}_outro"
            by_label[lab].append((key, i, lab))
        for lab, lst in sorted(by_label.items()):
            if lab.endswith("_outro"):
                nt = sum(1 for _ in lst)
                if sp == "train" and nt < TYPE_MIN_TRAIN:
                    continue
            rng.shuffle(lst)
            for key, i, lb in lst[:TYPE_CAP[sp]]:
                spec_pool[(sp, fam)].append((key, i, lb))
    # um "_outro" sem exemplos suficientes em val também sai (ImageFolder exige as mesmas classes em train e val)
    for fam in set(f for _, f in spec_pool):
        tr = Counter(l for _, _, l in spec_pool[("train", fam)])
        va = Counter(l for _, _, l in spec_pool[("val", fam)])
        bad = {l for l in tr if va[l] == 0} | {l for l in va if tr[l] == 0}
        for sp in ("train", "val"):
            spec_pool[(sp, fam)] = [x for x in spec_pool[(sp, fam)] if x[2] not in bad]

    for (sp, fam), lst in sorted(spec_pool.items()):
        for key, i, lab in lst:
            add(key, i, images[key][3][i][1], f"esp_{fam}/{sp}/{lab}/{key}_{i}.jpg")
        pool = list(lst)
        rng.shuffle(pool)
        for key, i, lab in pool[:ROUTER_CAP[sp]]:
            add(key, i, images[key][3][i][1], f"router/{sp}/{fam}/{key}_{i}.jpg")
    for sp in ("train", "val"):
        pool = list(cand[(sp, OTHER)])
        rng.shuffle(pool)
        for key, i, _ in pool[:ROUTER_CAP[sp]]:
            add(key, i, images[key][3][i][1], f"router/{sp}/{OTHER}/{key}_{i}.jpg")
    return crops, sizes


def plan_background(images, sizes, n_bg, rng, crops):
    """Regiões de fundo sem objetos anotados, com a distribuição de tamanhos dos sinais."""
    for sp, n in n_bg.items():
        keys = sorted(k for k, v in images.items() if v[0] == sp)
        made, tries = 0, 0
        while made < n and tries < n * 40:
            tries += 1
            key = rng.choice(keys)
            _, W, H, objs = images[key]
            w, h = rng.choice(sizes)
            if w >= W * 0.9 or h >= H * 0.9:
                continue
            x1 = rng.uniform(0, W - w)
            y1 = rng.uniform(H * 0.25, max(H * 0.25, H - h))
            box = (x1, y1, x1 + w, y1 + h)
            if y1 + h > H:
                continue
            if any(inter(box, o[1]) / area(box) > 0.02 or inter(box, o[1]) / max(area(o[1]), 1e-9) > 0.05
                   for o in objs):
                continue
            idx = f"n{made}"
            crops.setdefault((key, idx), {"box": box, "dests": []})["dests"].append(f"router/{sp}/{NEG}/{key}_{idx}.jpg")
            made += 1
        print(f"fundo {sp}: {made}/{n}")


def crop_img(im: Image.Image, box):
    x1, y1, x2, y2 = box
    p = PAD * max(x2 - x1, y2 - y1)
    c = im.crop((int(max(0, x1 - p)), int(max(0, y1 - p)), int(min(im.width, x2 + p)), int(min(im.height, y2 + p))))
    if max(c.size) > MAX_SIDE:
        s = MAX_SIDE / max(c.size)
        c = c.resize((max(1, round(c.width * s)), max(1, round(c.height * s))), Image.LANCZOS)
    return c


def save_with_links(c: Image.Image, rels: list[str]):
    first = OUT / rels[0]
    first.parent.mkdir(parents=True, exist_ok=True)
    c.save(first, quality=92)
    for r in rels[1:]:
        d = OUT / r
        d.parent.mkdir(parents=True, exist_ok=True)
        os.link(first, d)


_ZF: dict = {}


def work(task):
    zpath, member, size, items = task
    zf = _ZF.get(zpath) or _ZF.setdefault(zpath, zipfile.ZipFile(zpath))
    im = Image.open(io.BytesIO(zf.read(member)))
    im.load()
    if im.size != size:
        im2 = ImageOps.exif_transpose(im)
        if im2.size != size:
            return 0, 1
        im = im2
    im = im.convert("RGB")
    for box, rels in items:
        save_with_links(crop_img(im, box), rels)
    return len(items), 0


def aveiro_negatives(dets_json: Path, img_dir: Path, rng) -> Counter:
    """Candeeiros/postes/contentores de Aveiro (imagens já desfocadas) como negativos difíceis do router."""
    data = json.loads(dets_json.read_text())
    ids = sorted(im["id"] for im in data["images"])
    split_of = {i: ("val" if n % 5 == 0 else "train") for n, i in enumerate(ids)}   # por imagem, nunca partilhada
    cnt = Counter()
    for im in data["images"]:
        p = img_dir / f"{im['id']}.jpg"
        if not p.exists():
            continue
        src = None
        for d in im["detections"]:
            if d["cls"] not in ("candeeiro", "poste", "contentor"):
                continue
            b = d["bbox"]
            if min(b[2] - b[0], b[3] - b[1]) < MIN_SIDE:
                continue
            src = src or Image.open(p).convert("RGB")
            sp = split_of[im["id"]]
            save_with_links(crop_img(src, b), [f"router/{sp}/{NEG}/av_{im['id']}_{d['i']}.jpg"])
            cnt[sp] += 1
    print("negativos de Aveiro:", dict(cnt))
    return cnt


def write_meta_and_manifest():
    meta = {"params": {"MIN_SIDE": MIN_SIDE, "PAD": PAD, "TYPE_MIN_TRAIN": TYPE_MIN_TRAIN, "TYPE_MIN_VAL": TYPE_MIN_VAL,
                       "TYPE_CAP": TYPE_CAP, "ROUTER_CAP": ROUTER_CAP, "SEED": SEED},
            "models": {}}
    for mdir in sorted(p for p in OUT.iterdir() if p.is_dir()):
        labels = sorted(d.name for d in (mdir / "train").iterdir() if d.is_dir())
        meta["models"][mdir.name] = {"labels": labels, "counts": {
            sp: {l: len(list((mdir / sp / l).glob("*.jpg"))) for l in labels} for sp in ("train", "val")}}
    (OUT / "meta.json").write_text(json.dumps(meta, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")

    router = meta["models"]["router"]["labels"]
    groups, specs = {}, {}
    for g in router:
        if g in (NEG, OTHER):
            groups[g] = {"family": g, "leaf": g}
        else:
            groups[g] = {"family": g, "specialist": f"esp_{g}"}
            specs[f"esp_{g}"] = {"checkpoint": f"esp_{g}.pt", "labels": meta["models"][f"esp_{g}"]["labels"]}
    man = {"version": 1, "synthetic": False,
           "note": "Treinado com MTSD v2 (CC BY-NC-SA, uso não comercial) + negativos de Aveiro. "
                   "Folhas = tipo MTSD sem variante gráfica. C1 (contrato) pendente.",
           "source": {"dataset": "MTSD v2 fully annotated", "meta": "data/crops/mtsd/meta.json"},
           "router": {"checkpoint": "router.pt", "labels": router}, "groups": groups, "specialists": specs}
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    (MODEL_DIR / "manifest.json").write_text(json.dumps(man, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    from ctrlf.detection.subclass.hier_classifier import validate_manifest
    validate_manifest(man, "manifest.json (MTSD)")
    print("manifesto válido ->", MODEL_DIR / "manifest.json")
    for name, m in meta["models"].items():
        print(f"  {name}: {len(m['labels'])} classes, treino {sum(m['counts']['train'].values())}, "
              f"val {sum(m['counts']['val'].values())}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--aveiro-dets", type=Path)
    ap.add_argument("--aveiro-images", type=Path)
    ap.add_argument("--workers", type=int, default=8)
    a = ap.parse_args()
    if OUT.exists():
        shutil.rmtree(OUT)
    rng = random.Random(SEED)
    images = load_annotations()
    crops, sizes = plan(images, rng)
    n_av = Counter()
    if a.aveiro_dets and a.aveiro_images:
        n_av = aveiro_negatives(a.aveiro_dets, a.aveiro_images, rng)
    plan_background(images, sizes, {sp: ROUTER_CAP[sp] - n_av[sp] for sp in ("train", "val")}, rng, crops)

    by_key = defaultdict(list)
    for (key, _), v in crops.items():
        by_key[key].append((v["box"], v["dests"]))
    tasks, missing = [], set(by_key)
    for z in sorted(ZIPS.glob("mtsd_v2_fully_annotated_images.*.zip")):
        with zipfile.ZipFile(z) as zf:
            for n in zf.namelist():
                k = Path(n).stem
                if k in by_key:
                    missing.discard(k)
                    tasks.append((str(z), n, (images[k][1], images[k][2]), by_key[k]))
    print(f"imagens a processar: {len(tasks)} | recortes: {sum(len(t[3]) for t in tasks)} | sem imagem: {len(missing)}")
    done = bad = 0
    with Pool(a.workers) as pool:
        for i, (n, b) in enumerate(pool.imap_unordered(work, tasks, chunksize=8), 1):
            done += n
            bad += b
            if i % 2000 == 0:
                print(f"  {i}/{len(tasks)} imagens, {done} recortes")
    print(f"recortes gravados: {done} | imagens com tamanho incoerente (ignoradas): {bad}")
    write_meta_and_manifest()


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    main()
