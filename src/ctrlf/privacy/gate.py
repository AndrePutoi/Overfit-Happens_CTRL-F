"""Portão de privacidade: nenhuma imagem chega ao Grounding DINO sem passar pelos DOIS mecanismos
(rostos + matrículas). Ver docs/ESTADO_E_ESTRUTURA.md e Plano.md §11.

    from ctrlf.privacy.gate import ensure_anonymized
    rgb = ensure_anonymized(imagem)        # np.ndarray RGB / PIL -> Anonymized (RGB uint8)

* `Anonymized` é um np.ndarray que só `anonymize()` devolve. Uma imagem desse tipo não é anonimizada outra vez.
* Qualquer outra imagem é anonimizada à entrada. Não há parâmetro para saltar este passo.
* Se faltar um modelo, o portão levanta `PrivacyConfigError` (falha fechada): o Detector nem arranca.
* Parâmetros em configs/pipeline.yaml, secção `privacidade` (omissões abaixo).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.privacy.blur_privacy import DEFAULT_FACES, DEFAULT_PLATES, Anonymizer, PrivacyConfigError  # noqa: E402

CONFIG = ROOT / "configs" / "pipeline.yaml"
_KEYS = {  # chave no yaml -> argumento do Anonymizer
    "modo_desfoque": "mode", "mosaico_matriculas": "plate_tile", "imgsz_matriculas": "plate_imgsz",
    "conf_matriculas": "plate_conf", "mosaico_rostos": "face_tile", "imgsz_rostos": "face_imgsz",
    "conf_rostos": "face_conf"}

__all__ = ["Anonymized", "PrivacyConfigError", "anonymize", "ensure_anonymized", "get_anonymizer"]


class Anonymized(np.ndarray):
    """Imagem RGB uint8 já anonimizada. Só `anonymize()` a cria."""

    def __array_finalize__(self, obj):
        self.privacy_counts = getattr(obj, "privacy_counts", {})
        self.privacy_vehicles = getattr(obj, "privacy_vehicles", [])      # caixas xyxy de veículos (do desfoque)


_lock = threading.Lock()
_anonymizer: Anonymizer | None = None


def _settings() -> dict:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {}
    p = (cfg or {}).get("privacidade", {}) or {}
    kw = {arg: p[k] for k, arg in _KEYS.items() if k in p}
    for k, arg, default in (("pesos_matriculas", "plate_weights", DEFAULT_PLATES), ("pesos_rostos", "face_weights", DEFAULT_FACES)):
        kw[arg] = ROOT / p[k] if k in p else default
    return kw


def get_anonymizer() -> Anonymizer:
    """Constrói (uma vez) o anonimizador. Levanta PrivacyConfigError se faltar um modelo."""
    global _anonymizer
    with _lock:
        if _anonymizer is None:
            import torch
            _anonymizer = Anonymizer(device=0 if torch.cuda.is_available() else "cpu", **_settings())
        return _anonymizer


def anonymize(image) -> Anonymized:
    """PIL ou ndarray RGB uint8 (H, W, 3) -> Anonymized. Rostos e matrículas desfocados; ver Anonymizer."""
    rgb = np.asarray(image.convert("RGB")) if isinstance(image, Image.Image) else np.asarray(image)
    if rgb.dtype != np.uint8 or rgb.ndim != 3 or rgb.shape[2] != 3:
        raise ValueError(f"esperava imagem RGB uint8 (H, W, 3), obtido {rgb.dtype} {rgb.shape}")
    bgr = cv2.cvtColor(np.ascontiguousarray(rgb), cv2.COLOR_RGB2BGR)
    anon = get_anonymizer()
    out, counts = anon(bgr)
    res = np.ascontiguousarray(cv2.cvtColor(out, cv2.COLOR_BGR2RGB)).view(Anonymized)
    res.privacy_counts = counts
    res.privacy_vehicles = list(anon.last_boxes["vehicles"])
    return res


def ensure_anonymized(image) -> Anonymized:
    return image if isinstance(image, Anonymized) else anonymize(image)
