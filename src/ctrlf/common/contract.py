"""Contratos de dados partilhados entre A (modelos), B (pipeline) e C (API/BD).

Regra: ninguém muda este ficheiro sozinho.  A e B importam daqui.

    from ctrlf.common.contract import Detection, load_classes
"""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
from pathlib import Path

import yaml

from ctrlf.paths import ROOT
CLASSES_YAML = ROOT / "configs" / "classes.yaml"


def load_classes(path: Path = CLASSES_YAML) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# ---------------------------------------------------------------- A -> B
@dataclass
class Detection:
    """Uma caixa numa imagem.  É o que a função de A devolve a B."""

    cls: str                                   # um valor de detector_classes
    score: float                               # confiança do detetor, 0..1
    bbox: tuple[float, float, float, float]    # x1, y1, x2, y2 em PIXELS da imagem original
    subclass: str | None = None                # ex.: "stop", "ilha_reciclagem"
    subscore: float | None = None              # confiança do sub-classificador
    embedding: list[float] | None = None       # DINOv2-S do recorte (384 floats), p/ deduplicar

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def label(self) -> str:
        """Rótulo final para o mapa: subclasse se existir, senão a classe."""
        return self.subclass or self.cls


# Assinatura que A tem de implementar (detection/detector.py::Detector.detect):
#
#   def detect(image: "np.ndarray | PIL.Image", conf: float = 0.3) -> list[Detection]
#
# `image` é RGB.  Não desfoca nada: o desfoque é feito por B ANTES de chamar isto.


# ---------------------------------------------------------------- B -> C
@dataclass
class ImageMeta:
    """Uma imagem já ingerida (linha da tabela `image`)."""

    source: str                  # mapillary | kartaview | panoramax | video | streetview
    source_image_id: str
    lat: float
    lon: float
    heading: float               # graus, 0 = Norte, sentido horário
    captured_at: str | None = None
    camera_type: str = "perspective"   # perspective | equirectangular
    hfov_deg: float | None = None      # campo de visão horizontal (perspetiva)
    path: str = ""               # caminho da imagem JÁ DESFOCADA
    license: str = ""
    attribution: str = ""
    extra: dict = field(default_factory=dict)
