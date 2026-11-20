"""Filtro de PAPELEIRAS: separa caixotes de lixo de rua (presos a postes, cilíndricos, pequenos) dos ECOPONTOS.

O detetor de ecopontos (treinado no Porto) apanha também papeleiras como `contentor`.  Isto infla a contagem e, pior, uma papeleira
junto a uma ilha acaba fundida com ela.  CLIP zero-shot sobre o RECORTE de cada caixa compara duas famílias de frases:
  ecoponto : contentor de reciclagem grande / módulo subterrâneo / contentor com rodas / contentor colorido
  papeleira: caixote pequeno preso a um poste / cilíndrico público / caixote de rua pequeno
e devolve (p_papeleira, p_ecoponto), probabilidades de um softmax sobre TODAS as frases (incluindo "outras coisas").

    f = PapeleiraFilter(device="cuda")
    for p_pap, p_eco in f.scores(crops): ...

É uma heurística SEM treino, validada à vista num conjunto pequeno (ver relatório): usar --limiar com cuidado.
"""
from __future__ import annotations

import os
from pathlib import Path

import torch
from PIL import Image

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))

ECOPONTO = [
    "a photo of a large underground recycling container with a round lid on the pavement",
    "a photo of a recycling island with several large colored containers",
    "a photo of a large wheelie waste container with wheels and a lid",
    "a photo of a big blue recycling container",
    "a photo of a green glass recycling container",
    "a photo of a yellow packaging recycling container",
]
PAPELEIRA = [
    "a photo of a small litter bin attached to a pole",
    "a photo of a small street trash can on the sidewalk",
    "a photo of a cylindrical public litter bin",
    "a photo of a small grey public rubbish bin on a street",
    "a photo of a wall-mounted trash bin",
]
OUTRAS = [
    "a photo of a car", "a photo of a street pole", "a photo of a building wall", "a photo of a utility cabinet",
    "a photo of a bench", "a photo of a person", "a photo of a tree", "a photo of a road barrier",
]


def _feat(out):
    return out.pooler_output if hasattr(out, "pooler_output") else out


class PapeleiraFilter:
    def __init__(self, device: str = "cuda", model: str = "openai/clip-vit-base-patch32"):
        from transformers import CLIPModel, CLIPProcessor
        self.device = device
        self.model = CLIPModel.from_pretrained(model).to(device).eval()
        self.proc = CLIPProcessor.from_pretrained(model)
        with torch.no_grad():
            t = self.proc(text=ECOPONTO + PAPELEIRA + OUTRAS, return_tensors="pt", padding=True).to(device)
            self.text = torch.nn.functional.normalize(_feat(self.model.get_text_features(**t)), dim=-1)
        self.a, self.b = len(ECOPONTO), len(ECOPONTO) + len(PAPELEIRA)

    @torch.no_grad()
    def scores(self, crops: list[Image.Image]) -> list[tuple[float, float]]:
        out = []
        for i in range(0, len(crops), 32):
            x = self.proc(images=[c.convert("RGB") for c in crops[i:i + 32]], return_tensors="pt").to(self.device)
            f = torch.nn.functional.normalize(_feat(self.model.get_image_features(**x)), dim=-1)
            p = (100.0 * f @ self.text.T).softmax(dim=-1).cpu()
            out += [(float(r[self.a:self.b].sum()), float(r[:self.a].sum())) for r in p]
        return out


def crop_box(im: Image.Image, bbox, pad: float = 0.15) -> Image.Image:
    W, H = im.size
    x1, y1, x2, y2 = bbox
    px, py = pad * (x2 - x1), pad * (y2 - y1)
    return im.crop((max(0, int(x1 - px)), max(0, int(y1 - py)), min(W, int(x2 + px) + 1), min(H, int(y2 + py) + 1)))
