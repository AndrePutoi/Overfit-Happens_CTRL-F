"""Distância à câmara a partir de UMA imagem (profundidade métrica).

Usa Depth Anything V2 Metric Outdoor Small (ungated, ~25M parâmetros, ~0.3 GiB de GPU).
O plano refere o Depth Anything 3 (DA3METRIC-LARGE); trocar é só mudar `load()` e
manter a função `distance_in_bbox`.  Começar por este: já está instalado e funciona.

    from ctrlf.geometry.depth import DepthEstimator
    de = DepthEstimator()
    d_m = de.distance_in_bbox(pil_image, (x1, y1, x2, y2))     # metros

Cuidados:
  - A profundidade é a distância ao PLANO da câmara (eixo Z), não ao centro ótico; para
    objetos longe do eixo a distância real ao longo do raio é d / cos(ângulo).  A função faz
    essa correção quando recebe `offset_deg`.
  - Usa a MEDIANA da zona central da caixa (evita o fundo que entra nos cantos).
  - Erro típico de modelos métricos monoculares: 10-20% ou mais; por isso a triangulação
    (>= 2 vistas) vale mais do que esta estimativa.  Mede o erro nos 20 pontos de referência.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
NAME = "depth-anything/Depth-Anything-V2-Metric-Outdoor-Small-hf"


class DepthEstimator:
    def __init__(self, device: str | None = None):
        from transformers import AutoImageProcessor, AutoModelForDepthEstimation
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.proc = AutoImageProcessor.from_pretrained(NAME)
        self.model = AutoModelForDepthEstimation.from_pretrained(NAME).to(self.device).eval()

    @torch.no_grad()
    def depth_map(self, image: Image.Image) -> np.ndarray:
        """Mapa de profundidade em metros, com o tamanho da imagem (H, W)."""
        inp = self.proc(images=image.convert("RGB"), return_tensors="pt").to(self.device)
        d = self.model(**inp).predicted_depth
        d = torch.nn.functional.interpolate(d[:, None], size=image.size[::-1], mode="bicubic",
                                            align_corners=False)[0, 0]
        return d.float().cpu().numpy()

    def distance_in_bbox(self, image: Image.Image, bbox, offset_deg: float = 0.0,
                         depth: np.ndarray | None = None) -> float:
        d = self.depth_map(image) if depth is None else depth
        x1, y1, x2, y2 = bbox
        w, h = x2 - x1, y2 - y1
        cx1, cx2 = int(x1 + 0.3 * w), max(int(x1 + 0.7 * w), int(x1 + 0.3 * w) + 1)
        cy1, cy2 = int(y1 + 0.3 * h), max(int(y1 + 0.7 * h), int(y1 + 0.3 * h) + 1)
        patch = d[max(cy1, 0):cy2, max(cx1, 0):cx2]
        z = float(np.median(patch))
        return z / max(math.cos(math.radians(offset_deg)), 0.3)
