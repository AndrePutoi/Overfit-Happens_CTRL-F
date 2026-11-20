"""PKG-5: ramos de RESÍDUOS e ILUMINAÇÃO sobre as deteções do Detector (opt-in; nada muda por omissão).

    det = Detector()
    det.contentor_dedup_iou = 0.7     # deduplicação só de `contentor` dentro da mesma imagem (None = desligada)
    det.branch_attributes = True      # preenche det.last_branch_report com o estado de cada atributo
    dets = det.detect(img)            # assinatura e Detection inalteradas
    det.last_dedup_report, det.last_branch_report

Dimensões e o que o contrato atual (common/contract.py, configs/classes.yaml) permite representar:
  resíduos
    tipo_instalacao          subclassifiers.contentor = subterraneo | ilha_reciclagem | indiferenciado
                             -> Detection.subclass/subscore SÓ se houver modelo (models/subclassifier_contentor.pt);
                                sem modelo: subclass=None e estado "unavailable" no relatório lateral
    individual_vs_agrupamento  só derivável de tipo_instalacao == ilha_reciclagem; nenhum campo próprio
    fracao_material          não existe em classes.yaml nem em Detection -> "not_in_contract"
    enchimento               "Extra" no Plano.md (§2, item 9); sem campo nem dados -> "not_in_contract"
  iluminação
    tipo                     candeeiro | poste vem do próprio detetor (cls); "candeeiro e poste não têm subclasse"
    estado_operacional / defeitos / poste_torto   sem campo nem dados -> "not_in_contract"
Estados desconhecidos NUNCA vão para Detection.subclass (violaria classes.yaml); ficam no relatório lateral.
"""
from __future__ import annotations

import math
from numbers import Real

from ctrlf.common.contract import load_classes

# estados de atributo
CLASSIFIED = "classified"            # valor vindo de um modelo carregado
FROM_DETECTOR = "from_detector"      # valor é a própria classe do detetor
DERIVED = "derived"                  # deduzido de outro atributo classificado
UNKNOWN = "unknown"                  # atributo representável, mas sem evidência para decidir
UNAVAILABLE = "unavailable"          # atributo representável, mas sem modelo treinado
NOT_IN_CONTRACT = "not_in_contract"  # o contrato atual não tem onde o pôr

DEDUP_CLASS = "contentor"


def _check_box(b) -> tuple[float, float, float, float]:
    if not (isinstance(b, (tuple, list)) and len(b) == 4 and all(isinstance(v, Real) and math.isfinite(v) for v in b)):
        raise ValueError(f"bbox inválida {b!r}")
    if not (b[0] < b[2] and b[1] < b[3]):
        raise ValueError(f"bbox degenerada {b!r}")
    return tuple(float(v) for v in b)


def iou(a, b) -> float:
    a, b = _check_box(a), _check_box(b)
    ix = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = ix * iy
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / u if u > 0 else 0.0


def dedup_contentor(raw: list[tuple], iou_thr: float, cls: str = DEDUP_CLASS) -> tuple[list[tuple], dict]:
    """raw = [(cls, score, bbox)] (saída de Detector._raw).  Supressão gulosa SÓ entre caixas `cls`:
    por ordem de score decrescente (empate -> menor índice), uma caixa é removida se tiver IoU >= iou_thr com uma
    caixa já mantida.  Outras classes passam intactas e pela ordem original.  Caixas próximas mas com IoU < iou_thr
    (ex.: dois contentores lado a lado) são mantidas.  -> (raw_filtrado, relatório)"""
    if isinstance(iou_thr, bool) or not isinstance(iou_thr, Real) or not (0.0 < float(iou_thr) <= 1.0):
        raise ValueError(f"iou_thr tem de estar em ]0, 1], obtido {iou_thr!r}")
    for r in raw:
        if not (isinstance(r, tuple) and len(r) == 3):
            raise ValueError(f"entrada inválida {r!r}; esperado (cls, score, bbox)")
        _check_box(r[2])
    idx = [i for i, r in enumerate(raw) if r[0] == cls]
    order = sorted(idx, key=lambda i: (-raw[i][1], i))
    kept, removed = [], []
    for i in order:
        best = max(((iou(raw[i][2], raw[k][2]), k) for k in kept), default=(0.0, None))
        if best[1] is not None and best[0] >= iou_thr:
            removed.append({"index": i, "score": raw[i][1], "bbox": list(raw[i][2]), "kept_index": best[1],
                            "kept_score": raw[best[1]][1], "iou": round(best[0], 4)})
        else:
            kept.append(i)
    rm = {r["index"] for r in removed}
    out = [r for i, r in enumerate(raw) if i not in rm]
    rep = {"class": cls, "iou_thr": float(iou_thr), "n_in": len(idx), "n_kept": len(kept), "n_removed": len(removed),
           "kept_indices": sorted(kept), "removed": removed}
    return out, rep


def _attr(status, value=None, score=None, reason=None) -> dict:
    d = {"status": status, "value": value}
    if score is not None:
        d["score"] = float(score)
    if reason:
        d["reason"] = reason
    return d


def branch_report(dets, subclassifiers: dict | None = None, classes: dict | None = None) -> list[dict]:
    """Encaminha cada Detection para o seu ramo (classes.yaml: family_of) e descreve o estado de cada atributo.
    Não inventa valores: só reporta o que Detection já contém (detetor ou modelo carregado)."""
    cfg = classes or load_classes()
    family_of, subs = cfg.get("family_of", {}), cfg.get("subclassifiers", {})
    subclassifiers = subclassifiers or {}
    out = []
    for i, d in enumerate(dets):
        fam = family_of.get(d.cls)
        rec = {"index": i, "cls": d.cls, "family": fam, "branch": fam, "attributes": {}}
        a = rec["attributes"]
        if fam == "residuos":
            allowed = subs.get(d.cls, [])
            if d.subclass is not None:
                if d.subclass not in allowed:
                    raise ValueError(f"det {i}: subclass {d.subclass!r} fora de subclassifiers.{d.cls} {allowed}")
                a["tipo_instalacao"] = _attr(CLASSIFIED, d.subclass, d.subscore)
                a["individual_vs_agrupamento"] = (
                    _attr(DERIVED, "agrupamento", reason="tipo_instalacao == ilha_reciclagem")
                    if d.subclass == "ilha_reciclagem" else
                    _attr(UNKNOWN, reason="só ilha_reciclagem implica agrupamento; os outros tipos não decidem"))
            else:
                why = ("classificador carregado mas sem resultado" if d.cls in subclassifiers
                       else f"sem modelo (models/subclassifier_{d.cls}.pt não existe)")
                a["tipo_instalacao"] = _attr(UNAVAILABLE, reason=why)
                a["individual_vs_agrupamento"] = _attr(UNAVAILABLE, reason="depende de tipo_instalacao")
            a["fracao_material"] = _attr(NOT_IN_CONTRACT, reason="não definido em classes.yaml nem em Detection")
            a["enchimento"] = _attr(NOT_IN_CONTRACT, reason="extra no Plano.md; sem campo nem dados rotulados")
        elif fam == "iluminacao":
            if d.subclass is not None:
                raise ValueError(f"det {i}: {d.cls} não tem subclasses em classes.yaml, obtido {d.subclass!r}")
            a["tipo"] = _attr(FROM_DETECTOR, d.cls)
            a["estado_operacional"] = _attr(NOT_IN_CONTRACT, reason="sem campo nem dados (lâmpada, defeitos)")
            a["poste_torto"] = _attr(NOT_IN_CONTRACT, reason="extra no Plano.md; sem campo nem dados")
        elif fam == "sinal":
            a["tipo_sinal"] = (_attr(CLASSIFIED, d.subclass, d.subscore) if d.subclass is not None
                               else _attr(UNAVAILABLE, reason="sem classificador de sinais ativo"))
        else:
            rec["branch"] = None
            rec["note"] = f"classe {d.cls!r} sem família em classes.yaml (family_of)"
        out.append(rec)
    return out
