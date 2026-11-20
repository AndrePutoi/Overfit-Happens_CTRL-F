"""Registo de detetores e classificadores. Os backends carregam-se SÓ quando são precisos e libertam-se a seguir (a GPU de 6 GB não aguenta
vários modelos ao mesmo tempo: a anonimização precisa de ~3 GB e a profundidade e o emparelhador de ~1,5 GB cada)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass
class DetectorSpec:
    name: str
    family: str
    factory: Callable                       # (settings) -> DetectorBackend
    version: str
    weights: object = None                  # Path (ficheiro ou pasta) que o módulo precisa em UMS_MODELS_DIR, ou None (zero-shot / só código)
    note: str = ""                          # de onde vêm os pesos / licença


@dataclass
class ClassifierSpec:
    name: str
    task: str                               # sign_type | container_flux | light_style | papeleira | ...
    family: str
    factory: Callable                       # (settings) -> ClassifierBackend
    version: str
    only_cls: tuple[str, ...] | None = None # só classifica deteções destas classes (depois de eventuais set_cls anteriores)
    crop_pad: float = 0.15
    min_side: int = 8
    use_image: bool = False                 # True: `classify(imagens, dets)` recebe a IMAGEM INTEIRA (PIL) por deteção, não o recorte (p. ex. o estado do sinal)
    weights: object = None
    note: str = ""


class Registry:
    def __init__(self):
        self._det: dict[str, DetectorSpec] = {}
        self._clf: dict[str, ClassifierSpec] = {}
        self._live: dict[str, object] = {}
        self.support: list[tuple[str, object, str]] = []        # pesos de módulos de apoio (privacidade, profundidade...): (nome, caminho, nota)

    # ---- registo
    def register_detector(self, spec: DetectorSpec) -> None:
        self._det[spec.name] = spec

    def register_classifier(self, spec: ClassifierSpec) -> None:
        self._clf[spec.name] = spec

    def detectors(self, family: str | None = None) -> list[DetectorSpec]:
        return [s for s in self._det.values() if family in (None, s.family)]

    def classifiers(self, family: str | None = None) -> list[ClassifierSpec]:
        return [s for s in self._clf.values() if family in (None, s.family)]       # por ordem de registo (a ordem importa)

    def disable(self, name: str) -> None:
        self._det.pop(name, None)
        self._clf.pop(name, None)

    # ---- instâncias (carregamento preguiçoso)
    def backend(self, spec, settings):
        if spec.name not in self._live:
            self._live[spec.name] = spec.factory(settings)
        return self._live[spec.name]

    def release(self, name: str | None = None) -> int:
        """Fecha e esquece um backend (ou todos). -> quantos libertou."""
        names = [name] if name else list(self._live)
        n = 0
        for k in names:
            b = self._live.pop(k, None)
            if b is not None:
                n += 1
                close = getattr(b, "close", None)
                if close:
                    close()
        if n:
            try:
                import gc
                gc.collect()
                import torch
                if torch.cuda.is_available():
                    torch.cuda.empty_cache()
            except ImportError:
                pass
        return n

    def loaded(self) -> list[str]:
        return sorted(self._live)

    def describe(self) -> dict:
        w = lambda s: None if s.weights is None else str(s.weights)  # noqa: E731
        return {"detectors": [{"name": s.name, "family": s.family, "version": s.version, "weights": w(s)} for s in self._det.values()],
                "classifiers": [{"name": s.name, "task": s.task, "family": s.family, "version": s.version, "only_cls": s.only_cls, "use_image": s.use_image, "weights": w(s)}
                                for s in self._clf.values()],
                "loaded": self.loaded()}

    def weights_report(self) -> list[dict]:
        """Um registo por módulo que precisa de pesos: onde os pôr, se já lá estão e quanto ocupam."""
        from pathlib import Path
        out, seen = [], set()
        for s in [*self._det.values(), *self._clf.values()]:
            if s.weights is None or str(s.weights) in seen:
                continue
            seen.add(str(s.weights))
            p = Path(s.weights)
            size = (sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size) if p.exists() else None
            out.append({"modulo": s.name, "familia": getattr(s, "family", ""), "caminho": str(p), "existe": p.exists(), "tamanho_mb": None if size is None else round(size / 1e6, 1), "nota": s.note})
        for name, path, note in self.support:
            p = Path(path)
            size = (sum(f.stat().st_size for f in p.rglob("*") if f.is_file()) if p.is_dir() else p.stat().st_size) if p.exists() else None
            out.append({"modulo": name, "familia": "apoio", "caminho": str(p), "existe": p.exists(), "tamanho_mb": None if size is None else round(size / 1e6, 1), "nota": note})
        return out
