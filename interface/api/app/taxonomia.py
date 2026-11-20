"""Leitura de shared/taxonomia.json: rótulos, nomes em português e validação de correções."""
import json
import os
from functools import lru_cache

TAXONOMIA_PATH = os.environ.get(
    "TAXONOMIA_PATH",
    os.path.join(os.path.dirname(__file__), "..", "..", "shared", "taxonomia.json"),
)

# Grupo provisório para tipos de sinal que ainda não estão na taxonomia
PREFIX_GROUP = {
    "regulatory_": "regulamentacao",
    "warning_": "perigo",
    "information_": "informacao",
    "complementary_": "complementar",
}


class TaxonomiaError(ValueError):
    pass


@lru_cache
def load() -> dict:
    with open(TAXONOMIA_PATH, encoding="utf-8") as f:
        return json.load(f)


def families() -> dict:
    return load()["familias"]


def family_label(family: str) -> str | None:
    fam = families().get(family)
    return fam["label"] if fam else None


def class_label(family: str, cls: str) -> str | None:
    c = families().get(family, {}).get("classes", {}).get(cls)
    return c["label"] if c else None


def sign_type(subclass: str | None) -> dict | None:
    return families()["sinal"]["tipos"].get(subclass) if subclass else None


def group_label(group: str | None) -> str | None:
    return families()["sinal"]["grupos"].get(group) if group else None


def install_label(install_type: str | None) -> str | None:
    return load()["instalacao"].get(install_type) if install_type else None


def color_info(color: str | None) -> dict | None:
    return load()["cores_ecoponto"].get(color) if color else None


def single_view_uncertainty_m() -> float:
    return float(load().get("incerteza_posicao_m", {}).get("vista_unica", 15))


def sign_group(subclass: str | None, detection_class: str | None = None) -> str:
    t = sign_type(subclass)
    if t and t.get("grupo"):
        return t["grupo"]
    if subclass and not t:
        for prefix, group in PREFIX_GROUP.items():
            if subclass.startswith(prefix):
                return group
    by_det = families()["sinal"]["grupo_por_classe_detecao"]
    return by_det.get(detection_class or "", "desconhecido")


def describe(family: str, cls: str, subclass: str | None = None, install_type: str | None = None,
             color: str | None = None, detection_class: str | None = None) -> dict:
    """Devolve {sign_group, code, name} para guardar no elemento."""
    if family == "sinal":
        group = sign_group(subclass, detection_class)
        t = sign_type(subclass)
        if t and subclass != "desconhecido":
            name, code = t["nome"], t.get("codigo")
        elif subclass and not t:
            name, code = subclass, None
        elif group == "regulamentacao":
            name, code = "Sinal de regulamentação por identificar", None
        else:
            gl = group_label(group)
            name = "Sinal não identificado" + (f" ({gl.lower()})" if group != "desconhecido" and gl else "")
            code = None
        return {"sign_group": group, "code": code, "name": name}

    if family in ("iluminacao", "mobiliario"):
        return {"sign_group": None, "code": None, "name": class_label(family, cls) or cls}

    # resíduos
    if cls == "subterraneo":
        name = "Contentor subterrâneo"
    elif install_type == "ilha":
        name = "Ecoponto (ilha de reciclagem)"
    elif install_type == "indiferenciado":
        name = "Contentor de indiferenciados"
    else:
        name = "Contentor de superfície (tipo por classificar)"
    c = color_info(color)
    if c:
        name += f" · {c['label'].lower()} ({c['residuo']})"
    return {"sign_group": None, "code": None, "name": name}


def validate(state: dict) -> dict:
    """Valida o estado completo de um elemento depois de uma correção e preenche sign_group, code e name.

    Lança TaxonomiaError com uma mensagem legível se a combinação não for válida.
    """
    family, cls = state.get("family"), state.get("class")
    fam = families().get(family)
    if not fam:
        raise TaxonomiaError(f"Família desconhecida: {family}")
    if cls not in fam["classes"]:
        raise TaxonomiaError(f"Classe '{cls}' não existe em {fam['label']}. Opções: {', '.join(fam['classes'])}")

    out = dict(state)
    if family == "sinal":
        sub = out.get("subclass")
        if sub is not None and sub not in fam["tipos"]:
            raise TaxonomiaError(f"Tipo de sinal desconhecido: {sub}")
    else:
        out["subclass"] = None

    if family == "residuos":
        allowed = fam["classes"][cls].get("instalacao", [])
        it = out.get("install_type")
        if cls == "subterraneo":
            if it not in (None, "subterraneo"):
                raise TaxonomiaError("Um contentor subterrâneo só pode ter o tipo 'subterraneo'")
            out["install_type"] = "subterraneo"
        elif it is not None and it not in allowed:
            raise TaxonomiaError(f"Para {fam['classes'][cls]['label'].lower()}, o tipo tem de ser um de: {', '.join(allowed)}")
        if out.get("color") is not None and out["color"] not in load()["cores_ecoponto"]:
            raise TaxonomiaError(f"Cor de ecoponto desconhecida: {out['color']}")
    else:
        out["install_type"] = None
        out["color"] = None

    out.update(describe(family, cls, out.get("subclass"), out.get("install_type"), out.get("color"),
                        out.get("detection_class")))
    out.pop("detection_class", None)
    return out
