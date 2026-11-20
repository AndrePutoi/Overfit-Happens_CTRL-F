"""Reclamações dos cidadãos sobre o mobiliário urbano.

O cidadão (perfil público) pode dizer que um elemento verificado:
  - posicao   está no sítio errado (e propor a posição certa no mapa);
  - estado    está partido, sujo ou vandalizado (com foto opcional);
  - tipo      foi identificado com o tipo errado (e propor o tipo certo);
  - duplicado é o mesmo objeto que outro elemento do mapa;
  - nao_mobiliario   não é mobiliário urbano (deteção errada);
  - outro     outro problema, descrito no comentário (obrigatório).

O técnico vê todas as reclamações, marca-as como "a resolver" ou "resolvido", pode deixar uma
resposta pública e descarregar tudo em CSV. O público vê o estado de cada reclamação, mas não
a mensagem escrita nem a foto (podem ter dados pessoais).
"""
import csv
import io
import json
import os
import uuid
from datetime import datetime
from typing import Callable, Optional

from fastapi import Depends, FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from . import acoes
from . import taxonomia as tx
from .db import pool

KINDS = ("posicao", "estado", "tipo", "duplicado", "nao_mobiliario", "outro")
CONDITIONS = ("partido", "sujo", "vandalizado", "outro")
STATUSES = ("por_resolver", "a_resolver", "resolvido")
VERIFIED = ("validado", "corrigido")
MAX_PHOTO_BYTES = 8 * 1024 * 1024
MAX_MOVE_M = 300          # uma posição proposta a mais de 300 m é quase de certeza um engano
PHOTO_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "image/heic": ".heic"}

KIND_LABELS = {"posicao": "Posição errada", "estado": "Partido, sujo ou vandalizado",
               "tipo": "Tipo errado", "duplicado": "Duplicado",
               "nao_mobiliario": "Não é mobiliário urbano", "outro": "Outros"}
CONDITION_LABELS = {"partido": "Partido", "sujo": "Sujo", "vandalizado": "Vandalizado", "outro": "Outro problema"}
STATUS_LABELS = {"por_resolver": "Por resolver", "a_resolver": "A resolver", "resolvido": "Resolvido"}

SELECT = """
SELECT c.*, e.name AS element_current_name, e.status AS element_status,
       ST_Y(e.geom) AS element_lat, ST_X(e.geom) AS element_lon,
       CASE WHEN c.suggested_lat IS NULL OR e.geom IS NULL THEN NULL
            ELSE ST_Distance(e.geom::geography, ST_SetSRID(ST_MakePoint(c.suggested_lon, c.suggested_lat), 4326)::geography)
       END AS suggested_distance_m,
       d.name AS duplicate_name
FROM complaint c
LEFT JOIN element e ON e.ext_id = c.element_ext_id
LEFT JOIN element d ON d.ext_id = c.duplicate_of
"""


MIGRATIONS = ("03_reclamacoes.sql", "04_entrega_v13.sql", "05_nomes_regulamentacao.sql")


def migrate_conn(conn):
    """Atualiza uma base de dados que já existia (reclamações e entrega v1.3), sem a apagar."""
    for name in MIGRATIONS:
        path = os.path.join(os.environ.get("DB_INIT_DIR", "/app/db/init"), name)
        if not os.path.exists(path):
            path = os.path.join(os.path.dirname(__file__), "..", "..", "db", "init", name)
        if os.path.exists(path):
            conn.execute(open(path, encoding="utf-8").read())
            conn.commit()


def migrate():
    with pool.connection() as conn:
        migrate_conn(conn)


def _iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def out(r: dict, public: bool) -> dict:
    o = {
        "id": r["id"],
        "element_id": r["element_ext_id"],
        "element_name": r["element_current_name"] or r["element_name"],
        "family": r["family"],
        "kind": r["kind"],
        "kind_label": KIND_LABELS[r["kind"]],
        "condition": r["condition"],
        "condition_label": CONDITION_LABELS.get(r["condition"]),
        "suggested_lat": r["suggested_lat"],
        "suggested_lon": r["suggested_lon"],
        "suggested_distance_m": round(r["suggested_distance_m"], 1) if r["suggested_distance_m"] is not None else None,
        "suggested": r["suggested"],
        "suggested_label": r["suggested_label"],
        "duplicate_of": r["duplicate_of"],
        "duplicate_name": r["duplicate_name"],
        "status": r["status"],
        "status_label": STATUS_LABELS[r["status"]],
        "response": r["response"],
        "has_photo": bool(r["photo_path"]),
        "created_at": _iso(r["created_at"]),
        "updated_at": _iso(r["updated_at"]),
        "resolved_at": _iso(r["resolved_at"]),
    }
    if not public:
        o.update({"message": r["message"], "updated_by": r["updated_by"], "element_status": r["element_status"],
                  "element_lat": r["element_lat"], "element_lon": r["element_lon"]})
    return o


def _element(conn, ref: str, public: bool, what: str = "Elemento") -> dict:
    try:
        el = acoes.find_element(conn, ref)
    except acoes.AcaoErro:
        raise HTTPException(404, f"{what} não encontrado: {ref}")
    allowed = VERIFIED if public else acoes.ACTIVE
    if el["status"] not in allowed:
        raise HTTPException(404 if public else 409, f"{what} {ref} não está disponível para reclamações")
    return el


def _save_photo(photo: UploadFile, upload_dir: str) -> str:
    ext = PHOTO_TYPES.get((photo.content_type or "").lower())
    if not ext:
        raise HTTPException(415, "A foto tem de ser JPG, PNG, WEBP ou HEIC")
    data = photo.file.read(MAX_PHOTO_BYTES + 1)
    if len(data) > MAX_PHOTO_BYTES:
        raise HTTPException(413, "A foto não pode ter mais de 8 MB")
    if not data:
        raise HTTPException(400, "A foto está vazia")
    folder = os.path.join(upload_dir, "reclamacoes")
    os.makedirs(folder, exist_ok=True)
    name = uuid.uuid4().hex + ext
    with open(os.path.join(folder, name), "wb") as f:
        f.write(data)
    return f"reclamacoes/{name}"


class ComplaintPatch(BaseModel):
    status: Optional[str] = Field(None, description="por_resolver, a_resolver ou resolvido")
    response: Optional[str] = Field(None, max_length=1000, description="Resposta da câmara, visível para o público")


EXPORT_COLUMNS = ["id", "criada_em", "elemento", "nome_elemento", "familia", "reclamacao", "estado_equipamento",
                  "lat_sugerida", "lon_sugerida", "distancia_sugerida_m", "tipo_sugerido", "duplicado_de",
                  "mensagem", "tem_foto", "estado", "resposta", "atualizado_por", "atualizado_em", "resolvida_em",
                  "lat_elemento", "lon_elemento"]


def register(app: FastAPI, technician: Callable, viewer: Callable, upload_dir: Callable[[], str]):
    """Acrescenta as rotas das reclamações à API (as dependências de autenticação vêm de main)."""

    @app.post("/complaints", tags=["reclamações"], status_code=201,
              summary="Criar uma reclamação sobre um elemento (perfil público: só elementos verificados)")
    def create_complaint(
        element_id: str = Form(..., description="Elemento, ex.: sin-aveiro-00160"),
        kind: str = Form(..., description="posicao, estado, tipo, duplicado, nao_mobiliario ou outro"),
        condition: Optional[str] = Form(None, description="estado: partido, sujo, vandalizado ou outro"),
        lat: Optional[float] = Form(None, ge=-90, le=90, description="posicao: latitude proposta"),
        lon: Optional[float] = Form(None, ge=-180, le=180, description="posicao: longitude proposta"),
        suggested: Optional[str] = Form(None, description='tipo: JSON, ex.: {"subclass": "regulatory_stop"}'),
        duplicate_of: Optional[str] = Form(None, description="duplicado: o outro elemento"),
        message: Optional[str] = Form(None, max_length=1000),
        photo: Optional[UploadFile] = File(None, description="Foto opcional (sem rostos nem matrículas), até 8 MB"),
        t: Optional[dict] = Depends(viewer),
    ):
        public = t is None
        if kind not in KINDS:
            raise HTTPException(422, f"Tipo de reclamação desconhecido: {kind}")
        message = (message or "").strip() or None
        with pool.connection() as conn:
            el = _element(conn, element_id, public)
            row = {"condition": None, "lat": None, "lon": None, "suggested": None, "label": None, "dup": None}

            if kind == "posicao":
                if lat is None or lon is None:
                    raise HTTPException(422, "Indique no mapa a posição certa (lat e lon)")
                dist = conn.execute(
                    "SELECT ST_Distance(geom::geography, ST_SetSRID(ST_MakePoint(%s, %s), 4326)::geography) AS d "
                    "FROM element WHERE id = %s", [lon, lat, el["id"]]).fetchone()["d"]
                if dist > MAX_MOVE_M:
                    raise HTTPException(422, f"A posição proposta está a {round(dist)} m do elemento; "
                                             f"o máximo é {MAX_MOVE_M} m. Confirme se escolheu o elemento certo.")
                row.update(lat=lat, lon=lon)

            elif kind == "estado":
                if condition not in CONDITIONS:
                    raise HTTPException(422, "Indique o estado: partido, sujo, vandalizado ou outro")
                row["condition"] = condition

            elif kind == "tipo":
                try:
                    s = json.loads(suggested or "")
                    assert isinstance(s, dict)
                except (ValueError, AssertionError):
                    raise HTTPException(422, "Indique o tipo certo")
                state = {"family": el["family"], "class": s.get("class") or el["class"],
                         "subclass": s.get("subclass"), "install_type": s.get("install_type"), "color": s.get("color")}
                v = tx.validate(state)   # TaxonomiaError -> 422
                clean = {k: v[k] for k in ("class", "subclass", "install_type", "color") if v[k] is not None}
                current = {k: el[k] for k in ("class", "subclass", "install_type", "color") if el[k] is not None}
                if clean == current:
                    raise HTTPException(422, "O tipo proposto é igual ao atual")
                row.update(suggested=json.dumps(clean), label=v["name"])

            elif kind == "duplicado":
                if not duplicate_of:
                    raise HTTPException(422, "Indique o elemento repetido")
                other = _element(conn, duplicate_of, public, "Elemento repetido")
                if other["id"] == el["id"]:
                    raise HTTPException(422, "Escolha um elemento diferente")
                row["dup"] = other["ext_id"]

            elif kind == "outro":
                if not message or len(message) < 5:
                    raise HTTPException(422, "Descreva o problema no comentário")

            photo_path = _save_photo(photo, upload_dir()) if photo is not None and photo.filename else None
            r = conn.execute("""
                INSERT INTO complaint (element_ext_id, element_name, family, kind, condition, suggested_lat, suggested_lon,
                                       suggested, suggested_label, duplicate_of, message, photo_path)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                [el["ext_id"], el["name"], el["family"], kind, row["condition"], row["lat"], row["lon"],
                 row["suggested"], row["label"], row["dup"], message, photo_path]).fetchone()
            return out(conn.execute(f"{SELECT} WHERE c.id = %s", [r["id"]]).fetchone(), public)

    @app.get("/complaints", tags=["reclamações"],
             summary="Reclamações e contagens por estado (o público não vê a mensagem nem a foto)")
    def list_complaints(status: Optional[str] = Query(None, description="por_resolver, a_resolver, resolvido (vírgulas)"),
                        kind: Optional[str] = Query(None, description="posicao, estado, tipo, duplicado, nao_mobiliario, outro (vírgulas)"),
                        element_id: Optional[str] = None,
                        ids: Optional[str] = Query(None, description="Só estas reclamações (vírgulas)"),
                        t: Optional[dict] = Depends(viewer)):
        clauses, params = [], []
        for col, val in (("c.status", status), ("c.kind", kind), ("c.element_ext_id", element_id)):
            vals = [v.strip() for v in (val or "").split(",") if v.strip()]
            if vals:
                clauses.append(f"{col} = ANY(%s)")
                params.append(vals)
        if ids:
            try:
                clauses.append("c.id = ANY(%s)")
                params.append([int(x) for x in ids.split(",") if x.strip()])
            except ValueError:
                raise HTTPException(400, "ids inválidos")
        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        with pool.connection() as conn:
            rows = conn.execute(f"{SELECT}{where} ORDER BY c.created_at DESC, c.id DESC LIMIT 5000", params).fetchall()
            counts = {r["status"]: r["n"] for r in conn.execute("SELECT status, count(*) AS n FROM complaint GROUP BY 1").fetchall()}
        return {"counts": {s: counts.get(s, 0) for s in STATUSES},
                "items": [out(r, t is None) for r in rows]}

    @app.get("/complaints/export.csv", tags=["reclamações"], summary="Todas as reclamações em CSV (técnico)")
    def export_complaints(sep: str = Query(";"), t: dict = Depends(technician)):
        if sep not in (",", ";", "\t"):
            raise HTTPException(400, "Separador inválido")
        with pool.connection() as conn:
            rows = conn.execute(f"{SELECT} ORDER BY c.id").fetchall()
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, delimiter=sep)
        w.writeheader()
        for r in rows:
            w.writerow({
                "id": r["id"], "criada_em": _iso(r["created_at"]), "elemento": r["element_ext_id"],
                "nome_elemento": r["element_current_name"] or r["element_name"], "familia": r["family"],
                "reclamacao": KIND_LABELS[r["kind"]], "estado_equipamento": CONDITION_LABELS.get(r["condition"]),
                "lat_sugerida": r["suggested_lat"], "lon_sugerida": r["suggested_lon"],
                "distancia_sugerida_m": round(r["suggested_distance_m"], 1) if r["suggested_distance_m"] is not None else None,
                "tipo_sugerido": r["suggested_label"], "duplicado_de": r["duplicate_of"], "mensagem": r["message"],
                "tem_foto": "sim" if r["photo_path"] else "não", "estado": STATUS_LABELS[r["status"]],
                "resposta": r["response"], "atualizado_por": r["updated_by"], "atualizado_em": _iso(r["updated_at"]),
                "resolvida_em": _iso(r["resolved_at"]), "lat_elemento": r["element_lat"], "lon_elemento": r["element_lon"],
            })
        return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="reclamacoes_ctrlf_{datetime.now():%Y%m%d_%H%M}.csv"'})

    @app.get("/complaints/{complaint_id}/photo", tags=["reclamações"], summary="Foto da reclamação (técnico)")
    def complaint_photo(complaint_id: int, t: dict = Depends(technician)):
        with pool.connection() as conn:
            r = conn.execute("SELECT photo_path FROM complaint WHERE id = %s", [complaint_id]).fetchone()
        if not r or not r["photo_path"]:
            raise HTTPException(404, "Sem foto")
        path = os.path.join(upload_dir(), r["photo_path"])
        if not os.path.exists(path):
            raise HTTPException(404, "Foto não encontrada")
        return FileResponse(path)

    @app.patch("/complaints/{complaint_id}", tags=["reclamações"],
               summary="Mudar o estado (por resolver, a resolver, resolvido) e/ou a resposta pública (técnico)")
    def patch_complaint(complaint_id: int, body: ComplaintPatch, t: dict = Depends(technician)):
        ch = body.model_dump(exclude_unset=True)
        if not ch:
            raise HTTPException(400, "Nada para alterar")
        if "status" in ch and ch["status"] not in STATUSES:
            raise HTTPException(422, "Estado inválido: use por_resolver, a_resolver ou resolvido")
        if "response" in ch:
            ch["response"] = (ch["response"] or "").strip() or None
        sets = [f"{k} = %s" for k in ch] + ["updated_by = %s", "updated_at = now()"]
        if "status" in ch:
            sets.append("resolved_at = CASE WHEN %s = 'resolvido' THEN coalesce(resolved_at, now()) ELSE NULL END")
        params = list(ch.values()) + [t["name"]] + ([ch["status"]] if "status" in ch else []) + [complaint_id]
        with pool.connection() as conn:
            r = conn.execute(f"UPDATE complaint SET {', '.join(sets)} WHERE id = %s RETURNING id", params).fetchone()
            if not r:
                raise HTTPException(404, "Reclamação não encontrada")
            return out(conn.execute(f"{SELECT} WHERE c.id = %s", [complaint_id]).fetchone(), False)
