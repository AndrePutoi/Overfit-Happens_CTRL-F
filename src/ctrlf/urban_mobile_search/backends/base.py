"""Contrato dos backends. A aplicação pode registar os seus próprios detetores/classificadores sem tocar no resto."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class RawDet:
    cls: str
    score: float
    bbox: tuple[float, float, float, float]       # x1, y1, x2, y2 em píxeis


@dataclass
class ClassOut:
    label: str
    score: float
    extra: dict = field(default_factory=dict)
    reject: bool = False                           # True: a deteção não é do objeto (descarta-se)
    set_cls: str | None = None                     # muda a classe da deteção (p. ex. contentor -> papeleira)


class DetectorBackend(Protocol):
    def detect(self, image, conf: float) -> list[RawDet]:
        """`image`: a imagem ANONIMIZADA (ndarray RGB uint8; pode ser a subclasse `Anonymized` do portão de privacidade: não a converter)."""

    def close(self) -> None:
        """Liberta memória (GPU)."""


class ClassifierBackend(Protocol):
    def classify(self, crops: list, dets: list) -> list[ClassOut]:
        """Um ClassOut por recorte (PIL), na mesma ordem. `dets` são as deteções correspondentes (para decidir por família/classe)."""

    def close(self) -> None: ...
