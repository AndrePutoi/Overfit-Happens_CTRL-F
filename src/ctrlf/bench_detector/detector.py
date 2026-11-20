"""Detetor de bancos baseado no checkpoint RF-DETR pré-treinado em COCO (sem treino).

O checkpoint COCO do RF-DETR devolve `class_id` com os IDs de categoria COCO originais
(1-90, esparsos). Não se assume que o índice do modelo é 15: o ID de `bench` é resolvido
a partir do mapeamento do próprio modelo e verificado contra o nome, na carga e em cada
deteção.
"""
from __future__ import annotations

import hashlib
import math
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import numpy as np
from PIL import Image, UnidentifiedImageError

BENCH_CLASS_NAME = "bench"
BENCH_COCO_CATEGORY_ID = 15  # ID oficial COCO 2017; verificado contra o modelo em tempo de execução

# Checkpoint oficial (registo `rfdetr.assets.model_weights.ModelWeights.RF_DETR_MEDIUM`, rfdetr 1.12.1)
DEFAULT_VARIANT = "medium"
OFFICIAL_CHECKPOINTS = {
    "medium": {
        "filename": "rf-detr-medium.pth",
        "url": "https://repo.roboflow.com/rfdetr/medium_coco/checkpoint_best_regular.pth",
        "md5": "7223f764a87b863f02eb8d52bf0ce2ee",
        "sha256": "749ff6071828aaffac63e204c4f4135ed3d6cdae4d702e086c360edc3b5768c8",
    },
    "small": {          # checkpoint oficial RF-DETR Small COCO (pacote CTRL_F_RFDETR_SMALL_BANCOS_v1.0); a pipeline do projeto usa este (decisão do utilizador, 2026-11-20)
        "filename": "rf-detr-small.pth",
        "url": "https://repo.roboflow.com/rfdetr/small_coco/checkpoint_best_regular.pth",
        "md5": "fb37061c1af7bace359c91b723a8d5c1",
        "sha256": "d81979a9213a2109345158ce9232668df4c1ae52e9b8db3f2ec0a8cbad959b33",
    },
}
WEIGHTS_ENV_VAR = "BENCH_RFDETR_WEIGHTS"


class CheckpointNotFoundError(FileNotFoundError):
    """O ficheiro de pesos não existe (o detetor nunca descarrega pesos implicitamente)."""


class ClassMappingError(RuntimeError):
    """O mapeamento de classes do modelo não corresponde a COCO `bench`."""


class InvalidImageError(ValueError):
    """Imagem ilegível, vazia ou com formato não suportado."""


def default_weights_path(variant: str = DEFAULT_VARIANT) -> Path:
    env = os.environ.get(WEIGHTS_ENV_VAR)
    if env:
        return Path(env).expanduser()
    home = os.environ.get("RF_HOME") or os.environ.get("ROBOFLOW_HOME") or "~/.roboflow/models"
    return Path(home).expanduser() / OFFICIAL_CHECKPOINTS[variant]["filename"]


def sha256_file(path: str | os.PathLike, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def load_rgb(image: Any) -> np.ndarray:
    """Converte caminho / PIL / ndarray em ndarray RGB uint8 (H, W, 3)."""
    if isinstance(image, (str, os.PathLike)):
        p = Path(image)
        if not p.is_file():
            raise InvalidImageError(f"imagem inexistente: {p.name}")
        try:
            with Image.open(p) as im:
                im.load()
                arr = np.array(im.convert("RGB"))
        except (UnidentifiedImageError, OSError) as e:
            raise InvalidImageError(f"imagem ilegível: {p.name} ({e.__class__.__name__})") from e
    elif isinstance(image, Image.Image):
        arr = np.array(image.convert("RGB"))
    elif isinstance(image, np.ndarray):
        arr = image
    else:
        raise InvalidImageError(f"tipo de imagem não suportado: {type(image).__name__}")
    if arr.ndim != 3 or arr.shape[2] != 3 or arr.shape[0] == 0 or arr.shape[1] == 0:
        raise InvalidImageError(f"esperado RGB (H,W,3); recebido shape={arr.shape}")
    if arr.dtype != np.uint8:
        raise InvalidImageError(f"esperado uint8; recebido {arr.dtype}")
    return arr


def resolve_bench_ids(id_to_name: dict[int, str]) -> int:
    """Devolve o único class_id que o modelo associa a `bench`; falha se ambíguo/inconsistente."""
    ids = [int(k) for k, v in id_to_name.items() if v == BENCH_CLASS_NAME]
    if len(ids) != 1:
        raise ClassMappingError(f"esperado exatamente 1 id para '{BENCH_CLASS_NAME}', obtido {ids}")
    if ids[0] != BENCH_COCO_CATEGORY_ID:
        raise ClassMappingError(
            f"o modelo associa '{BENCH_CLASS_NAME}' ao id {ids[0]}, não ao id COCO {BENCH_COCO_CATEGORY_ID}"
        )
    return ids[0]


def _load_rfdetr(weights: Path, variant: str, device: str | None):
    import rfdetr  # import tardio: os testes unitários não precisam do pacote
    from rfdetr.utilities.class_names import class_id_to_name

    cls = {"medium": rfdetr.RFDETRMedium, "small": rfdetr.RFDETRSmall}[variant]
    kwargs: dict[str, Any] = {"pretrain_weights": str(weights)}
    if device:
        kwargs["device"] = device
    model = cls(**kwargs)
    id_to_name = class_id_to_name(list(model.class_names), int(model.model_config.num_classes), [])
    return model, id_to_name


@dataclass
class BenchDetector:
    """Carrega o RF-DETR COCO e devolve apenas deteções `bench`.

    `model_loader` permite injetar um modelo falso nos testes; deve devolver
    `(model, id_to_name)` onde `model.predict(rgb, threshold=...)` devolve um objeto
    com `xyxy`, `confidence`, `class_id` e `data["class_name"]` (como `supervision.Detections`).
    """

    weights: str | os.PathLike | None = None
    variant: str = DEFAULT_VARIANT
    device: str | None = None
    threshold: float = 0.5
    model_loader: Callable[..., tuple[Any, dict[int, str]]] | None = None
    verify_sha256: bool = False
    model: Any = field(init=False, default=None)
    bench_class_id: int = field(init=False, default=-1)

    def __post_init__(self) -> None:
        if self.variant not in OFFICIAL_CHECKPOINTS:
            raise ValueError(f"variante não suportada: {self.variant}")
        if not (0.0 <= float(self.threshold) <= 1.0):
            raise ValueError("threshold deve estar em [0, 1]")
        w = Path(self.weights).expanduser() if self.weights else default_weights_path(self.variant)
        if not w.is_file():
            raise CheckpointNotFoundError(
                f"checkpoint não encontrado: {w}. Descarregar o oficial "
                f"({OFFICIAL_CHECKPOINTS[self.variant]['url']}) ou definir {WEIGHTS_ENV_VAR}."
            )
        if self.verify_sha256:
            got = sha256_file(w)
            exp = OFFICIAL_CHECKPOINTS[self.variant]["sha256"]
            if got != exp:
                raise CheckpointNotFoundError(f"SHA-256 inesperado para {w.name}: {got} (esperado {exp})")
        self.weights_path = w
        loader = self.model_loader or _load_rfdetr
        self.model, id_to_name = loader(w, self.variant, self.device)
        self.bench_class_id = resolve_bench_ids(id_to_name)

    def detect(self, image: Any, image_id: str | int | None = None) -> dict[str, Any]:
        """Deteta bancos numa imagem. Coordenadas xyxy em píxeis da imagem original."""
        rgb = load_rgb(image)
        h, w = rgb.shape[:2]
        t0 = time.perf_counter()
        det = self.model.predict(rgb, threshold=float(self.threshold))
        latency_ms = (time.perf_counter() - t0) * 1000.0
        xyxy = np.asarray(det.xyxy, dtype=float).reshape(-1, 4)
        conf = np.asarray(det.confidence, dtype=float).reshape(-1)
        cid = np.asarray(det.class_id).reshape(-1).astype(int)
        names = np.asarray((getattr(det, "data", None) or {}).get("class_name", [None] * len(cid)), dtype=object)
        out = []
        for box, s, c, n in zip(xyxy, conf, cid, names):
            is_bench_id = c == self.bench_class_id
            if n is not None and is_bench_id != (n == BENCH_CLASS_NAME):
                raise ClassMappingError(f"inconsistência class_id={c} vs class_name={n!r}")
            if not is_bench_id:
                continue
            if not math.isfinite(s) or not np.all(np.isfinite(box)):
                continue  # descarta saídas numéricas inválidas
            x1, y1, x2, y2 = (float(v) for v in box)
            x1, x2 = sorted((min(max(x1, 0.0), w), min(max(x2, 0.0), w)))
            y1, y2 = sorted((min(max(y1, 0.0), h), min(max(y2, 0.0), h)))
            if x2 - x1 <= 0 or y2 - y1 <= 0:
                continue
            out.append(
                {
                    "bbox_xyxy": [round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2)],
                    "score": round(float(s), 5),
                    "class_name": BENCH_CLASS_NAME,
                    "coco_category_id": BENCH_COCO_CATEGORY_ID,
                    "model_class_id": int(c),
                }
            )
        out.sort(key=lambda d: -d["score"])
        if image_id is None and isinstance(image, (str, os.PathLike)):
            image_id = Path(image).stem
        return {
            "image_id": str(image_id) if image_id is not None else None,
            "width": int(w),
            "height": int(h),
            "detections": out,
            "latency_ms": round(latency_ms, 2),
        }

    def describe(self) -> dict[str, Any]:
        meta = OFFICIAL_CHECKPOINTS[self.variant]
        try:
            import rfdetr

            version = getattr(rfdetr, "__version__", None)
            if version is None:
                from importlib.metadata import version as _v

                version = _v("rfdetr")
        except Exception:  # pragma: no cover - apenas metadados
            version = None
        return {
            "model": f"RF-DETR {self.variant} (COCO pré-treinado, sem fine-tuning)",
            "rfdetr_version": version,
            "checkpoint_file": self.weights_path.name,
            "checkpoint_url": meta["url"],
            "checkpoint_sha256_expected": meta["sha256"],
            "threshold": float(self.threshold),
            "class_name": BENCH_CLASS_NAME,
            "coco_category_id": BENCH_COCO_CATEGORY_ID,
            "model_class_id": self.bench_class_id,
        }
