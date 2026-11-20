"""Adaptador RF-DETR com a interface do YOLO usada em privacy/blur_privacy.py (substitui o `ultralytics.YOLO`, AGPL-3.0, por RF-DETR, Apache-2.0).

O `Anonymizer` só precisa de: `modelo.predict(imagem_ou_lista_BGR, imgsz=, conf=, device=, verbose=)` -> lista de resultados `r` com
`r.boxes.xyxy`, `r.boxes.conf`, `r.boxes.cls` (tensores; usa-se `.cpu().numpy()`). Isto reproduz exatamente isso, de modo que `_tiled_predict`,
`face_boxes`, `plate_boxes` e `_audit_sheet` não mudam.

Dois tipos de modelo:
  kind="coco"       RF-DETR COCO oficial (pessoas e veículos). O `cls` devolvido usa os índices do YOLO (pessoa=0, bicicleta=1, carro=2, mota=3, autocarro=5, camião=7),
                    atribuídos POR NOME de classe, porque o RF-DETR usa os ids COCO (pessoa=1, carro=3...) e trocar uns pelos outros desfocava a classe errada.
  kind="checkpoint" detetor treinado por nós (rostos ou matrículas, uma classe): `cls` = 0.

`imgsz` é ignorado: o RF-DETR usa a resolução com que foi treinado. As imagens chegam em BGR (OpenCV) e são convertidas para RGB aqui.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import numpy as np

# nome COCO -> índice YOLO (80 classes). Só as que o anonimizador usa (COCO_PERSON e COCO_VEHICLES em blur_privacy.py).
YOLO_IDX = {"person": 0, "bicycle": 1, "car": 2, "motorcycle": 3, "bus": 5, "truck": 7}


class RFDETRBoxesError(RuntimeError):
    """Modelo RF-DETR indisponível ou com classes inesperadas (a privacidade falha fechada)."""


@dataclass
class _Boxes:
    xyxy: Any
    conf: Any
    cls: Any


@dataclass
class _Result:
    boxes: _Boxes


def _tensors(xyxy: np.ndarray, conf: np.ndarray, cls: np.ndarray) -> _Boxes:
    import torch
    return _Boxes(torch.as_tensor(np.asarray(xyxy, dtype=np.float32).reshape(-1, 4)),
                  torch.as_tensor(np.asarray(conf, dtype=np.float32).reshape(-1)),
                  torch.as_tensor(np.asarray(cls, dtype=np.float32).reshape(-1)))


def _load(weights: Path, kind: str, variant: str, device: str | None):
    import rfdetr
    if kind == "coco":
        from rfdetr.utilities.class_names import class_id_to_name
        cls = {"small": rfdetr.RFDETRSmall, "medium": rfdetr.RFDETRMedium}[variant]
        model = cls(pretrain_weights=str(weights), **({"device": device} if device else {}))
        return model, class_id_to_name(list(model.class_names), int(model.model_config.num_classes), [])
    model = rfdetr.RFDETR.from_checkpoint(str(weights), trust_checkpoint=True)      # o nosso detetor, treinado a partir do COCO oficial
    return model, {i: str(n) for i, n in enumerate(model.class_names)}


class RFDETRBoxes:
    """`RFDETRBoxes(pesos, kind="coco"|"checkpoint")`. `model_loader` permite injetar um modelo falso nos testes: devolve `(model, {id: nome})`."""

    def __init__(self, weights: str | Path, kind: str = "checkpoint", variant: str = "small", device: str | int | None = None,
                 model_loader: Callable[..., tuple[Any, dict[int, str]]] | None = None):
        if kind not in ("coco", "checkpoint"):
            raise ValueError(f"kind {kind!r} desconhecido")
        w = Path(weights)
        if model_loader is None and not w.is_file():
            raise RFDETRBoxesError(f"falta o modelo RF-DETR: {w}")
        self.kind, self.weights = kind, w
        dev = "cpu" if device == "cpu" else None                  # 0/"cuda": o RF-DETR escolhe a GPU sozinho
        self.model, self.id_to_name = (model_loader or _load)(w, kind, variant, dev)
        if kind == "coco":
            self.map_cls = {i: YOLO_IDX[n] for i, n in self.id_to_name.items() if n in YOLO_IDX}
            em_falta = sorted(set(YOLO_IDX) - set(self.id_to_name.values()))
            if em_falta:
                raise RFDETRBoxesError(f"o modelo COCO {w.name} não tem as classes {em_falta}")
        else:
            self.map_cls = {}

    def predict(self, source, imgsz=None, conf: float = 0.25, device=None, verbose: bool = False) -> list[_Result]:
        imgs = source if isinstance(source, (list, tuple)) else [source]
        rgb = [np.ascontiguousarray(np.asarray(im)[..., ::-1]) for im in imgs]          # BGR (OpenCV) -> RGB
        out = self.model.predict(rgb, threshold=float(conf))
        dets = out if isinstance(out, list) else [out]
        res = []
        for d in dets:
            xyxy = np.asarray(d.xyxy, dtype=np.float32).reshape(-1, 4)
            sc = np.asarray(d.confidence, dtype=np.float32).reshape(-1)
            cid = np.asarray(d.class_id, dtype=np.int64).reshape(-1)
            if self.kind == "coco":
                keep = np.array([int(c) in self.map_cls for c in cid], dtype=bool)
                xyxy, sc, cid = xyxy[keep], sc[keep], np.array([self.map_cls[int(c)] for c in cid[keep]], dtype=np.float32)
            else:
                cid = np.zeros(len(cid), dtype=np.float32)
            res.append(_Result(_tensors(xyxy, sc, cid)))
        return res
