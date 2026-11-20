"""Orquestra uma imagem: admissão -> privacidade -> detetores -> classificadores -> (posição) -> armazenamento.

    from ctrlf.urban_mobile_search import Pipeline, Settings, Store
    pipe = Pipeline(Settings.from_env(), store=Store("ums.sqlite"))
    result = pipe.process("foto.jpg", meta={"lat": 40.64, "lon": -8.65, "heading": 90.0, ...})

POLÍTICA DE GPU: processa FAMÍLIA A FAMÍLIA (sinal, resíduos, iluminação). Para cada uma carrega os seus modelos, corre-os em TODAS as imagens
do lote e liberta-os antes da seguinte (`keep_models_loaded=False`): a GPU de 6 GB não aguenta vários ao mesmo tempo. Por isso `process_many`
é muito mais barato por imagem do que chamar `process` em ciclo.
`admit` e `anonymize` são injetáveis (testes, ou a aplicação com o seu próprio portão); por omissão usam os módulos do projeto
(`ingest.admissao`, `privacy.anon_cache`), que garantem a anonimização ANTES de qualquer modelo e falham fechado.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from . import geo
from .models import Classification, Detection, ImageResult, detection_id
from .registry import Registry
from .settings import FIXED_LABELS, Settings
from .store import Store


def _legacy_admit(settings: Settings) -> Callable:
    from .backends.legacy import ensure_path
    ensure_path(settings)
    from ctrlf.ingest import admissao
    cfg = admissao.load_cfg()
    return lambda path, meta: admissao.admit(Path(path), meta, cfg)


def _legacy_anonymize(settings: Settings) -> Callable:
    from .backends.legacy import ensure_path
    ensure_path(settings)
    from ctrlf.privacy.anon_cache import anonymized_cached
    return anonymized_cached


class Pipeline:
    def __init__(self, settings: Settings | None = None, registry: Registry | None = None, store: Store | None = None,
                 admit: Callable | None = None, anonymize: Callable | None = None):
        self.settings = settings or Settings.from_env()
        if registry is None:
            from .backends.legacy import default_registry
            registry = default_registry(self.settings)
        self.registry, self.store = registry, store
        self._admit, self._anon = admit, anonymize

    # ---- passos injetáveis
    def admit(self, path, meta):
        if self._admit is None:
            self._admit = _legacy_admit(self.settings)
        return self._admit(path, meta)

    def anonymize(self, path):
        if self._anon is None:
            self._anon = _legacy_anonymize(self.settings)
        return self._anon(path)

    # ---- API
    def process(self, image, meta: dict | None = None, families=None, persist: bool = True) -> ImageResult:
        return self.process_many([(image, meta)], families, persist)[0]

    def process_many(self, items, families=None, persist: bool = True) -> list[ImageResult]:
        fams = tuple(families or self.settings.families)
        results: list[ImageResult] = []
        live: list[tuple[ImageResult, object, Path, dict]] = []                 # (resultado, imagem anonimizada, caminho, meta)
        for path, meta in items:
            path = Path(path)
            t0 = time.time()
            adm = self.admit(path, meta)
            m = dict(adm.get("meta") or meta or {})
            image_id = str(adm.get("id") or m.get("source_image_id") or path.stem)
            res = ImageResult(image_id=image_id, admission=adm)
            results.append(res)
            if adm.get("status") == "rejeitada":
                res.skipped = "admissão: " + ",".join(adm.get("motivos", []))
                continue
            anon = self.anonymize(path)                                         # NÃO converter: o tipo `Anonymized` é a prova de anonimização
            im = Image.fromarray(np.asarray(anon))
            m.setdefault("width", im.width)
            m.setdefault("height", im.height)
            res.timings["admissao_privacidade_s"] = round(time.time() - t0, 3)
            ap = self.settings.images_dir / path.name
            res.anon_path = str(ap) if ap.exists() else None
            live.append((res, anon, path, m))

        by_id = {r.image_id: (r, a, p, m, Image.fromarray(np.asarray(a))) for r, a, p, m in live}
        for fam in fams:
            t0 = time.time()
            self._run_family(fam, by_id)
            for r, *_ in by_id.values():
                r.timings[f"{fam}_s"] = round(time.time() - t0, 3)               # tempo da família para o lote (partilhado)
            if not self.settings.keep_models_loaded:
                self.registry.release()
        if persist and self.store is not None:
            for res in results:
                meta_out = by_id[res.image_id][3] if res.image_id in by_id else dict(res.admission.get("meta") or {})
                self.store.add_image(res.image_id, meta_out, {k: v for k, v in res.admission.items() if k != "meta"}, res.anon_path)
                if res.detections:
                    self.store.merge_model_detections(res.image_id, res.detections)
        return results

    # ---- uma família sobre todas as imagens
    def _run_family(self, fam: str, by_id: dict) -> None:
        s = self.settings
        specs = self.registry.detectors(fam)
        if not specs or not by_id:
            return
        per_img: dict[str, list[Detection]] = {iid: [] for iid in by_id}
        for spec in specs:
            det = self.registry.backend(spec, s)
            for iid, (res, anon, path, meta, pil) in by_id.items():
                for raw in det.detect(anon, s.conf.get(fam, 0.3)):
                    w, h = raw.bbox[2] - raw.bbox[0], raw.bbox[3] - raw.bbox[1]
                    if min(w, h) < s.min_side.get(fam, 8):
                        continue
                    bbox = tuple(float(v) for v in raw.bbox)
                    per_img[iid].append(Detection(id=detection_id(iid, fam, raw.cls, bbox), image_id=iid, family=fam, cls=raw.cls, score=float(raw.score),
                                                  bbox=bbox, model_version=spec.version, extra={"cls_detector": raw.cls, "detector": spec.name}))
        for cspec in self.registry.classifiers(fam):                              # por ordem de registo (p. ex. papeleira antes do fluxo)
            pairs = [(d, by_id[iid][4]) for iid, dets in per_img.items() for d in dets
                     if d.status != "rejeitado" and (cspec.only_cls is None or d.cls in cspec.only_cls)
                     and min(d.bbox[2] - d.bbox[0], d.bbox[3] - d.bbox[1]) >= cspec.min_side]
            if not pairs:
                continue
            clf = self.registry.backend(cspec, s)
            crops = [pil if cspec.use_image else _crop(pil, d.bbox, cspec.crop_pad) for d, pil in pairs]
            outs = clf.classify(crops, [d for d, _ in pairs])
            for (d, _), o in zip(pairs, outs):
                if o is None:
                    continue
                d.classifications.append(Classification(task=cspec.task, label=o.label, score=float(o.score), model=cspec.name, model_version=cspec.version, extra=dict(o.extra)))
                if o.set_cls:
                    d.extra.setdefault("cls_antes", d.cls)
                    d.cls = o.set_cls
                if o.reject:
                    d.status, d.extra["auto_rejeitada"] = "rejeitado", cspec.name
        for dets in per_img.values():                                            # etiquetas fixas por classe (ex.: papeleira -> fluxo indiferenciado)
            for d in dets:
                for task, label in FIXED_LABELS.get((d.family, d.cls), {}).items():
                    if d.status != "rejeitado" and not any(c.task == task and c.model == "regra" for c in d.classifications):
                        d.classifications.append(Classification(task=task, label=label, score=1.0, model="regra", model_version="fixa", extra={"motivo": f"{d.cls} é sempre {label}"}))
        for iid, dets in per_img.items():
            res, _, _, meta, _ = by_id[iid]
            if s.locate:
                for d in dets:
                    g = geo.locate(d.family, d.bbox, meta, s.cam_height_m)
                    if g:
                        d.extra["geo"] = g
            res.detections.extend(dets)


def _crop(im: Image.Image, box, pad: float) -> Image.Image:
    W, H = im.size
    x1, y1, x2, y2 = box
    p = pad * max(x2 - x1, y2 - y1)
    return im.crop((max(0, int(x1 - p)), max(0, int(y1 - p)), min(W, int(x2 + p) + 1), min(H, int(y2 + p) + 1)))
