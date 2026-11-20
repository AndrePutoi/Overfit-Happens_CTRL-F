"""Peças da deduplicação v2 que precisam de modelos: leitura das observações do catálogo, embeddings DINOv2 dos recortes e emparelhador EfficientLoFTR.

Extraído (sem alterações de lógica) dos scripts de geração de pares usados nas rondas de rotulagem, que ficaram de fora deste repositório.
"""
from __future__ import annotations

import functools
import json
import os
from collections import defaultdict
from pathlib import Path

import numpy as np

from ctrlf.geometry.geometry import to_m
from ctrlf.paths import ROOT

os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
ANON = ROOT / "data" / "images_anon"                      # só imagens ANONIMIZADAS
MIN_SIDE = 24.0                                           # lado mínimo (px) de uma observação para entrar na deduplicação
MODOS = {"recorte": 1.15, "contexto": 3.0}
LADO = 384                                                # lado maior do recorte depois de ampliar/reduzir


def carregar(cat: Path) -> list[dict]:
    feats = json.loads((cat / "catalog_ajustado.geojson").read_text(encoding="utf-8"))["features"]
    fam = {f["properties"]["id"]: f["properties"]["family"] for f in feats}
    obs, seen = [], set()
    for eid, members in json.loads((cat / "observacoes.json").read_text(encoding="utf-8")).items():
        for m in members:
            key = (m["image_id"], tuple(round(v) for v in m["bbox"]))
            if key in seen:
                continue
            seen.add(key)
            x1, y1, x2, y2 = m["bbox"]
            if min(x2 - x1, y2 - y1) < MIN_SIDE:
                continue
            az = np.radians(m["az"])
            cam = to_m(*m["cam"])
            obs.append({"oid": f"{m['image_id']}|{round(x1)},{round(y1)},{round(x2)},{round(y2)}", "image_id": m["image_id"], "bbox": [round(v, 1) for v in m["bbox"]],
                        "family": fam[eid], "grupo": m["cls"] if fam[eid] == "sinal" else fam[eid], "tipo": m.get("tipo"), "elem": eid, "cam_id": (round(m["cam"][0], 6), round(m["cam"][1], 6)),
                        "cam_xy": cam, "az": m["az"], "dist": m["dist_m"], "xy": cam + m["dist_m"] * np.array([np.sin(az), np.cos(az)])})
    return obs


def embeddings(obs: list[dict], ids: list[int]) -> dict[int, np.ndarray]:
    """Mesmo embedding do pipeline: DINOv2-small, recorte com 15% de margem (detection.postfilter.papeleiras.crop_box), pooler_output normalizado."""
    import torch
    from PIL import Image
    from torchvision import transforms
    from transformers import AutoModel
    from ctrlf.detection.postfilter.papeleiras import crop_box
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = AutoModel.from_pretrained("facebook/dinov2-small").to(dev).eval()
    tf = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), transforms.Normalize((0.485, 0.456, 0.406), (0.229, 0.224, 0.225))])
    out: dict[int, np.ndarray] = {}
    by_img = defaultdict(list)
    for i in ids:
        by_img[obs[i]["image_id"]].append(i)
    batch, keys = [], []

    def flush():
        if not batch:
            return
        with torch.no_grad():
            e = model(pixel_values=torch.stack(batch).to(dev)).pooler_output.float().cpu().numpy()
        for k, v in zip(keys, e):
            out[k] = v / (np.linalg.norm(v) + 1e-9)
        batch.clear(); keys.clear()

    for n, (img, lst) in enumerate(by_img.items(), 1):
        im = Image.open(ANON / f"{img}.jpg").convert("RGB")                    # só imagens ANONIMIZADAS
        for i in lst:
            batch.append(tf(crop_box(im, obs[i]["bbox"]).convert("RGB"))); keys.append(i)
        if len(batch) >= 64:
            flush()
    flush()
    return out


def recortar(img, bbox, fator):
    """Recorte quadrado-ish à volta da caixa (centro fixo), lado = fator × maior lado da caixa (mín. 48 px), sem sair da imagem."""
    from PIL import Image
    W, H = img.size
    x1, y1, x2, y2 = bbox
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    s = max(max(x2 - x1, y2 - y1) * fator, 48)
    box = (max(0, cx - s / 2), max(0, cy - s / 2), min(W, cx + s / 2), min(H, cy + s / 2))
    c = img.crop(tuple(int(round(v)) for v in box))
    k = LADO / max(c.size)
    c = c.resize((max(8, round(c.size[0] * k)), max(8, round(c.size[1] * k))), Image.BICUBIC)
    # caixa do objeto dentro do recorte (para contar inliers dentro do objeto)
    bx = [(x1 - box[0]) * k, (y1 - box[1]) * k, (x2 - box[0]) * k, (y2 - box[1]) * k]
    return c, bx


def inliers(p0, p1):
    import cv2
    import numpy as np
    if len(p0) < 8:
        return 0, np.zeros(len(p0), bool)
    F, m = cv2.findFundamentalMat(np.float32(p0), np.float32(p1), cv2.USAC_MAGSAC, 1.5, 0.999, 2000)
    if m is None:
        return 0, np.zeros(len(p0), bool)
    m = m.ravel().astype(bool)
    return int(m.sum()), m


def dentro(p, b):
    return (p[:, 0] >= b[0]) & (p[:, 0] <= b[2]) & (p[:, 1] >= b[1]) & (p[:, 1] <= b[3])


class Eloftr:
    def __init__(self, dev):
        import torch
        from transformers import AutoImageProcessor, EfficientLoFTRForKeypointMatching
        self.torch, self.dev = torch, dev
        self.proc = AutoImageProcessor.from_pretrained("zju-community/efficientloftr")
        self.m = EfficientLoFTRForKeypointMatching.from_pretrained("zju-community/efficientloftr").to(dev).eval()

    def __call__(self, a, b):
        torch = self.torch
        inp = self.proc([a, b], return_tensors="pt").to(self.dev)
        with torch.no_grad():
            out = self.m(**inp)
        k0, k1 = out.keypoints[0, 0], out.keypoints[0, 1]
        mt = out.matches[0, 0]
        ok = mt > -1
        sc = out.matching_scores[0, 0][ok]
        # as coordenadas vêm normalizadas [0,1] (x, y): converter para píxeis do recorte
        ws = [a.size[0], b.size[0]]; hs = [a.size[1], b.size[1]]
        p0 = k0[ok].cpu().numpy() * [ws[0], hs[0]]
        p1 = k1[mt[ok]].cpu().numpy() * [ws[1], hs[1]]
        return p0, p1, sc.cpu().numpy()


@functools.lru_cache(maxsize=48)
def _img(image_id: str):
    from PIL import Image
    return Image.open(ANON / f"{image_id}.jpg").convert("RGB")


def pontuar(M, oi: dict, oj: dict) -> dict:
    """Emparelhador (EfficientLoFTR, modo recorte) -> inliers e inliers dentro da caixa do objeto."""
    ca, ba = recortar(_img(oi["image_id"]), oi["bbox"], MODOS["recorte"])
    cb, bb = recortar(_img(oj["image_id"]), oj["bbox"], MODOS["recorte"])
    p0, p1, _ = M(ca, cb)
    n, msk = inliers(p0, p1)
    return {"matches": int(len(p0)), "inl": n, "inl_obj": int((msk & dentro(p0, ba) & dentro(p1, bb)).sum()) if len(msk) else 0}
