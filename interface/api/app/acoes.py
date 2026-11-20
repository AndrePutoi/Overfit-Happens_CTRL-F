"""Ações do técnico sobre o catálogo.

Usadas pela API (uma ação por pedido) e pelo importador (que volta a aplicar as decisões
guardadas depois de cada reimportação da entrega). Cada ação, quando record=True, escreve
uma linha em edit_log com a decisão no formato "decisoes" do pipeline.
"""
import json
from datetime import datetime, timezone
from typing import Optional

from . import taxonomia as tx

ACTIVE = ("auto", "validado", "corrigido")


class AcaoErro(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.message = message


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _json(v) -> str:
    return json.dumps(v, default=str, ensure_ascii=False)


def find_element(conn, ref: str, lock: bool = False) -> dict:
    """Aceita o ext_id (ex.: sin-aveiro-00001) ou o id numérico interno."""
    sql = "SELECT *, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM element WHERE ext_id = %s"
    params = [ref]
    if ref.isdigit():
        sql = "SELECT *, ST_Y(geom) AS lat, ST_X(geom) AS lon FROM element WHERE ext_id = %s OR id = %s"
        params = [ref, int(ref)]
    row = conn.execute(sql + (" FOR UPDATE" if lock else ""), params).fetchone()
    if not row:
        raise AcaoErro(404, f"Elemento não encontrado: {ref}")
    return row


def log(conn, ext_id: str, who: str, action: str, before: dict, after: dict, decision: dict,
        at: Optional[str] = None):
    decision = {"element_id": ext_id, **decision, "decided_by": who, "decided_at": at or now_iso()}
    conn.execute(
        "INSERT INTO edit_log (element_ext_id, who, action, at, before, after, decision) VALUES (%s, %s, %s, %s, %s, %s, %s)",
        [ext_id, who, action, decision["decided_at"], _json(before), _json(after), _json(decision)])


def recompute(conn, element_id: int, keep_best: bool = True):
    """Recalcula vistas, confiança, ordem e melhor deteção depois de juntar ou separar.

    Confiança = 1 - prod(1 - s_i) sobre a melhor pontuação de cada imagem (o fator
    geométrico do pipeline volta a ser calculado na próxima entrega).
    """
    conn.execute("""
        WITH ranked AS (
          SELECT id, row_number() OVER (ORDER BY quality DESC NULLS LAST, score DESC) AS r
          FROM detection WHERE element_id = %s)
        UPDATE detection d SET rank = ranked.r FROM ranked WHERE d.id = ranked.id""", [element_id])
    conn.execute("""
        UPDATE element e SET
          n_views = agg.n,
          confidence = LEAST(1.0, agg.c),
          best_detection_id = CASE
              WHEN %s AND e.best_detection_id IN (SELECT id FROM detection WHERE element_id = e.id)
              THEN e.best_detection_id ELSE agg.best END
        FROM (
          SELECT count(*) AS n,
                 1 - exp(sum(ln(GREATEST(1e-6, 1 - s)))) AS c,
                 (SELECT id FROM detection WHERE element_id = %s ORDER BY rank LIMIT 1) AS best
          FROM (SELECT image_id, max(score) AS s FROM detection WHERE element_id = %s GROUP BY image_id) per_image
        ) agg
        WHERE e.id = %s""", [keep_best, element_id, element_id, element_id])


def _best_detection_class(conn, element: dict) -> Optional[str]:
    if not element.get("best_detection_id"):
        return None
    r = conn.execute("SELECT class FROM detection WHERE id = %s", [element["best_detection_id"]]).fetchone()
    return r["class"] if r else None


# ------------------------------------------------------------------ estado

def set_status(conn, ref: str, who: str, new_status: str, action: str, allowed_from: tuple,
               record: bool = True, at: Optional[str] = None, note: Optional[str] = None) -> str:
    el = find_element(conn, ref, lock=True)
    if el["status"] == new_status:
        return el["ext_id"]
    if el["status"] not in allowed_from:
        raise AcaoErro(409, f"Não é possível passar de '{el['status']}' para '{new_status}'")
    conn.execute("UPDATE element SET status = %s, updated_by = %s, updated_at = coalesce(%s::timestamptz, now()) WHERE id = %s",
                 [new_status, who, at, el["id"]])
    if record:
        decision = {"status_reset": True} if new_status == "auto" else {"status": new_status}
        if note:
            decision["note"] = note
        log(conn, el["ext_id"], who, action, {"status": el["status"]}, {"status": new_status}, decision, at)
    return el["ext_id"]


def validate(conn, ref, who, **kw):
    return set_status(conn, ref, who, "validado", "validar", ("auto",), **kw)


def reject(conn, ref, who, **kw):
    return set_status(conn, ref, who, "rejeitado", "rejeitar", ACTIVE, **kw)


def restore(conn, ref, who, **kw):
    return set_status(conn, ref, who, "auto", "repor", ("rejeitado",), **kw)


# ------------------------------------------------------------------ correção

EDITABLE = ("class", "subclass", "install_type", "color", "address")


def correct(conn, ref: str, who: str, changes: dict, record: bool = True, at: Optional[str] = None,
            note: Optional[str] = None) -> str:
    """changes pode ter: class, subclass, install_type, color, address, lat, lon."""
    el = find_element(conn, ref, lock=True)
    if el["status"] == "fundido":
        raise AcaoErro(409, "Elemento fundido noutro; corrija o elemento de destino")

    new = {k: el[k] for k in EDITABLE}
    type_fields = {"class", "subclass", "install_type", "color"} & changes.keys()
    for k in type_fields | ({"address"} & changes.keys()):
        new[k] = changes[k]
    if type_fields:
        state = {"family": el["family"], **{k: new[k] for k in ("class", "subclass", "install_type", "color")},
                 "detection_class": _best_detection_class(conn, el)}
        # ao trocar contentor <-> subterrâneo, o tipo de instalação antigo deixa de fazer sentido
        if "class" in changes and "install_type" not in changes:
            state["install_type"] = None
        try:
            v = tx.validate(state)
        except tx.TaxonomiaError as e:
            raise AcaoErro(422, str(e))
        new.update({k: v[k] for k in ("class", "subclass", "install_type", "color")})
        derived = {k: v[k] for k in ("sign_group", "code", "name")}
    else:
        derived = {k: el[k] for k in ("sign_group", "code", "name")}

    lat, lon = changes.get("lat", el["lat"]), changes.get("lon", el["lon"])
    if (lat is None) != (lon is None):
        raise AcaoErro(422, "Indique lat e lon juntos")
    moved = abs(lat - el["lat"]) > 1e-9 or abs(lon - el["lon"]) > 1e-9

    before = {k: el[k] for k in EDITABLE if el[k] != new[k]}
    after = {k: new[k] for k in EDITABLE if el[k] != new[k]}
    if moved:
        before.update(lat=el["lat"], lon=el["lon"])
        after.update(lat=lat, lon=lon)
    if not after:
        return el["ext_id"]

    conn.execute(f"""
        UPDATE element SET {', '.join(f'{k} = %s' for k in EDITABLE)},
               sign_group = %s, code = %s, name = %s,
               geom = ST_SetSRID(ST_MakePoint(%s, %s), 4326),
               geo_method = CASE WHEN %s THEN 'manual' ELSE geo_method END,
               position_reliable = CASE WHEN %s THEN true ELSE position_reliable END,
               status = 'corrigido', updated_by = %s, updated_at = coalesce(%s::timestamptz, now())
        WHERE id = %s""",
        [new[k] for k in EDITABLE] + [derived["sign_group"], derived["code"], derived["name"],
                                      lon, lat, moved, moved, who, at, el["id"]])
    if record:
        before["status"], after["status"] = el["status"], "corrigido"
        decision = {"status": "corrigido", **{k: v for k, v in after.items() if k != "status"}}
        if note:
            decision["note"] = note
        action = "mover" if moved and set(after) <= {"lat", "lon", "status"} else "corrigir"
        log(conn, el["ext_id"], who, action, before, after, decision, at)
    return el["ext_id"]


def set_best(conn, ref: str, who: str, detection_ref: str, record: bool = True, at: Optional[str] = None) -> str:
    el = find_element(conn, ref, lock=True)
    det = conn.execute("SELECT id, ext_id, element_id FROM detection WHERE ext_id = %s", [detection_ref]).fetchone()
    if not det or det["element_id"] != el["id"]:
        raise AcaoErro(422, f"A deteção {detection_ref} não pertence ao elemento {el['ext_id']}")
    if det["id"] == el["best_detection_id"]:
        return el["ext_id"]
    old = conn.execute("SELECT ext_id FROM detection WHERE id = %s", [el["best_detection_id"]]).fetchone() if el["best_detection_id"] else None
    conn.execute("UPDATE element SET best_detection_id = %s, updated_by = %s, updated_at = coalesce(%s::timestamptz, now()) WHERE id = %s",
                 [det["id"], who, at, el["id"]])
    if record:
        log(conn, el["ext_id"], who, "melhor_imagem", {"best_detection_id": old["ext_id"] if old else None},
            {"best_detection_id": det["ext_id"]}, {"best_detection_id": det["ext_id"]}, at)
    return el["ext_id"]


# ------------------------------------------------------------------ juntar e separar

def merge(conn, ref: str, into_ref: str, who: str, record: bool = True, at: Optional[str] = None) -> str:
    src = find_element(conn, ref, lock=True)
    dst = find_element(conn, into_ref, lock=True)
    if src["id"] == dst["id"]:
        raise AcaoErro(422, "Não se pode juntar um elemento a si próprio")
    if src["family"] != dst["family"]:
        raise AcaoErro(422, "Só se juntam elementos da mesma família")
    if src["status"] == "fundido" or dst["status"] not in ACTIVE:
        raise AcaoErro(409, "Um dos elementos já não está ativo")

    conn.execute("UPDATE detection SET element_id = %s WHERE element_id = %s", [dst["id"], src["id"]])
    conn.execute("UPDATE element SET parent_id = %s WHERE parent_id = %s", [dst["id"], src["id"]])
    recompute(conn, dst["id"])
    conn.execute("""UPDATE element SET status = 'fundido', merged_into = %s, best_detection_id = NULL, n_views = 0,
                    updated_by = %s, updated_at = coalesce(%s::timestamptz, now()) WHERE id = %s""",
                 [dst["id"], who, at, src["id"]])
    conn.execute("UPDATE element SET updated_by = %s, updated_at = coalesce(%s::timestamptz, now()) WHERE id = %s",
                 [who, at, dst["id"]])
    # grupo de duplicados resolvido quando só lhe resta um elemento ativo
    for gid in {src["duplicate_group_id"], dst["duplicate_group_id"]} - {None}:
        conn.execute("""UPDATE duplicate_group g SET resolved = (
                          SELECT count(*) <= 1 FROM element WHERE duplicate_group_id = g.id AND status = ANY(%s))
                        WHERE id = %s""", [list(ACTIVE), gid])
    if record:
        new_dst = conn.execute("SELECT n_views, confidence FROM element WHERE id = %s", [dst["id"]]).fetchone()
        log(conn, src["ext_id"], who, "fundir", {"status": src["status"]},
            {"status": "fundido", "merged_into": dst["ext_id"]}, {"merge_into": dst["ext_id"]}, at)
        log(conn, dst["ext_id"], who, "fundir",
            {"n_views": dst["n_views"], "confidence": dst["confidence"]},
            {"n_views": new_dst["n_views"], "confidence": new_dst["confidence"], "absorbed": src["ext_id"]},
            {"absorbed": src["ext_id"]}, at)
    return dst["ext_id"]


def split(conn, ref: str, detection_refs: list[str], who: str, record: bool = True, at: Optional[str] = None) -> str:
    """Tira as deteções indicadas do elemento e cria um elemento novo com elas.

    O novo elemento fica na mesma posição (o técnico pode depois movê-lo) e com o id
    <ext_id>-s<n>. Devolve o ext_id do novo elemento.
    """
    el = find_element(conn, ref, lock=True)
    if el["status"] == "fundido":
        raise AcaoErro(409, "Elemento fundido noutro")
    if not detection_refs:
        raise AcaoErro(422, "Indique pelo menos uma deteção")
    dets = conn.execute("SELECT id, ext_id FROM detection WHERE element_id = %s", [el["id"]]).fetchall()
    own = {d["ext_id"]: d["id"] for d in dets}
    missing = [d for d in detection_refs if d not in own]
    if missing:
        raise AcaoErro(422, f"Deteções que não pertencem a {el['ext_id']}: {', '.join(missing)}")
    if len(set(detection_refs)) >= len(own):
        raise AcaoErro(422, "O elemento tem de ficar com pelo menos uma deteção")

    n = conn.execute("SELECT count(*) AS n FROM element WHERE split_from = %s", [el["id"]]).fetchone()["n"] + 1
    new_ext = f"{el['ext_id']}-s{n}"
    while conn.execute("SELECT 1 FROM element WHERE ext_id = %s", [new_ext]).fetchone():
        n += 1
        new_ext = f"{el['ext_id']}-s{n}"
    new = conn.execute("""
        INSERT INTO element (ext_id, municipality_id, family, class, subclass, sign_group, code, name,
                             install_type, color, geom, position_original, geo_method, position_reliable,
                             address, status, split_from, first_seen_at, updated_by, updated_at)
        SELECT %s, municipality_id, family, class, subclass, sign_group, code, name,
               install_type, color, geom, position_original, 'separado', false,
               address, 'corrigido', id, first_seen_at, %s, coalesce(%s::timestamptz, now())
        FROM element WHERE id = %s
        RETURNING id""", [new_ext, who, at, el["id"]]).fetchone()
    conn.execute("UPDATE detection SET element_id = %s WHERE id = ANY(%s)",
                 [new["id"], [own[d] for d in detection_refs]])
    recompute(conn, el["id"])
    recompute(conn, new["id"], keep_best=False)
    conn.execute("UPDATE element SET updated_by = %s, updated_at = coalesce(%s::timestamptz, now()) WHERE id = %s",
                 [who, at, el["id"]])
    if record:
        log(conn, el["ext_id"], who, "separar", {}, {"new_element": new_ext, "detections": detection_refs},
            {"split_detection_ids": detection_refs, "new_element_id": new_ext}, at)
    return new_ext


# ------------------------------------------------------------------ decisões no formato do pipeline

def apply_decision(conn, d: dict, record: bool = True) -> Optional[str]:
    """Aplica uma decisão no formato "decisoes" do pipeline. Devolve o ext_id afetado."""
    ref, who, at = d.get("element_id"), d.get("decided_by"), d.get("decided_at")
    if not ref or not who:
        raise AcaoErro(422, "Cada decisão precisa de element_id e decided_by")
    kw = {"record": record, "at": at}
    result = ref

    if d.get("split_detection_ids"):
        split(conn, ref, d["split_detection_ids"], who, **kw)
    if d.get("merge_into"):
        return merge(conn, ref, d["merge_into"], who, **kw)
    if d.get("best_detection_id"):
        set_best(conn, ref, who, d["best_detection_id"], **kw)

    changes = {k: d[k] for k in ("class", "subclass", "install_type", "color", "address", "lat", "lon") if k in d}
    if changes:
        correct(conn, ref, who, changes, note=d.get("note"), **kw)

    status = d.get("status")
    if d.get("status_reset"):
        restore(conn, ref, who, **kw)
    elif status == "validado":
        el = find_element(conn, ref)
        if el["status"] == "auto":
            validate(conn, ref, who, note=d.get("note"), **kw)
    elif status == "rejeitado":
        reject(conn, ref, who, note=d.get("note"), **kw)
    elif status == "corrigido" and not changes:
        el = find_element(conn, ref, lock=True)
        if el["status"] in ("auto", "validado"):
            conn.execute("UPDATE element SET status = 'corrigido', updated_by = %s, updated_at = coalesce(%s::timestamptz, now()) WHERE id = %s",
                         [who, at, el["id"]])
            if record:
                log(conn, el["ext_id"], who, "corrigir", {"status": el["status"]}, {"status": "corrigido"},
                    {"status": "corrigido"}, at)
    elif status not in (None, "corrigido"):
        raise AcaoErro(422, f"Estado inválido: {status}")
    return result
