"""Detetor de bancos (COCO `bench`) com RF-DETR pré-treinado, sem fine-tuning.

Módulo isolado: não usa nem altera `common/contract.py` ou `common/classes.yaml`.
"""
from ctrlf.bench_detector.detector import (
    BENCH_CLASS_NAME,
    BENCH_COCO_CATEGORY_ID,
    BenchDetector,
    CheckpointNotFoundError,
    ClassMappingError,
    InvalidImageError,
)

__all__ = [
    "BENCH_CLASS_NAME",
    "BENCH_COCO_CATEGORY_ID",
    "BenchDetector",
    "CheckpointNotFoundError",
    "ClassMappingError",
    "InvalidImageError",
]
