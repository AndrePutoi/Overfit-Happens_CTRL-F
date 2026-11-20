"""Open Images V7 -> dois conjuntos de DETEÇÃO de uma classe (rostos; matrículas) para treinar RF-DETR (substitui os YOLO da privacidade).

    python -m ctrlf.scripts.preparar_privacidade_oi --oi <pasta com os CSV do Open Images> [--ver]     # --ver: só conta, não descarrega

Porquê DOIS detetores e não um de 2 classes: o Open Images só anota uma classe numa imagem quando ela foi verificada para essa imagem. Nas imagens com matrícula, 98 % não têm o
rosto verificado (e vice-versa): um modelo de 2 classes aprenderia que rostos/matrículas não anotados são fundo, o pior erro num portão de privacidade. Cada conjunto usa SÓ imagens
onde a sua classe foi verificada.

Regras (para cada classe K):
  positivos : imagens com caixas de K, sem nenhuma caixa K marcada IsGroupOf ou IsDepiction (desenhos/multidões têm rótulos duvidosos), sem rotação EXIF, licença CC BY.
  negativos : imagens com K verificado como AUSENTE (confiança 0 ao nível da imagem). Matrículas: só as que têm carro/veículo (negativos difíceis).
  divisões  : as do Open Images (train / validation / test) — a validação serve para escolher o ponto de treino, o teste só para o relatório final.
Imagens: espelho S3 do Open Images (<= 1024 px de lado maior). Licenças/autores ficam em <cache>/LICENCAS.csv (CC BY exige atribuição).
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import shutil
import statistics
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

from ctrlf.paths import ROOT
FACE, PLATE, CAR, LANDVEH = "/m/0dzct", "/m/01jfm_", "/m/0k4j", "/m/01prls"
ALVOS = {"rostos": (FACE, "rosto"), "matriculas": (PLATE, "matricula")}
S3 = "https://open-images-dataset.s3.amazonaws.com/{split}/{id}.jpg"
# (n_pos, n_neg) por divisão; None = todas
PLANO = {
    "rostos":     {"train": (5000, 600), "validation": (500, 100), "test": (800, 200)},
    "matriculas": {"train": (None, 1500), "validation": (None, 150), "test": (1000, 300)},
}
FICH = {"train": ("oidv6-train-annotations-bbox.csv", "train-images-boxable-with-rotation.csv", "train-imagelabels.csv"),
        "validation": ("validation-annotations-bbox.csv", "validation-images-with-rotation.csv", "validation-imagelabels.csv"),
        "test": ("test-annotations-bbox.csv", "test-images-with-rotation.csv", "test-imagelabels.csv")}


def carregar_split(oi: Path, sp: str):
    f_box, f_img, f_lab = (oi / n for n in FICH[sp])
    lab = defaultdict(dict)                                   # imagem -> {classe: confiança 0/1}
    for r in csv.DictReader(open(f_lab, encoding="utf-8")):
        if r["LabelName"] in (FACE, PLATE, CAR, LANDVEH):
            lab[r["ImageID"]][r["LabelName"]] = int(float(r["Confidence"]))
    boxes = defaultdict(lambda: defaultdict(list))            # imagem -> classe -> [(x0,x1,y0,y1)]
    ruins = defaultdict(set)                                  # imagem -> classes com caixa de grupo/desenho
    for r in csv.DictReader(open(f_box, encoding="utf-8")):
        k = r["LabelName"]
        if k not in (FACE, PLATE):
            continue
        if r["IsGroupOf"] == "1" or r["IsDepiction"] == "1":
            ruins[r["ImageID"]].add(k)
        boxes[r["ImageID"]][k].append(tuple(float(r[c]) for c in ("XMin", "XMax", "YMin", "YMax")))
    return lab, boxes, ruins, f_img


def escolher(alvo: str, sp: str, oi: Path, rng: random.Random):
    K, _ = ALVOS[alvo]
    lab, boxes, ruins, f_img = carregar_split(oi, sp)
    pos = [i for i, b in boxes.items() if K in b and K not in ruins[i] and lab.get(i, {}).get(K) != 0]
    neg = [i for i, d in lab.items() if d.get(K) == 0 and K not in boxes.get(i, {})]
    if alvo == "matriculas":
        neg = [i for i in neg if lab[i].get(CAR) == 1 or lab[i].get(LANDVEH) == 1]
    n_pos, n_neg = PLANO[alvo][sp]
    rng.shuffle(pos)
    rng.shuffle(neg)
    if n_pos and len(pos) > n_pos:
        if alvo == "rostos":          # a vista de rua tem rostos pequenos: 60 % das imagens vêm das de rostos mais pequenos
            alt = {i: statistics.median(b[3] - b[2] for b in boxes[i][K]) for i in pos}
            peq = sorted(pos, key=lambda i: alt[i])[: len(pos) // 4]
            n_peq = int(0.6 * n_pos)
            pick = peq[:n_peq]
            resto = [i for i in pos if i not in set(pick)]
            pos = pick + resto[: n_pos - len(pick)]
        else:
            pos = pos[:n_pos]
    neg = neg[:n_neg]
    quer = set(pos) | set(neg)
    meta = {}
    for r in csv.DictReader(open(f_img, encoding="utf-8")):
        if r["ImageID"] in quer:
            meta[r["ImageID"]] = r
    def ok(i):
        m = meta.get(i)
        return bool(m) and "creativecommons.org/licenses/by/" in m["License"] and (m.get("Rotation") or "0") in ("", "0", "0.0")
    return [i for i in pos if ok(i)], [i for i in neg if ok(i)], boxes, meta


def baixar(sp: str, iid: str, destino: Path) -> tuple[int, int] | None:
    f = destino / sp / f"{iid}.jpg"
    f.parent.mkdir(parents=True, exist_ok=True)
    for t in range(4):
        try:
            if not f.exists() or f.stat().st_size < 1000:
                b = urllib.request.urlopen(urllib.request.Request(S3.format(split=sp, id=iid), headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read()
                f.write_bytes(b)
            with Image.open(f) as im:
                return im.size
        except Exception:
            time.sleep(1 + t)
    f.unlink(missing_ok=True)
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--oi", type=Path, required=True)
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "oi_cache")
    ap.add_argument("--out", type=Path, default=ROOT / "data")
    ap.add_argument("--ver", action="store_true", help="só conta o que entraria")
    ap.add_argument("--so", choices=list(ALVOS), default=None)
    ap.add_argument("--threads", type=int, default=16)
    a = ap.parse_args()
    rng = random.Random(0)
    licencas = []
    for alvo in ([a.so] if a.so else list(ALVOS)):
        K, nome = ALVOS[alvo]
        out = a.out / f"privacidade_{alvo}_det"
        sel = {}
        for sp in ("train", "validation", "test"):
            pos, neg, boxes, meta = escolher(alvo, sp, a.oi, rng)
            sel[sp] = (pos, neg, boxes, meta)
            nb = sum(len(boxes[i][K]) for i in pos)
            print(f"{alvo:10s} {sp:10s}: {len(pos):5d} imagens com {nb:6d} caixas + {len(neg):4d} negativas", flush=True)
        if a.ver:
            continue
        if out.exists():
            shutil.rmtree(out)
        for sp, (pos, neg, boxes, meta) in sel.items():
            ids = pos + neg
            with ThreadPoolExecutor(a.threads) as ex:
                tam = dict(zip(ids, ex.map(lambda i: baixar(sp, i, a.cache), ids)))
            falhas = [i for i, t in tam.items() if t is None]
            dst = out / ("valid" if sp == "validation" else sp)
            dst.mkdir(parents=True)
            imgs, anns = [], []
            for i in ids:
                if tam[i] is None:
                    continue
                w, h = tam[i]
                iid = len(imgs) + 1
                os.link(a.cache / sp / f"{i}.jpg", dst / f"{i}.jpg")
                imgs.append({"id": iid, "file_name": f"{i}.jpg", "width": w, "height": h})
                if i in pos:
                    for x0, x1, y0, y1 in boxes[i][K]:
                        bw, bh = (x1 - x0) * w, (y1 - y0) * h
                        if bw >= 2 and bh >= 2:
                            anns.append({"id": len(anns) + 1, "image_id": iid, "category_id": 1, "bbox": [round(x0 * w, 1), round(y0 * h, 1), round(bw, 1), round(bh, 1)], "area": round(bw * bh, 1), "iscrowd": 0})
                m = meta[i]
                licencas.append([alvo, sp, i, m["License"], m["Author"], m["OriginalLandingURL"]])
            (dst / "_annotations.coco.json").write_text(json.dumps({"categories": [{"id": 1, "name": nome}], "images": imgs, "annotations": anns}), encoding="utf-8")
            print(f"  -> {dst.relative_to(a.out)}: {len(imgs)} imagens, {len(anns)} caixas, {len(falhas)} falhas de download", flush=True)
    if licencas:
        a.cache.mkdir(parents=True, exist_ok=True)
        with open(a.cache / "LICENCAS.csv", "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["conjunto", "divisao", "imagem", "licenca", "autor", "origem"])
            w.writerows(licencas)
        print("licenças:", dict(Counter(l[3] for l in licencas)))


if __name__ == "__main__":
    main()
