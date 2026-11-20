"""Classificação hierárquica de recortes de sinais: ROUTER (grupo visual) -> ESPECIALISTA (sinal concreto).

    from ctrlf.detection.subclass.hier_classifier import HierClassifier
    hc = HierClassifier.from_manifest("models/hier_sinal/manifest.json", device="cuda")
    hc.predict(crops)            # -> [(rótulo, score)]  (mesma interface de sign_classifier.Loaded)
    hc.predict_detailed(crops)   # -> [dict] com grupo, família, p_router, especialista, folha

Regras de saída (por recorte):
  grupo com especialista   -> rótulo = folha do especialista,  score = p_router * p_especialista
  grupo terminal ("leaf")  -> rótulo = essa folha,             score = p_router
  grupo sem especialista   -> rótulo = "unknown",              score = p_router
O Detector põe o rótulo em Detection.subclass e o score em Detection.subscore; cls continua "sinal".

Manifesto (JSON, em models/, fora do Git):
{
  "version": 1,
  "synthetic": false,                     # true => modelos treinados com dados sintéticos
  "router": {"checkpoint": "router.pt", "labels": ["grupo_a", "grupo_b", ...]},
  "groups": {
    "grupo_a": {"family": "familia_semantica", "specialist": "esp_a"},
    "grupo_b": {"family": "familia_semantica", "leaf": "stop"},
    "grupo_c": {"family": "familia_semantica"}            # sem especialista -> "unknown"
  },
  "specialists": {"esp_a": {"checkpoint": "esp_a.pt", "labels": ["folha_1", "folha_2"]}}
}
Os caminhos dos checkpoints são relativos à pasta do manifesto.  Os rótulos de cada checkpoint têm de
ser IGUAIS (mesma ordem) aos do manifesto; qualquer incoerência levanta HierManifestError a nomear o
ficheiro.  Manifestos sintéticos só carregam com allow_synthetic=True.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

UNKNOWN = "unknown"
_NAME = re.compile(r"^[a-z0-9_]+$")


class HierManifestError(ValueError):
    pass


def validate_manifest(m: dict, where: str = "manifesto") -> dict:
    """Valida a estrutura e a coerência dos rótulos.  Devolve m.  HierManifestError se algo falhar."""
    def err(msg):
        raise HierManifestError(f"{where}: {msg}")

    if not isinstance(m, dict):
        err("não é um objeto JSON")
    if m.get("version") != 1:
        err(f"version {m.get('version')!r} != 1")
    if not isinstance(m.get("synthetic"), bool):
        err("campo 'synthetic' (bool) obrigatório")
    r, groups, specs = m.get("router"), m.get("groups"), m.get("specialists", {})
    if not isinstance(r, dict) or not r.get("checkpoint") or not isinstance(r.get("labels"), list):
        err("router precisa de 'checkpoint' e 'labels'")
    rl = r["labels"]
    if len(rl) < 2 or len(set(rl)) != len(rl):
        err(f"router.labels tem de ter >= 2 rótulos únicos: {rl}")
    if not isinstance(groups, dict) or set(groups) != set(rl):
        err(f"groups {sorted(groups or {})} != router.labels {sorted(rl)}")
    if not isinstance(specs, dict):
        err("specialists tem de ser um objeto")
    leaves, used = [], []
    for g in rl:
        e = groups[g]
        if not _NAME.match(g):
            err(f"nome de grupo inválido {g!r}")
        if not isinstance(e, dict) or not isinstance(e.get("family"), str):
            err(f"grupo {g!r} sem 'family'")
        if "leaf" in e and "specialist" in e:
            err(f"grupo {g!r} tem 'leaf' e 'specialist' ao mesmo tempo")
        if "leaf" in e:
            leaves.append(e["leaf"])
        if "specialist" in e:
            s = e["specialist"]
            if s not in specs:
                err(f"grupo {g!r} aponta para especialista inexistente {s!r}")
            used.append(s)
    if sorted(used) != sorted(specs):
        err(f"especialistas sem grupo ou partilhados: definidos {sorted(specs)}, usados {sorted(used)}")
    for s, e in specs.items():
        if not isinstance(e, dict) or not e.get("checkpoint") or not isinstance(e.get("labels"), list):
            err(f"especialista {s!r} precisa de 'checkpoint' e 'labels'")
        if len(e["labels"]) < 2 or len(set(e["labels"])) != len(e["labels"]):
            err(f"especialista {s!r}: >= 2 rótulos únicos, obtido {e['labels']}")
        leaves += e["labels"]
    for lf in leaves:
        if not isinstance(lf, str) or not _NAME.match(lf) or lf == UNKNOWN:
            err(f"folha inválida {lf!r} ('{UNKNOWN}' é reservado)")
    if len(set(leaves)) != len(leaves):
        err(f"folhas repetidas: {sorted(x for x in set(leaves) if leaves.count(x) > 1)}")
    return m


def load_manifest(path) -> dict:
    path = Path(path)
    if not path.is_file():
        raise HierManifestError(f"{path}: manifesto não existe")
    try:
        m = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise HierManifestError(f"{path}: JSON inválido: {e}") from e
    return validate_manifest(m, str(path))


class HierClassifier:
    """router e especialistas: objetos com `.labels` e `.predict(crops) -> [(rótulo, prob)]`."""

    def __init__(self, manifest: dict, router, specialists: dict, where: str = "manifesto"):
        self.m = validate_manifest(manifest, where)
        if list(router.labels) != list(self.m["router"]["labels"]):
            raise HierManifestError(f"{where}: rótulos do router {list(router.labels)} != manifesto "
                                    f"{self.m['router']['labels']}")
        if set(specialists) != set(self.m["specialists"]):
            raise HierManifestError(f"{where}: especialistas carregados {sorted(specialists)} != manifesto "
                                    f"{sorted(self.m['specialists'])}")
        for s, clf in specialists.items():
            if list(clf.labels) != list(self.m["specialists"][s]["labels"]):
                raise HierManifestError(f"{where}: rótulos do especialista {s!r} {list(clf.labels)} != manifesto "
                                        f"{self.m['specialists'][s]['labels']}")
        self.router, self.specialists = router, specialists
        self.synthetic = self.m["synthetic"]
        self.labels = self.leaves() + [UNKNOWN]

    def leaves(self) -> list[str]:
        out = []
        for g in self.m["router"]["labels"]:
            e = self.m["groups"][g]
            if "leaf" in e:
                out.append(e["leaf"])
            elif "specialist" in e:
                out += self.m["specialists"][e["specialist"]]["labels"]
        return out

    @classmethod
    def from_manifest(cls, path, device: str = "cuda", allow_synthetic: bool = False) -> "HierClassifier":
        from ctrlf.detection.subclass.sign_classifier import load_classifier
        path = Path(path)
        m = load_manifest(path)
        if m["synthetic"] and not allow_synthetic:
            raise HierManifestError(f"{path}: manifesto SINTÉTICO; recusado sem allow_synthetic=True")
        base = path.parent

        def load(ck, labels):
            try:
                return load_classifier(base / ck, device, expected_labels=labels)
            except ValueError as e:
                raise HierManifestError(f"{path}: {e}") from e

        router = load(m["router"]["checkpoint"], m["router"]["labels"])
        specs = {s: load(e["checkpoint"], e["labels"]) for s, e in m["specialists"].items()}
        return cls(m, router, specs, str(path))

    def predict_detailed(self, crops) -> list[dict]:
        if not crops:
            return []
        routed = self.router.predict(crops)
        out = []
        for g, p in routed:
            e = self.m["groups"][g]
            rec = {"group": g, "family": e["family"], "p_router": float(p), "specialist": None,
                   "p_specialist": None}
            if "specialist" in e:
                rec["route"], rec["specialist"] = "specialist", e["specialist"]
            elif "leaf" in e:
                rec.update(route="terminal", label=e["leaf"], score=float(p))
            else:
                rec.update(route="no_specialist", label=UNKNOWN, score=float(p))
            out.append(rec)
        for s, clf in self.specialists.items():
            idx = [i for i, r in enumerate(out) if r["specialist"] == s]
            if idx:
                for i, (lab, ps) in zip(idx, clf.predict([crops[i] for i in idx])):
                    out[i].update(label=lab, p_specialist=float(ps), score=out[i]["p_router"] * float(ps))
        return out

    def predict(self, crops) -> list[tuple[str, float]]:
        return [(r["label"], r["score"]) for r in self.predict_detailed(crops)]
