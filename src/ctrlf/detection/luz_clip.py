"""Pré-anotação de postes de luz e candeeiros (COCO para importar no CVAT).

    python -m ctrlf.detection.annotation.preannotate_luz data/cvat_upload/porto data/preannot/luz/porto --limit 40 --preview 40
    python -m ctrlf.detection.annotation.preannotate_luz data/cvat_upload/porto data/preannot/luz/porto

1. Grounding DINO (zero-shot, passa pelo portão de privacidade como o resto) deteta "iluminação" SEM distinguir o tipo (prompt "street light").
2. CLIP zero-shot classifica o RECORTE de cada caixa com dois prompts (instruções da equipa):
     "a tall modern grey metal street light pole with a flat LED lamp head"                              -> poste_luz
     "an ornate dark green cast iron lamppost with glass lanterns and decorative scroll arms"            -> candeeiro
   A classe é a mais provável das duas e a PROBABILIDADE do CLIP fica como grau de confiança (`confianca`; o desafio pede-o por elemento).
3. Um filtro à parte (`p_rejeitar`, CLIP com frases de "não é candeeiro": poste elétrico, semáforo, sinal, árvore...) descarta as caixas
   que não são iluminação (--reject). Não faz parte da receita da equipa: foi mantido porque o Grounding DINO apanha muitos postes elétricos.
É uma SUGESTÃO para corrigir no CVAT: a fronteira simples/decorativo é subjetiva e o CLIP erra nela (o prompt do candeeiro fala em
"verde escuro, ferro fundido": candeeiros decorativos de outra cor/material podem sair como poste_luz).
Cada anotação leva `score` (detetor), `p_poste_luz`, `p_candeeiro`, `confianca` e `p_rejeitar`.

Saída: <dst>/annotations/instances_default.json (COCO 1.0, formato que o CVAT importa) e <dst>.zip.
Os `file_name` são os das imagens carregadas na task, por isso a task tem de ter as MESMAS imagens.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
import sys
import time
import zipfile
from pathlib import Path

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
sys.path.insert(0, str(ROOT))

import cv2  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from PIL import Image  # noqa: E402

from ctrlf.detection.detector import Detector  # noqa: E402
from ctrlf.privacy.anon_cache import anonymized_cached  # noqa: E402

CATS = [{"id": 1, "name": "poste_luz"}, {"id": 2, "name": "candeeiro"}]

# Frases do Grounding DINO: cada uma mapeia numa classe de detector_classes (a classe aqui é só "candidato";
# quem decide a classe final é o CLIP).  As frases concorrentes são descartadas.
PROMPTS = {
    "street light": "candeeiro",
    "street lamp": "candeeiro",
    "lamp post": "candeeiro",
    "street light pole": "candeeiro",
    "utility pole": "poste",
    "traffic sign": "__ignorar__",
    "traffic light": "__ignorar__",
}

# Prompts da equipa para a classificação do tipo (CLIP sobre o recorte)
PROMPT_POSTE_LUZ = "a tall modern grey metal street light pole with a flat LED lamp head"
PROMPT_CANDEEIRO = "an ornate dark green cast iron lamppost with glass lanterns and decorative scroll arms"

SIMPLE = [
    "a photo of a plain simple street light pole with a modern lamp on top",
    "a photo of a simple grey metal lamp post",
    "a photo of a minimalist street lighting column",
]
DECORATIVE = [
    "a photo of an ornate decorative street lamp",
    "a photo of a vintage cast iron street lantern on a decorated post",
    "a photo of a classic ornamental lamp post with a lantern",
]
REJECT = [
    "a photo of an electrical utility pole with cables",
    "a photo of a telephone pole",
    "a photo of a traffic light",
    "a photo of a street sign on a pole",
    "a photo of a tree trunk",
    "a photo of a building",
    "a photo of a car",
    "a photo of a person",
    "a photo of a bollard",
    "a photo of a fence",
    "a photo of a stone pillar or column of a building",
    "a photo of a concrete or granite pillar",
    "a photo of a wall corner of a building",
    "a photo of a vertical pipe or drainpipe",
    "a photo of a door or window frame",
]


class LuzClip:
    def __init__(self, device: str, model: str = "openai/clip-vit-base-patch32"):
        from transformers import CLIPModel, CLIPProcessor
        self.device = device
        self.model = CLIPModel.from_pretrained(model).to(device).eval()
        self.proc = CLIPProcessor.from_pretrained(model)
        with torch.no_grad():
            t = self.proc(text=SIMPLE + DECORATIVE + REJECT, return_tensors="pt", padding=True).to(device)
            f = self.model.get_text_features(**t)
            f = f.pooler_output if hasattr(f, "pooler_output") else f
            self.text = torch.nn.functional.normalize(f, dim=-1)
        self.a, self.b = len(SIMPLE), len(SIMPLE) + len(DECORATIVE)
        with torch.no_grad():                                     # os dois prompts da equipa (classificação do tipo)
            t2 = self.proc(text=[PROMPT_POSTE_LUZ, PROMPT_CANDEEIRO], return_tensors="pt", padding=True).to(device)
            f2 = self.model.get_text_features(**t2)
            f2 = f2.pooler_output if hasattr(f2, "pooler_output") else f2
            self.text2 = torch.nn.functional.normalize(f2, dim=-1)

    @torch.no_grad()
    def probs(self, crops: list[Image.Image]) -> list[tuple[float, float, float]]:
        """-> [(p_poste_luz, p_candeeiro, p_rejeitar)] por recorte.
        p_poste_luz + p_candeeiro = 1 (softmax só entre os dois prompts da equipa); p_rejeitar vem do conjunto alargado com as frases de rejeição."""
        out = []
        for i in range(0, len(crops), 32):
            x = self.proc(images=[c.convert("RGB") for c in crops[i:i + 32]], return_tensors="pt").to(self.device)
            f = self.model.get_image_features(**x)
            f = f.pooler_output if hasattr(f, "pooler_output") else f
            f = torch.nn.functional.normalize(f, dim=-1)
            p = (100.0 * f @ self.text.T).softmax(dim=-1).cpu()
            p2 = (100.0 * f @ self.text2.T).softmax(dim=-1).cpu()
            for r, r2 in zip(p, p2):
                out.append((float(r2[0]), float(r2[1]), float(r[self.b:].sum())))
        return out


def crop(img: Image.Image, box, pad: float = 0.15) -> Image.Image:
    W, H = img.size
    x1, y1, x2, y2 = box
    px, py = pad * (x2 - x1), pad * (y2 - y1)
    return img.crop((max(0, int(x1 - px)), max(0, int(y1 - py)), min(W, int(x2 + px) + 1), min(H, int(y2 + py) + 1)))


def nms(items: list[dict], thr: float = 0.6) -> list[dict]:
    """Remove caixas muito sobrepostas (as várias frases propõem o mesmo poste); fica a de maior score."""
    items = sorted(items, key=lambda d: -d["score"])
    keep: list[dict] = []
    for d in items:
        x1, y1, x2, y2 = d["box"]
        ok = True
        for k in keep:
            a1, b1, a2, b2 = k["box"]
            iw, ih = min(x2, a2) - max(x1, a1), min(y2, b2) - max(y1, b1)
            if iw > 0 and ih > 0:
                inter = iw * ih
                if inter / (min((x2 - x1) * (y2 - y1), (a2 - a1) * (b2 - b1)) + 1e-9) > thr:
                    ok = False
                    break
        if ok:
            keep.append(d)
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("src", type=Path)
    ap.add_argument("dst", type=Path)
    ap.add_argument("--conf", type=float, default=0.3, help="limiar do Grounding DINO")
    ap.add_argument("--reject", type=float, default=0.5, help="descarta se p_rejeitar >= isto")
    ap.add_argument("--limit", type=int, default=0, help="só N imagens (aleatórias) para teste")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--preview", type=int, default=0, help="grava previews das primeiras N imagens com caixas")
    ap.add_argument("--so-candeeiro", action="store_true", help="só candeeiros: ignora os poste_luz; fica como candeeiro tudo com p_candeeiro >= --pc-min")
    ap.add_argument("--pc-min", type=float, default=0.25, help="com --so-candeeiro: p_candeeiro mínimo para ser 'possível' candeeiro")
    ap.add_argument("--sem-politica", action="store_true", help="ignora configs/luz_politica.json")
    ap.add_argument("--sem-retoma", action="store_true", help="não retoma de <dst>/partial.json (ponto de controlo gravado a cada 50 imagens)")
    a = ap.parse_args()
    pol_f = ROOT / "configs" / "luz_politica.json"
    if pol_f.exists() and not a.sem_politica:                # política por cidade (nome da pasta de saída): ver configs/luz_politica.json
        pol = json.loads(pol_f.read_text(encoding="utf-8")).get(a.dst.name)
        if pol:
            for k, v in pol.items():
                setattr(a, k, v)
            print(f"política '{a.dst.name}': {pol}", flush=True)

    files = sorted(p for p in a.src.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    if a.limit:
        files = sorted(random.Random(a.seed).sample(files, min(a.limit, len(files))))
    (a.dst / "annotations").mkdir(parents=True, exist_ok=True)
    if a.preview:
        (a.dst / "preview").mkdir(exist_ok=True)

    det = Detector(backend="gdino", embed=False, subclassify=False)
    det.set_prompts(PROMPTS)
    clip = LuzClip(det.device)

    images, anns, t0 = [], [], time.time()
    n_prev = 0
    # Ponto de controlo: a pré-anotação só gravava no fim, e um bloqueio a meio (aconteceu em Lisboa: 2 h sem progresso) perdia tudo.
    part = a.dst / "partial.json"
    key = {"conf": a.conf, "reject": a.reject, "so_candeeiro": a.so_candeeiro, "pc_min": a.pc_min, "n": len(files)}
    start = 0
    if part.exists() and not a.sem_retoma:
        try:
            st = json.loads(part.read_text(encoding="utf-8"))
            ok = st["key"] == key and all(im["file_name"] == files[k].name for k, im in enumerate(st["images"]))
            if ok:
                images, anns, start = st["images"], st["anns"], len(st["images"])
                print(f"retoma de {part.name}: {start}/{len(files)} imagens já feitas ({len(anns)} caixas)", flush=True)
            else:
                print("partial.json não corresponde (outros parâmetros ou ficheiros): recomeça do zero", flush=True)
        except (ValueError, KeyError, IndexError):
            print("partial.json ilegível: recomeça do zero", flush=True)
    for i, p in enumerate(files):
        if i < start:
            continue
        anon = anonymized_cached(p)                  # desfoca UMA vez (data/images_anon) e reutiliza nas execuções seguintes
        im = Image.fromarray(np.asarray(anon))
        images.append({"id": i + 1, "file_name": p.name, "width": im.width, "height": im.height})
        cands = [{"score": d.score, "box": d.bbox} for d in det.detect(anon, a.conf) if d.cls != "__ignorar__"]
        cands = nms(cands)
        pr = clip.probs([crop(im, c["box"]) for c in cands]) if cands else []
        kept = []
        for c, (ps, pd, pj) in zip(cands, pr):
            if pj >= a.reject:
                continue
            if a.so_candeeiro:                           # só candeeiros: ps = p_poste_luz, pd = p_candeeiro
                if pd < a.pc_min:
                    continue
                cat = 2
            else:
                cat = 2 if pd > ps else 1                # ps = p_poste_luz, pd = p_candeeiro
            x1, y1, x2, y2 = c["box"]
            anns.append({"id": len(anns) + 1, "image_id": i + 1, "category_id": cat,
                         "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                         "area": round((x2 - x1) * (y2 - y1), 1), "iscrowd": 0, "score": round(c["score"], 3),
                         "attributes": {"occluded": False},
                         "p_poste_luz": round(ps, 3), "p_candeeiro": round(pd, 3), "confianca": round(max(ps, pd), 3),
                         "p_rejeitar": round(pj, 3),
                         **({"candeeiro_certeza": "alta" if pd >= 0.5 else "possivel"} if a.so_candeeiro else {})})
            kept.append((cat, c["box"], pd))
        if a.preview and kept and n_prev < a.preview:
            bgr = cv2.cvtColor(np.asarray(im), cv2.COLOR_RGB2BGR)
            for cat, (x1, y1, x2, y2), pd in kept:
                col = (255, 0, 255) if cat == 2 else (0, 200, 255)     # BGR: candeeiro magenta, poste_luz amarelo
                cv2.rectangle(bgr, (int(x1), int(y1)), (int(x2), int(y2)), col, 3)
                cv2.putText(bgr, f"{CATS[cat-1]['name']} {pd:.2f}", (int(x1), max(20, int(y1) - 6)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.8, col, 2)
            cv2.imwrite(str(a.dst / "preview" / p.name), bgr)
            n_prev += 1
        if (i + 1) % 50 == 0:
            tmp = part.with_suffix(".tmp")
            tmp.write_text(json.dumps({"key": key, "images": images, "anns": anns}), encoding="utf-8")
            tmp.replace(part)
        if (i + 1) % 25 == 0 or i + 1 == len(files):
            print(f"  {i+1}/{len(files)} imagens ({time.time()-t0:.0f}s) | {len(anns)} caixas", flush=True)

    out = {"licenses": [{"name": "", "id": 0, "url": ""}], "info": {"description": "pre-anotacao luz"},
           "categories": CATS, "images": images, "annotations": anns}
    js = a.dst / "annotations" / "instances_default.json"
    js.write_text(json.dumps(out), encoding="utf-8")
    part.unlink(missing_ok=True)
    zp = a.dst.with_suffix(".zip")
    with zipfile.ZipFile(zp, "w", zipfile.ZIP_DEFLATED) as z:
        z.write(js, "annotations/instances_default.json")
    n1 = sum(1 for x in anns if x["category_id"] == 1)
    print(f"\n{len(images)} imagens | poste_luz {n1} | candeeiro {len(anns)-n1} | {js}\n-> {zp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
