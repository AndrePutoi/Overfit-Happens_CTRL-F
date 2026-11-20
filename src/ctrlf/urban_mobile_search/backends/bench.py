"""Detetor de bancos: RF-DETR pré-treinado no COCO (só a classe `bench`), sem treino nosso. Importa `ctrlf.bench_detector` de forma preguiçosa."""
from __future__ import annotations

import numpy as np

from ..settings import Settings
from .base import RawDet
from .legacy import _free_cuda, ensure_path


class BenchBackend:
    """RF-DETR (Small por omissão; Settings.bench_variant) pré-treinado em COCO, só a classe `bench` (bench_detector.BenchDetector). Pesos: Settings.bench_weights."""

    def __init__(self, settings: Settings, weights):
        ensure_path(settings)
        from ctrlf.bench_detector import BenchDetector
        self.det = BenchDetector(weights=str(weights), variant=settings.bench_variant, device=settings.resolve_device(), threshold=settings.conf.get("mobiliario", 0.5))

    def detect(self, image, conf: float) -> list[RawDet]:
        self.det.threshold = float(conf)
        r = self.det.detect(np.asarray(image))
        return [RawDet("banco", float(d["score"]), tuple(float(v) for v in d["bbox_xyxy"])) for d in r["detections"]]

    def close(self) -> None:
        self.det = None
        _free_cuda()
