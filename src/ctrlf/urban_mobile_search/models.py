"""Modelo de dados do urban_mobile_search: deteção, classificações (do modelo e do técnico) e resultado por imagem.

Uma DETEÇÃO é uma caixa numa imagem. Cada deteção tem várias CLASSIFICAÇÕES, uma por TAREFA (`sign_type`, `container_flux`, `light_style`,
`papeleira`...), e cada classificação pode vir de um modelo (com a sua versão) ou de uma pessoa. A etiqueta EFETIVA de uma tarefa é a decisão
humana mais recente; se não houver, a do modelo mais recente. Nada se apaga: reprocessar com um modelo novo só ACRESCENTA classificações.
"""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field

from .settings import FIXED_LABELS

STATUS = ("auto", "validado", "corrigido", "rejeitado")      # estado de uma deteção
FAMILIES = ("sinal", "residuos", "iluminacao", "mobiliario")


def iou(a, b) -> float:
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    ua = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / ua if ua > 0 else 0.0


def detection_id(image_id: str, family: str, cls: str, bbox) -> str:
    """Id estável: a mesma caixa (arredondada ao píxel) na mesma imagem dá sempre o mesmo id, seja qual for o modelo."""
    key = f"{image_id}|{family}|{cls}|" + ",".join(str(int(round(v))) for v in bbox)
    return f"det-{family[:3]}-{hashlib.sha1(key.encode()).hexdigest()[:10]}"


@dataclass
class Classification:
    task: str
    label: str
    score: float
    model: str = ""
    model_version: str = ""
    source: str = "model"                 # "model" | "human"
    by: str | None = None
    created_at: str | None = None
    extra: dict = field(default_factory=dict)
    id: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Detection:
    id: str
    image_id: str
    family: str
    cls: str                              # classe do detetor (pode ser mudada por um classificador, p. ex. contentor -> papeleira)
    score: float
    bbox: tuple[float, float, float, float]       # x1, y1, x2, y2 em PÍXEIS da imagem original
    status: str = "auto"
    origin: str = "model"                 # "model" | "human" (caixa desenhada à mão)
    model_version: str = ""
    classifications: list[Classification] = field(default_factory=list)
    extra: dict = field(default_factory=dict)     # p. ex. azimuth, position, cls_detector

    def effective(self) -> dict[str, Classification]:
        """tarefa -> classificação efetiva (humana mais recente; senão a do modelo mais recente)."""
        out: dict[str, Classification] = {}
        for c in sorted(self.classifications, key=lambda c: (c.created_at or "", c.id or 0)):
            cur = out.get(c.task)
            if cur is None or c.source == "human" or cur.source != "human":
                out[c.task] = c
        for task, label in FIXED_LABELS.get((self.family, self.cls), {}).items():       # regra por classe (papeleira -> indiferenciado): ganha a tudo
            out[task] = Classification(task=task, label=label, score=1.0, model="regra", model_version="fixa", source="rule")
        return out

    def label(self, task: str) -> str | None:
        c = self.effective().get(task)
        return c.label if c else None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["bbox"] = list(self.bbox)
        d["effective"] = {t: {"label": c.label, "score": c.score, "source": c.source} for t, c in self.effective().items()}
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Detection":
        return cls(id=d["id"], image_id=d["image_id"], family=d["family"], cls=d["cls"], score=float(d["score"]), bbox=tuple(d["bbox"]),
                   status=d.get("status", "auto"), origin=d.get("origin", "model"), model_version=d.get("model_version", ""),
                   classifications=[Classification(**{k: v for k, v in c.items()}) for c in d.get("classifications", [])], extra=d.get("extra", {}))


@dataclass
class ImageResult:
    image_id: str
    admission: dict
    detections: list[Detection] = field(default_factory=list)
    timings: dict = field(default_factory=dict)
    anon_path: str | None = None
    skipped: str | None = None            # motivo, se a imagem não foi processada (rejeitada na admissão)

    def to_dict(self) -> dict:
        return {"image_id": self.image_id, "admission": {k: v for k, v in self.admission.items() if k != "meta"}, "skipped": self.skipped,
                "timings": self.timings, "anon_path": self.anon_path, "detections": [d.to_dict() for d in self.detections]}
