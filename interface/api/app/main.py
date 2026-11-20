"""CTRL+F — API do catálogo de mobiliário urbano (versão 2).

Os elementos saem no formato da entrega do pipeline (elementos.geojson, esquema 1.0), com
campos extra para a interface. As decisões do técnico entram e saem no formato "decisoes".
Documentação interativa em /docs.
"""
import csv
import io
import json
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import Body, Depends, FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import acoes
from . import reclamacoes
from . import taxonomia as tx
from .db import pool

MEDIA_DIR = os.environ.get("MEDIA_DIR", "/data/media")      # imagens já desfocadas e recortes
UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "/data/uploads")  # vídeos por processar (temporários)
CORS_ORIGINS = os.environ.get("CORS_ORIGINS", "http://localhost:5173").split(",")
ACTIVE = acoes.ACTIVE


@asynccontextmanager
async def lifespan(app: FastAPI):
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    pool.open()
    reclamacoes.migrate()   # cria a tabela das reclamações numa base de dados já existente
    yield
    pool.close()


app = FastAPI(
    title="CTRL+F API",
    description="Catálogo georreferenciado de sinais, iluminação e resíduos (Aveiro Tech City Hackathon 2026, desafio 2). "
                "Os elementos seguem o formato da entrega do pipeline (esquema 1.0). "
                "Sem o cabeçalho X-Tecnico-Token, a API responde no perfil público: só elementos verificados por um técnico.",
    version="2.0.0",
    lifespan=lifespan,
)
app.add_middleware(GZipMiddleware, minimum_size=2000)
app.add_middleware(CORSMiddleware, allow_origins=CORS_ORIGINS, allow_methods=["*"], allow_headers=["*"])
os.makedirs(MEDIA_DIR, exist_ok=True)
app.mount("/media", StaticFiles(directory=MEDIA_DIR, check_dir=False), name="media")


@app.exception_handler(acoes.AcaoErro)
def acao_error(_, exc: acoes.AcaoErro):
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.message})


@app.exception_handler(tx.TaxonomiaError)
def taxonomy_error(_, exc: tx.TaxonomiaError):
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# ---------------------------------------------------------------- utilitários

def csv_list(value: Optional[str]) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def media_url(path: Optional[str]) -> Optional[str]:
    return f"/media/{path}" if path else None


def iso(v):
    return v.isoformat() if isinstance(v, datetime) else v


def uncertainty(row: dict) -> float:
    if row["position_reliable"]:
        # triangulado: o resíduo da triangulação, com um mínimo de 3 m (erro do GPS das câmaras)
        return max(3.0, round(row["geo_residual"] or 0, 1))
    # vista única: a incerteza calculada pelo pipeline (v1.2+), senão o valor típico da taxonomia
    if row.get("position_sigma_m"):
        return max(3.0, round(row["position_sigma_m"], 1))
    return tx.single_view_uncertainty_m()


FLUXOS = {"indiferenciado": ("Indiferenciado", "cinzento"), "embalagens": ("Embalagens", "amarelo"),
          "papel": ("Papel e cartão", "azul"), "vidro": ("Vidro", "verde"),
          "organicos": ("Biorresíduos", "castanho"), "pilhas": ("Pilhas", "vermelho")}


def ilha_out(ilha):
    """Ilha de reciclagem (ilhas.json) com rótulos: a composição é uma sugestão do classificador."""
    if not ilha:
        return None
    comp = [{"fluxo": k, "label": FLUXOS.get(k, (k, None))[0], "color": FLUXOS.get(k, (k, None))[1], "n": n}
            for k, n in sorted((ilha.get("composicao_estimada") or {}).items(), key=lambda kv: -kv[1])]
    return {**ilha, "composicao": comp}


def serialize(row: dict) -> dict:
    """Uma linha de ELEMENT_SELECT -> propriedades no formato da entrega + campos da interface."""
    color = tx.color_info(row["color"])
    return {
        # --- formato da entrega (elementos.schema.json)
        "id": row["ext_id"],
        "family": row["family"],
        "class": row["class"],
        "subclass": row["subclass"],
        "confidence": round(row["confidence"], 3) if row["confidence"] is not None else None,
        "n_views": row["n_views"],
        "status": row["status"],
        "geo_method": row["geo_method"],
        "geo_residual": row["geo_residual"],
        "position_reliable": row["position_reliable"],
        "position_original": {"lat": row["orig_lat"], "lon": row["orig_lon"]} if row["orig_lat"] is not None else None,
        "road_adjustment_m": row["road_adjustment_m"],
        "road_adjustment_method": row["road_adjustment_method"],
        "n_units": row["n_units"],
        "osm_ref_match": row["osm_ref_match"],
        "observations": row["observations"],
        "best_detection_id": row["best_detection_ext_id"],
        "duplicate_group_id": row["duplicate_group_id"],
        "duplicate_level": row.get("duplicate_level"),
        "position_method": row.get("position_method"),
        "position_sigma_m": row.get("position_sigma_m"),
        "clip_suspect": row.get("clip_suspect"),
        "auto_merged": row.get("auto_merged") or False,
        "merged_from": row.get("merged_from") or [],
        "ilha": ilha_out(row.get("ilha")),
        "fluxo_sugerido": ({"fluxo": row["fluxo_sugerido"], "label": FLUXOS.get(row["fluxo_sugerido"], (row["fluxo_sugerido"], None))[0],
                            "color": FLUXOS.get(row["fluxo_sugerido"], (None, None))[1], "p": row.get("fluxo_p")}
                           if row.get("fluxo_sugerido") else None),
        # --- campos da interface
        "family_label": tx.family_label(row["family"]),
        "class_label": tx.class_label(row["family"], row["class"]),
        "sign_group": row["sign_group"],
        "sign_group_label": tx.group_label(row["sign_group"]),
        "code": row["code"],
        "name": row["name"],
        "install_type": row["install_type"],
        "install_label": tx.install_label(row["install_type"]) or ("Por classificar" if row["class"] == "contentor" else None),
        "color": row["color"],
        "color_label": color["label"] if color else None,
        "color_waste": color["residuo"] if color else None,
        "lat": row["lat"],
        "lon": row["lon"],
        "uncertainty_m": uncertainty(row),
        "confidence_pct": round(100 * row["confidence"]) if row["confidence"] is not None else None,
        "review_state": row["review_state"],
        "address": row["address"],
        "parent_id": row["parent_ext_id"],
        "merged_into": row["merged_ext_id"],
        "split_from": row["split_from_ext_id"],
        "best": {
            "detection_id": row["best_detection_ext_id"],
            "image_id": row["best_image_ext_id"],
            "bbox": row["best_bbox"],
            "image_url": media_url(row["best_image_path"]),
            "crop_url": media_url(row["best_crop_path"]),
            "image_width": row["best_image_width"],
            "image_height": row["best_image_height"],
            "blur_audited": row["best_image_blur_audited"],
        },
        "source": {
            "key": row["source_key"],
            "name": row["source_name"],
            "license": row["source_license"],
            "attribution": row["source_attribution"],
        },
        "first_seen_at": iso(row["first_seen_at"]),
        "updated_by": row["updated_by"],
        "updated_at": iso(row["updated_at"]),
    }


def feature(row: dict, extra: Optional[dict] = None) -> dict:
    props = serialize(row)
    if extra:
        props.update(extra)
    return {"type": "Feature", "id": props["id"],
            "geometry": {"type": "Point", "coordinates": [row["lon"], row["lat"]]},
            "properties": props}


ELEMENT_SELECT = """
SELECT v.*, obs.observations
FROM v_element v
LEFT JOIN LATERAL (
  SELECT coalesce(json_agg(json_build_object(
           'detection_id', d.ext_id, 'image_id', i.ext_id, 'bbox', d.bbox,
           'score', d.score, 'quality', d.quality, 'rank', d.rank)
         ORDER BY d.rank NULLS LAST, d.score DESC), '[]'::json) AS observations
  FROM detection d JOIN image i ON i.id = d.image_id
  WHERE d.element_id = v.id
) obs ON true
"""


def bool_param(v: Optional[str]) -> Optional[bool]:
    if v is None or v == "":
        return None
    if v.lower() in ("true", "1", "sim", "yes"):
        return True
    if v.lower() in ("false", "0", "nao", "não", "no"):
        return False
    raise HTTPException(400, f"Valor booleano inválido: {v}")


# Tipo de ícone do elemento (igual a kindOf em web/src/tax.js), para filtrar como no mapa
KIND_SQL = """CASE
  WHEN {a}.family = 'sinal' THEN CASE
    WHEN {a}.subclass = 'regulatory_stop' THEN 'stop'
    WHEN {a}.sign_group = 'prioridade' THEN 'cedencia'
    WHEN {a}.sign_group IN ('perigo', 'proibicao', 'obrigacao', 'informacao', 'regulamentacao', 'complementar', 'orientacao')
      THEN {a}.sign_group
    ELSE 'desconhecido' END
  WHEN {a}.family = 'iluminacao' THEN CASE WHEN {a}.class = 'candeeiro' THEN 'candeeiro' ELSE 'poste' END
  WHEN {a}.family = 'mobiliario' THEN 'banco'
  WHEN {a}.class = 'subterraneo' THEN 'subterraneo'
  WHEN {a}.install_type = 'ilha' THEN 'ecoponto'
  WHEN {a}.install_type = 'indiferenciado' THEN 'contentor'
  ELSE 'por_classificar' END"""


class Filters:
    """Filtros comuns ao mapa, à fila de revisão e às exportações.

    Cada parâmetro aceita vários valores separados por vírgulas: dentro do mesmo parâmetro
    combinam com OU, entre parâmetros com E.
    """

    def __init__(
        self,
        family: Optional[str] = Query(None, description="sinal,iluminacao,residuos,mobiliario"),
        cls: Optional[str] = Query(None, alias="class", description="sinal,poste_luz,candeeiro,contentor,subterraneo"),
        subclass: Optional[str] = Query(None, description="Tipo de sinal, ex.: regulatory_stop,regulatory_yield. Com kind, combina com OU"),
        sign_group: Optional[str] = Query(None, description="prioridade,proibicao,obrigacao,regulamentacao,perigo,informacao,complementar,orientacao,desconhecido"),
        install_type: Optional[str] = Query(None, description="subterraneo,ilha,indiferenciado,por_classificar"),
        color: Optional[str] = Query(None),
        status: Optional[str] = Query(None, description="por_rever, verificado, auto, validado, corrigido, rejeitado, fundido ou todos. Por omissão: ativos"),
        min_conf: Optional[float] = Query(None, ge=0, le=1),
        min_conf_family: Optional[str] = Query(None, description="Famílias a que se aplica min_conf (vírgulas); por omissão, todas"),
        min_conf_familia: Optional[str] = Query(None, description="Confiança mínima por família, ex.: sinal:0.5,residuos:0.7"),
        reliable: Optional[str] = Query(None, description="true: só posições trianguladas; false: só aproximadas"),
        duplicates: Optional[str] = Query(None, description="true: só elementos num grupo de duplicados por resolver"),
        kind: Optional[str] = Query(None, description="Tipo de ícone: stop,cedencia,proibicao,obrigacao,regulamentacao,perigo,informacao,complementar,orientacao,desconhecido,candeeiro,poste,subterraneo,ecoponto,contentor,por_classificar"),
        q: Optional[str] = Query(None, description="Pesquisa por id, nome, código, tipo ou morada"),
        bbox: Optional[str] = Query(None, description="minLon,minLat,maxLon,maxLat"),
    ):
        self.family, self.cls, self.subclass = csv_list(family), csv_list(cls), csv_list(subclass)
        self.sign_group, self.install_type, self.color = csv_list(sign_group), csv_list(install_type), csv_list(color)
        self.status = self._statuses(csv_list(status))
        self.min_conf, self.q, self.bbox = min_conf, q, bbox
        self.min_conf_family = csv_list(min_conf_family)
        self.min_conf_familia: dict[str, float] = {}
        for item in csv_list(min_conf_familia):
            fam, _, val = item.partition(":")
            try:
                v = float(val)
            except ValueError:
                raise HTTPException(422, f"min_conf_familia inválido: {item}")
            if not 0 <= v <= 1:
                raise HTTPException(422, f"min_conf_familia fora de 0–1: {item}")
            self.min_conf_familia[fam.strip()] = v
        self.reliable, self.duplicates = bool_param(reliable), bool_param(duplicates)
        self.kind = csv_list(kind)

    @staticmethod
    def _statuses(values: list[str]) -> Optional[list[str]]:
        if not values:
            return list(ACTIVE)
        if "todos" in values:
            return None
        out: list[str] = []
        for v in values:
            out += {"por_rever": ["auto"], "verificado": ["validado", "corrigido"]}.get(v, [v])
        return out

    def where(self, alias: str = "v") -> tuple[str, list]:
        clauses, params = [], []
        for col, vals in (("family", self.family), ("class", self.cls),
                          ("sign_group", self.sign_group), ("color", self.color), ("status", self.status)):
            if vals:
                clauses.append(f"{alias}.{col} = ANY(%s)")
                params.append(vals)
        if self.install_type:
            parts = []
            known = [v for v in self.install_type if v != "por_classificar"]
            if known:
                parts.append(f"{alias}.install_type = ANY(%s)")
                params.append(known)
            if "por_classificar" in self.install_type:
                parts.append(f"({alias}.family = 'residuos' AND {alias}.install_type IS NULL)")
            clauses.append("(" + " OR ".join(parts) + ")")
        # kind (grupo do ícone) e subclass (tipo de sinal) combinam com OU, como nos filtros do mapa
        if self.kind and self.subclass:
            clauses.append(f"(({KIND_SQL.format(a=alias)}) = ANY(%s) OR {alias}.subclass = ANY(%s))")
            params += [self.kind, self.subclass]
        elif self.kind:
            clauses.append(f"({KIND_SQL.format(a=alias)}) = ANY(%s)")
            params.append(self.kind)
        elif self.subclass:
            clauses.append(f"{alias}.subclass = ANY(%s)")
            params.append(self.subclass)
        if self.min_conf is not None:
            if self.min_conf_family:   # só nestas famílias; as outras passam sem limite
                clauses.append(f"({alias}.family <> ALL(%s) OR {alias}.confidence >= %s)")
                params += [self.min_conf_family, self.min_conf]
            else:
                clauses.append(f"{alias}.confidence >= %s")
                params.append(self.min_conf)
        for fam, v in self.min_conf_familia.items():   # cada família com o seu limite
            clauses.append(f"({alias}.family <> %s OR {alias}.confidence >= %s)")
            params += [fam, v]
        if self.reliable is not None:
            clauses.append(f"{alias}.position_reliable = %s")
            params.append(self.reliable)
        if self.duplicates:
            clauses.append(f"{alias}.duplicate_group_id IN (SELECT id FROM duplicate_group WHERE NOT resolved)")
        if self.q:
            clauses.append(f"({alias}.ext_id ILIKE %s OR {alias}.name ILIKE %s OR coalesce({alias}.code, '') ILIKE %s "
                           f"OR coalesce({alias}.subclass, '') ILIKE %s OR coalesce({alias}.address, '') ILIKE %s)")
            params += [f"%{self.q}%"] * 5
        if self.bbox:
            try:
                b = [float(x) for x in self.bbox.split(",")]
                assert len(b) == 4
            except (ValueError, AssertionError):
                raise HTTPException(400, "bbox deve ser minLon,minLat,maxLon,maxLat")
            clauses.append(f"{alias}.geom && ST_MakeEnvelope(%s, %s, %s, %s, 4326)")
            params += b
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def fetch_elements(f: Filters, order: str = "v.family, v.ext_id", limit: int = 20000) -> list[dict]:
    where, params = f.where()
    with pool.connection() as conn:
        return conn.execute(f"{ELEMENT_SELECT}{where} ORDER BY {order} LIMIT %s", params + [limit]).fetchall()


def fetch_one(conn, ref: str) -> dict:
    el = acoes.find_element(conn, ref)
    return conn.execute(f"{ELEMENT_SELECT} WHERE v.id = %s", [el["id"]]).fetchone()


# ---------------------------------------------------------------- autenticação

def technician(x_tecnico_token: Optional[str] = Header(None, description="Token do técnico (demo: demo-ana)")) -> dict:
    if not x_tecnico_token:
        raise HTTPException(401, "Falta o cabeçalho X-Tecnico-Token")
    with pool.connection() as conn:
        t = conn.execute("SELECT id, name, role, municipality_id FROM technician WHERE token = %s", [x_tecnico_token]).fetchone()
    if not t:
        raise HTTPException(401, "Token inválido")
    return t


def viewer(x_tecnico_token: Optional[str] = Header(None, description="Token do técnico. Sem token: perfil público (só elementos verificados)")) -> Optional[dict]:
    """Técnico autenticado, ou None para o perfil público."""
    if not x_tecnico_token:
        return None
    return technician(x_tecnico_token)


VERIFIED = ["validado", "corrigido"]


def public_only(f: "Filters", t: Optional[dict]):
    """No perfil público só se veem os elementos já verificados por um técnico."""
    if t is None:
        allowed = VERIFIED if f.status is None else [s for s in f.status if s in VERIFIED]
        f.status = allowed or ["__nenhum__"]


# ---------------------------------------------------------------- sistema e catálogo

@app.get("/health", tags=["sistema"])
def health():
    with pool.connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True}


@app.get("/taxonomy", tags=["catálogo"], summary="Classes, tipos de sinal em português, cores (shared/taxonomia.json)")
def get_taxonomy():
    return tx.load()


@app.get("/config", tags=["sistema"], summary="Município, zona piloto, fontes com licenças e última importação")
def get_config():
    with pool.connection() as conn:
        m = conn.execute("""SELECT id, name, pilot_zone_name,
                                   ST_AsGeoJSON(area)::json AS area,
                                   ST_AsGeoJSON(ST_Centroid(area))::json AS center
                            FROM municipality ORDER BY id LIMIT 1""").fetchone()
        sources = conn.execute("SELECT key, name, license, attribution, url, enabled, requires_authorization FROM source ORDER BY id").fetchall()
        last = conn.execute("SELECT * FROM import_run ORDER BY id DESC LIMIT 1").fetchone()
        blur = conn.execute("SELECT count(*) AS n, count(*) FILTER (WHERE blur_audited) AS audited FROM image").fetchone()
    return {"municipality": m, "sources": sources, "last_import": last,
            "privacy": {"images": blur["n"], "images_blur_audited": blur["audited"]}}


@app.get("/imports", tags=["sistema"], summary="Histórico de importações da entrega")
def list_imports(t: dict = Depends(technician)):
    with pool.connection() as conn:
        return conn.execute("SELECT * FROM import_run ORDER BY id DESC").fetchall()


@app.get("/elements", tags=["catálogo"], summary="Elementos para o mapa e a lista (GeoJSON no formato da entrega)")
def list_elements(f: Filters = Depends(), limit: int = Query(20000, le=50000), t: Optional[dict] = Depends(viewer)):
    public_only(f, t)
    rows = fetch_elements(f, limit=limit)
    feats = [feature(r) for r in rows]
    if t is None:  # o público não vê quem validou
        for ft in feats:
            ft["properties"]["updated_by"] = None
    return {"type": "FeatureCollection", "total": len(feats), "features": feats}


def observations_detail(conn, element_id: int, best_id: Optional[int]) -> list[dict]:
    rows = conn.execute("""
        SELECT d.ext_id AS detection_id, d.class, d.subtype, d.score, d.quality, d.rank, d.bbox,
               d.azimuth, d.est_distance, d.crop_path, d.extra,
               i.ext_id AS image_id, i.captured_at, i.heading, i.hfov_deg, i.width, i.height, i.blur_audited,
               ST_Y(i.cam) AS cam_lat, ST_X(i.cam) AS cam_lon, i.image_path,
               s.key AS source_key, s.name AS source_name, s.license, s.attribution, (d.id = %s) AS is_best
        FROM detection d
        JOIN image i ON i.id = d.image_id
        JOIN source s ON s.id = i.source_id
        WHERE d.element_id = %s
        ORDER BY d.rank NULLS LAST, d.score DESC""", [best_id, element_id]).fetchall()
    for r in rows:
        r["image_url"], r["crop_url"] = media_url(r.pop("image_path")), media_url(r.pop("crop_path"))
        r["captured_at"] = iso(r["captured_at"])
    return rows


def duplicate_info(conn, row: dict) -> Optional[dict]:
    gid = row["duplicate_group_id"]
    if not gid:
        return None
    g = conn.execute("SELECT * FROM duplicate_group WHERE id = %s", [gid]).fetchone()
    members = conn.execute("""
        SELECT e.ext_id AS id, e.name, e.status, e.n_views, e.confidence, mg.ext_id AS merged_into,
               (SELECT p.distance_m FROM duplicate_pair p
                 WHERE (p.element_a = e.ext_id AND p.element_b = %s) OR (p.element_b = e.ext_id AND p.element_a = %s)
                 LIMIT 1) AS distance_m,
               (SELECT p.shared_image FROM duplicate_pair p
                 WHERE (p.element_a = e.ext_id AND p.element_b = %s) OR (p.element_b = e.ext_id AND p.element_a = %s)
                 LIMIT 1) AS shared_image
        FROM element e LEFT JOIN element mg ON mg.id = e.merged_into
        WHERE e.duplicate_group_id = %s AND e.id <> %s ORDER BY e.ext_id""",
        [row["ext_id"]] * 4 + [gid, row["id"]]).fetchall()
    return {"id": gid, "suggested_keep": g["suggested_keep"], "max_distance_m": g["max_distance_m"],
            "resolved": g["resolved"], "others": members, "level": g.get("level"),
            "confidence": g.get("confidence"), "recommendation": g.get("recommendation")}


def history(conn, ext_id: str) -> list[dict]:
    rows = conn.execute("SELECT who, action, at, before, after FROM edit_log WHERE element_ext_id = %s ORDER BY at DESC, id DESC",
                        [ext_id]).fetchall()
    for r in rows:
        r["at"] = iso(r["at"])
    return rows


@app.get("/elements/{element_id}", tags=["catálogo"], summary="Detalhe: todas as observações com imagem, duplicados e histórico")
def get_element(element_id: str, t: Optional[dict] = Depends(viewer)):
    with pool.connection() as conn:
        row = fetch_one(conn, element_id)
        if t is None:
            if row["status"] not in VERIFIED:
                raise HTTPException(404, "Elemento não encontrado")
            return feature(row, {
                "observations_detail": observations_detail(conn, row["id"], row["best_detection_id"]),
                "duplicates": None, "children": [], "history": [], "updated_by": None,
            })
        return feature(row, {
            "observations_detail": observations_detail(conn, row["id"], row["best_detection_id"]),
            "duplicates": duplicate_info(conn, row),
            "children": conn.execute("SELECT ext_id AS id, name FROM element WHERE parent_id = %s AND status <> 'fundido' ORDER BY ext_id",
                                     [row["id"]]).fetchall(),
            "history": history(conn, row["ext_id"]),
        })


ACTION_LABELS = {"validar": "Validar", "corrigir": "Corrigir", "mover": "Mover", "rejeitar": "Rejeitar", "repor": "Repor",
                 "fundir": "Juntar duplicados", "separar": "Separar", "melhor_imagem": "Melhor imagem"}

HISTORY_SELECT = """
SELECT l.id, l.at, l.who, l.action, l.element_ext_id AS element_id, l.before, l.after,
       e.name AS element_name, e.family, e.status AS element_status
FROM edit_log l LEFT JOIN element e ON e.ext_id = l.element_ext_id
"""


def _history_filter(action: Optional[str], who: Optional[str]):
    clauses, params = [], []
    for col, val in (("l.action", action), ("l.who", who)):
        vals = [v.strip() for v in (val or "").split(",") if v.strip()]
        if vals:
            clauses.append(f"{col} = ANY(%s)")
            params.append(vals)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


@app.get("/history", tags=["correção"], summary="Histórico de todas as alterações dos técnicos (mais recentes primeiro)")
def list_history(action: Optional[str] = Query(None, description="validar, corrigir, mover, rejeitar, repor, fundir, separar, melhor_imagem"),
                 who: Optional[str] = None, limit: int = Query(1000, ge=1, le=20000), t: dict = Depends(technician)):
    where, params = _history_filter(action, who)
    with pool.connection() as conn:
        rows = conn.execute(f"{HISTORY_SELECT}{where} ORDER BY l.at DESC, l.id DESC LIMIT %s", params + [limit]).fetchall()
        counts = conn.execute("SELECT action, count(*) AS n FROM edit_log GROUP BY 1").fetchall()
        whos = conn.execute("SELECT who, count(*) AS n FROM edit_log GROUP BY 1 ORDER BY 2 DESC").fetchall()
    for r in rows:
        r["at"] = iso(r["at"])
        r["action_label"] = ACTION_LABELS.get(r["action"], r["action"])
    return {"total": sum(c["n"] for c in counts), "counts": {c["action"]: c["n"] for c in counts},
            "technicians": whos, "items": rows}


@app.get("/history/export.csv", tags=["correção"], summary="Histórico de alterações em CSV")
def export_history(sep: str = Query(";"), t: dict = Depends(technician)):
    if sep not in (",", ";", "\t"):
        raise HTTPException(400, "Separador inválido")
    with pool.connection() as conn:
        rows = conn.execute(f"{HISTORY_SELECT} ORDER BY l.at, l.id").fetchall()
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=sep)
    w.writerow(["data_hora", "tecnico", "acao", "elemento", "nome_elemento", "familia", "antes", "depois"])
    for r in rows:
        w.writerow([iso(r["at"]), r["who"], ACTION_LABELS.get(r["action"], r["action"]), r["element_id"], r["element_name"],
                    r["family"], json.dumps(r["before"], ensure_ascii=False), json.dumps(r["after"], ensure_ascii=False)])
    return Response("\ufeff" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="historico_ctrlf_{datetime.now():%Y%m%d_%H%M}.csv"'})


@app.get("/elements/{element_id}/history", tags=["correção"])
def get_history(element_id: str, t: dict = Depends(technician)):
    with pool.connection() as conn:
        el = acoes.find_element(conn, element_id)
        return history(conn, el["ext_id"])


DETECTION_SELECT = """
SELECT d.ext_id AS id, i.ext_id AS image_id, d.family, d.class, d.subtype, d.score, d.bbox, d.quality,
       d.azimuth, d.est_distance, e.ext_id AS element_id, d.in_catalog, d.excluded_reason, d.suggested_class,
       d.crop_path, d.extra, d.rank
FROM detection d JOIN image i ON i.id = d.image_id LEFT JOIN element e ON e.id = d.element_id
"""


def detection_out(r: dict) -> dict:
    r["crop_url"] = media_url(r["crop_path"])
    return r


@app.get("/detections", tags=["catálogo"], summary="Deteções (formato deteccoes.json), filtráveis")
def list_detections(element_id: Optional[str] = None, image_id: Optional[str] = None,
                    in_catalog: Optional[str] = None, excluded_reason: Optional[str] = None,
                    family: Optional[str] = None, limit: int = Query(5000, le=20000), offset: int = 0,
                    t: dict = Depends(technician)):
    clauses, params = [], []
    if element_id:
        clauses.append("e.ext_id = %s")
        params.append(element_id)
    if image_id:
        clauses.append("i.ext_id = %s")
        params.append(image_id)
    if bool_param(in_catalog) is not None:
        clauses.append("d.in_catalog = %s")
        params.append(bool_param(in_catalog))
    if excluded_reason:
        clauses.append("d.excluded_reason = ANY(%s)")
        params.append(csv_list(excluded_reason))
    if family:
        clauses.append("d.family = ANY(%s)")
        params.append(csv_list(family))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with pool.connection() as conn:
        rows = conn.execute(f"{DETECTION_SELECT}{where} ORDER BY d.ext_id LIMIT %s OFFSET %s", params + [limit, offset]).fetchall()
    return [detection_out(r) for r in rows]


@app.get("/detections/{detection_id}", tags=["catálogo"])
def get_detection(detection_id: str, t: dict = Depends(technician)):
    with pool.connection() as conn:
        r = conn.execute(f"{DETECTION_SELECT} WHERE d.ext_id = %s", [detection_id]).fetchone()
    if not r:
        raise HTTPException(404, "Deteção não encontrada")
    return detection_out(r)


@app.get("/images/{image_id}", tags=["catálogo"], summary="Imagem (formato imagens.json) e as deteções que tem")
def get_image(image_id: str, t: dict = Depends(technician)):
    with pool.connection() as conn:
        i = conn.execute("""
            SELECT i.ext_id AS id, s.key AS source, i.source_image_id, ST_Y(i.cam) AS lat, ST_X(i.cam) AS lon,
                   i.heading, i.hfov_deg, i.camera_type, i.captured_at, i.width, i.height, s.license, s.attribution,
                   i.image_path AS path, i.pano_id, i.yaw, i.blurred, i.blur_audited
            FROM image i JOIN source s ON s.id = i.source_id WHERE i.ext_id = %s""", [image_id]).fetchone()
        if not i:
            raise HTTPException(404, "Imagem não encontrada")
        dets = conn.execute(f"{DETECTION_SELECT} WHERE i.ext_id = %s ORDER BY d.ext_id", [image_id]).fetchall()
    i["url"] = media_url(i["path"])
    i["captured_at"] = iso(i["captured_at"])
    i["detections"] = [detection_out(d) for d in dets]
    return i


@app.get("/duplicates", tags=["correção"], summary="Grupos de possíveis duplicados (duplicados.json) com o estado de cada elemento")
def list_duplicates(resolved: Optional[str] = Query("false", description="false (por omissão), true ou todos"),
                    family: Optional[str] = None, t: dict = Depends(technician)):
    clauses, params = [], []
    if resolved != "todos" and bool_param(resolved) is not None:
        clauses.append("g.resolved = %s")
        params.append(bool_param(resolved))
    if family:
        clauses.append("g.family = ANY(%s)")
        params.append(csv_list(family))
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    with pool.connection() as conn:
        groups = conn.execute(f"""
            SELECT g.*, json_agg(json_build_object('id', e.ext_id, 'name', e.name, 'status', e.status,
                                                   'n_views', e.n_views, 'confidence', e.confidence,
                                                   'lat', ST_Y(e.geom), 'lon', ST_X(e.geom)) ORDER BY e.ext_id) AS members
            FROM duplicate_group g JOIN element e ON e.duplicate_group_id = g.id
            {where} GROUP BY g.id ORDER BY g.id""", params).fetchall()
        pairs = conn.execute("SELECT group_id, element_a AS a, element_b AS b, family, distance_m, same_class, shared_image "
                             "FROM duplicate_pair ORDER BY id").fetchall()
    ids = {g["id"] for g in groups}
    return {"groups": groups, "pairs": [p for p in pairs if p["group_id"] in ids]}


@app.get("/review-queue", tags=["correção"], summary="Por rever, da menor para a maior confiança")
def review_queue(f: Filters = Depends(), limit: int = Query(1000, le=5000), t: dict = Depends(technician)):
    f.status = ["auto"]
    rows = fetch_elements(f, order="v.confidence ASC NULLS FIRST, v.ext_id", limit=limit)
    return {"type": "FeatureCollection", "total": len(rows), "features": [feature(r) for r in rows]}


@app.get("/stats", tags=["catálogo"], summary="Contagens para o painel do catálogo")
def stats(t: dict = Depends(technician)):
    with pool.connection() as conn:
        act = [list(ACTIVE)]
        by_family = conn.execute("SELECT family, count(*) AS n FROM element WHERE status = ANY(%s) GROUP BY 1", act).fetchall()
        by_class = conn.execute("SELECT family, class, count(*) AS n FROM element WHERE status = ANY(%s) GROUP BY 1, 2 ORDER BY 1, 2", act).fetchall()
        by_group = conn.execute("SELECT sign_group, count(*) AS n FROM element WHERE status = ANY(%s) AND family = 'sinal' GROUP BY 1 ORDER BY 2 DESC", act).fetchall()
        by_status = conn.execute("SELECT status, count(*) AS n FROM element GROUP BY 1").fetchall()
        extra = conn.execute("""
            SELECT count(*) FILTER (WHERE position_reliable) AS reliable,
                   count(*) FILTER (WHERE family = 'residuos' AND install_type IS NULL) AS waste_unclassified
            FROM element WHERE status = ANY(%s)""", act).fetchone()
        dups = conn.execute("SELECT count(*) FILTER (WHERE NOT resolved) AS open, count(*) AS total FROM duplicate_group").fetchone()
    st = {r["status"]: r["n"] for r in by_status}
    total = sum(st.get(s, 0) for s in ACTIVE)
    verified = st.get("validado", 0) + st.get("corrigido", 0)
    return {
        "total": total,
        "by_family": {r["family"]: r["n"] for r in by_family},
        "by_class": by_class,
        "by_sign_group": {r["sign_group"]: r["n"] for r in by_group},
        "by_status": st,
        "pending_review": st.get("auto", 0),
        "verified_pct": round(100 * verified / total) if total else 0,
        "position_reliable": extra["reliable"],
        "waste_unclassified": extra["waste_unclassified"],
        "duplicate_groups_open": dups["open"],
        "duplicate_groups_total": dups["total"],
    }


@app.get("/me", tags=["correção"], summary="Técnico autenticado e o que fez hoje")
def me(t: dict = Depends(technician)):
    with pool.connection() as conn:
        counts = conn.execute("""
            SELECT count(*) FILTER (WHERE action = 'validar') AS validated_today,
                   count(*) FILTER (WHERE action NOT IN ('validar', 'repor')) AS corrected_today
            FROM edit_log WHERE who = %s AND at >= current_date""", [t["name"]]).fetchone()
    initials = "".join(p[0] for p in t["name"].split()[:2]).upper()
    return {**t, "initials": initials, **counts}


# ---------------------------------------------------------------- correção pelo técnico

class ElementPatch(BaseModel):
    class_: Optional[str] = Field(None, alias="class", description="sinal, poste_luz, candeeiro, contentor ou subterraneo (dentro da mesma família)")
    subclass: Optional[str] = Field(None, description="Tipo de sinal, ex.: regulatory_stop")
    install_type: Optional[str] = Field(None, description="Contentores: ilha ou indiferenciado")
    color: Optional[str] = Field(None, description="Ecopontos: verde, azul, amarelo, vermelho, cinzento, castanho")
    lat: Optional[float] = Field(None, ge=-90, le=90)
    lon: Optional[float] = Field(None, ge=-180, le=180)
    address: Optional[str] = None
    note: Optional[str] = None

    model_config = {"populate_by_name": True}


def run_action(fn, *args, **kwargs) -> dict:
    with pool.connection() as conn, conn.transaction():
        ext = fn(conn, *args, **kwargs)
        return feature(fetch_one(conn, ext))


@app.patch("/elements/{element_id}", tags=["correção"], summary="Corrigir tipo, cor ou posição (fica 'corrigido')")
def patch_element(element_id: str, body: ElementPatch, t: dict = Depends(technician)):
    changes = body.model_dump(exclude_unset=True, by_alias=True)
    note = changes.pop("note", None)
    if not changes:
        raise HTTPException(400, "Nada para alterar")
    return run_action(acoes.correct, element_id, t["name"], changes, note=note)


@app.post("/elements/{element_id}/validate", tags=["correção"], summary="Confirmar que a deteção está certa")
def validate(element_id: str, t: dict = Depends(technician)):
    return run_action(acoes.validate, element_id, t["name"])


@app.post("/elements/{element_id}/reject", tags=["correção"], summary="Rejeitar (sai do mapa e das exportações)")
def reject(element_id: str, t: dict = Depends(technician)):
    return run_action(acoes.reject, element_id, t["name"])


@app.post("/elements/{element_id}/restore", tags=["correção"], summary="Repor um elemento rejeitado")
def restore(element_id: str, t: dict = Depends(technician)):
    return run_action(acoes.restore, element_id, t["name"])


class BestBody(BaseModel):
    detection_id: str = Field(..., description="Deteção do próprio elemento, ex.: det-sn-00910")


@app.put("/elements/{element_id}/best-detection", tags=["correção"], summary="Escolher a imagem principal do elemento")
def set_best(element_id: str, body: BestBody, t: dict = Depends(technician)):
    return run_action(acoes.set_best, element_id, t["name"], body.detection_id)


class MergeBody(BaseModel):
    into: str = Field(..., description="Elemento que fica, ex.: ilu-aveiro-00012")


@app.post("/elements/{element_id}/merge", tags=["correção"], summary="Juntar este elemento a outro (as observações passam para o destino)")
def merge(element_id: str, body: MergeBody, t: dict = Depends(technician)):
    return run_action(acoes.merge, element_id, body.into, t["name"])


class SplitBody(BaseModel):
    detection_ids: list[str] = Field(..., min_length=1, description="Deteções que passam para um elemento novo")


@app.post("/elements/{element_id}/split", tags=["correção"], status_code=201,
          summary="Separar: as deteções indicadas formam um elemento novo (devolve o novo)")
def split(element_id: str, body: SplitBody, t: dict = Depends(technician)):
    return run_action(acoes.split, element_id, body.detection_ids, t["name"])


@app.get("/decisions", tags=["correção"], summary="Decisões do técnico no formato 'decisoes' do pipeline (para o pipeline reaprender)")
def export_decisions(since: Optional[datetime] = Query(None, description="Só as decisões a partir desta data/hora"),
                     t: dict = Depends(technician)):
    with pool.connection() as conn:
        rows = conn.execute("SELECT decision FROM edit_log WHERE %s::timestamptz IS NULL OR at >= %s ORDER BY at, id",
                            [since, since]).fetchall()
    return Response(json.dumps({"schema_version": "1.0", "decisions": [r["decision"] for r in rows]}, ensure_ascii=False, indent=1),
                    media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="decisoes_{datetime.now():%Y%m%d_%H%M}.json"'})


@app.post("/decisions", tags=["correção"], summary="Aplicar decisões no formato 'decisoes' (tudo ou nada)")
def import_decisions(payload: dict = Body(..., examples=[{"schema_version": "1.0", "decisions": [
        {"element_id": "ilu-aveiro-00015", "merge_into": "ilu-aveiro-00012",
         "decided_by": "Ana Teixeira", "decided_at": "2026-11-17T10:01:00Z"}]}]),
        t: dict = Depends(technician)):
    decisions = payload.get("decisions")
    if not isinstance(decisions, list):
        raise HTTPException(422, "Falta a lista 'decisions'")
    results = []
    with pool.connection() as conn, conn.transaction():
        for i, d in enumerate(decisions):
            d = {**d, "decided_by": d.get("decided_by") or t["name"]}
            try:
                results.append(acoes.apply_decision(conn, d))
            except acoes.AcaoErro as e:
                raise acoes.AcaoErro(e.status_code, f"Decisão {i} ({d.get('element_id')}): {e.message}")
    return {"applied": len(results), "elements": results}


# ---------------------------------------------------------------- exportação

EXPORT_COLUMNS = ["id", "familia", "classe", "tipo", "grupo", "codigo", "nome", "instalacao", "cor", "n_unidades",
                  "lat", "lon", "incerteza_m", "posicao_fiavel", "metodo_posicao", "confianca", "n_vistas", "estado",
                  "fonte", "licenca", "atribuicao", "morada", "detetado_em", "atualizado_por", "atualizado_em"]


def export_props(r: dict) -> dict:
    return {
        "id": r["ext_id"], "familia": r["family"], "classe": r["class"], "tipo": r["subclass"], "grupo": r["sign_group"],
        "codigo": r["code"], "nome": r["name"], "instalacao": r["install_type"], "cor": r["color"], "n_unidades": r["n_units"],
        "lat": round(r["lat"], 7), "lon": round(r["lon"], 7), "incerteza_m": uncertainty(r),
        "posicao_fiavel": r["position_reliable"], "metodo_posicao": r["geo_method"],
        "confianca": round(r["confidence"], 3) if r["confidence"] is not None else None,
        "n_vistas": r["n_views"], "estado": r["status"],
        "fonte": r["source_name"], "licenca": r["source_license"], "atribuicao": r["source_attribution"],
        "morada": r["address"], "detetado_em": iso(r["first_seen_at"]),
        "atualizado_por": r["updated_by"], "atualizado_em": iso(r["updated_at"]),
    }


def export_filename(ext: str) -> str:
    return f"catalogo_ctrlf_{datetime.now():%Y%m%d_%H%M}.{ext}"


@app.get("/export.geojson", tags=["exportação"], summary="Catálogo em GeoJSON (respeita os filtros)")
def export_geojson(f: Filters = Depends(), t: Optional[dict] = Depends(viewer)):
    public_only(f, t)
    rows = fetch_elements(f)
    with pool.connection() as conn:
        licenses = conn.execute("SELECT name, license, attribution FROM source WHERE enabled ORDER BY id").fetchall()
    data = {
        "type": "FeatureCollection",
        "name": "catalogo_mobiliario_urbano",
        "crs_note": "Coordenadas em WGS84 (EPSG:4326)",
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "sources": licenses,
        "features": [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(r["lon"], 7), round(r["lat"], 7)]},
                      "properties": export_props(r)} for r in rows],
    }
    return Response(json.dumps(data, ensure_ascii=False, indent=1), media_type="application/geo+json",
                    headers={"Content-Disposition": f'attachment; filename="{export_filename("geojson")}"'})


@app.get("/export.csv", tags=["exportação"], summary="Catálogo em CSV (respeita os filtros)")
def export_csv(f: Filters = Depends(), sep: str = Query(";", description="';' abre bem no Excel em português, ',' é o padrão"),
               t: Optional[dict] = Depends(viewer)):
    public_only(f, t)
    if sep not in (",", ";", "\t"):
        raise HTTPException(400, "Separador inválido")
    rows = fetch_elements(f)
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=EXPORT_COLUMNS, delimiter=sep)
    w.writeheader()
    for r in rows:
        w.writerow(export_props(r))
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{export_filename("csv")}"'})


# ---------------------------------------------------------------- processamentos

def job_out(j: dict) -> dict:
    return {k: iso(v) for k, v in j.items() if k not in ("input_path", "gpx_path")}


JOB_SELECT = """SELECT j.*, s.key AS source_key, s.name AS source_name
                FROM job j LEFT JOIN source s ON s.id = j.source_id"""


JOB_STATUSES = ("na_fila", "a_processar", "concluido", "erro")


@app.get("/jobs", tags=["processamento"], summary="Pedidos de processamento (o pipeline lê os 'na_fila')")
def list_jobs(limit: int = Query(50, le=500),
              status: Optional[str] = Query(None, description="na_fila, a_processar, concluido, erro (vírgulas)"),
              t: dict = Depends(technician)):
    vals = [v.strip() for v in (status or "").split(",") if v.strip()]
    if any(v not in JOB_STATUSES for v in vals):
        raise HTTPException(422, "Estado inválido")
    where, params = ("WHERE j.status = ANY(%s)", [vals]) if vals else ("", [])
    order = "ASC" if vals == ["na_fila"] else "DESC"   # a fila: o mais antigo primeiro
    with pool.connection() as conn:
        rows = conn.execute(f"{JOB_SELECT} {where} ORDER BY j.created_at {order} LIMIT %s", params + [limit]).fetchall()
    out = []
    for j in rows:
        o = job_out(j)
        if j.get("input_path"):   # o pipeline precisa do caminho do vídeo; a interface não o mostra
            o["input_file"] = os.path.relpath(j["input_path"], UPLOAD_DIR)
            o["gpx_file"] = os.path.relpath(j["gpx_path"], UPLOAD_DIR) if j.get("gpx_path") else None
        out.append(o)
    return out


class JobPatch(BaseModel):
    status: Optional[str] = Field(None, description="a_processar, concluido ou erro")
    progress: Optional[int] = Field(None, ge=0, le=100)
    n_images: Optional[int] = Field(None, ge=0)
    n_detections: Optional[int] = Field(None, ge=0)
    n_elements: Optional[int] = Field(None, ge=0)
    error: Optional[str] = Field(None, max_length=2000)
    etapa: Optional[str] = Field(None, max_length=200, description="Etapa do pipeline em curso, mostrada na interface")


@app.patch("/jobs/{job_id}", tags=["processamento"],
           summary="O pipeline atualiza o estado, o progresso e as contagens de um pedido")
def patch_job(job_id: int, body: JobPatch, t: dict = Depends(technician)):
    ch = body.model_dump(exclude_unset=True)
    if not ch:
        raise HTTPException(400, "Nada para alterar")
    if "status" in ch and ch["status"] not in JOB_STATUSES:
        raise HTTPException(422, "Estado inválido: use na_fila, a_processar, concluido ou erro")
    if ch.get("status") == "concluido":
        ch.setdefault("progress", 100)
    etapa = ch.pop("etapa", None)
    sets = [f"{k} = %s" for k in ch] + ["updated_at = now()"]
    vals = list(ch.values())
    if etapa is not None:
        sets.append("params = params || jsonb_build_object('etapa', %s::text)")
        vals.append(etapa)
    with pool.connection() as conn:
        r = conn.execute(f"UPDATE job SET {', '.join(sets)} WHERE id = %s RETURNING id", vals + [job_id]).fetchone()
        if not r:
            raise HTTPException(404, "Pedido não encontrado")
    return get_job(job_id, t)


@app.get("/jobs/{job_id}", tags=["processamento"])
def get_job(job_id: int, t: dict = Depends(technician)):
    with pool.connection() as conn:
        j = conn.execute(f"{JOB_SELECT} WHERE j.id = %s", [job_id]).fetchone()
    if not j:
        raise HTTPException(404, "Processamento não encontrado")
    return job_out(j)


@app.post("/jobs/video", tags=["processamento"], status_code=201, summary="Enviar vídeo (e GPX opcional) para processar")
def upload_video(video: UploadFile = File(...), gpx: Optional[UploadFile] = File(None),
                 name: Optional[str] = Form(None), t: dict = Depends(technician)):
    if not (video.content_type or "").startswith("video/"):
        raise HTTPException(415, "O ficheiro tem de ser um vídeo (MP4 ou MOV)")
    folder = os.path.join(UPLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(folder)
    vpath = os.path.join(folder, os.path.basename(video.filename or "video.mp4"))
    with open(vpath, "wb") as out:
        shutil.copyfileobj(video.file, out)
    gpath = None
    if gpx is not None and gpx.filename:
        gpath = os.path.join(folder, os.path.basename(gpx.filename))
        with open(gpath, "wb") as out:
            shutil.copyfileobj(gpx.file, out)
    with pool.connection() as conn:
        j = conn.execute("""INSERT INTO job (municipality_id, source_id, name, input_path, gpx_path, created_by)
                            VALUES (%s, (SELECT id FROM source WHERE key = 'video'), %s, %s, %s, %s) RETURNING id""",
                         [t["municipality_id"], name or video.filename, vpath, gpath, t["name"]]).fetchone()
    return get_job(j["id"], t)


class SourceJob(BaseModel):
    source: str = Field(..., description="mapillary, kartaview, panoramax ou streetview")
    name: str = Field(..., description="Rua ou bairro")
    bbox: Optional[list[float]] = Field(None, description="[minLon, minLat, maxLon, maxLat]; por omissão, a zona piloto")


@app.post("/jobs/source", tags=["processamento"], status_code=201, summary="Pedir a recolha de imagens de uma fonte aberta")
def source_job(body: SourceJob, t: dict = Depends(technician)):
    with pool.connection() as conn:
        s = conn.execute("SELECT id, name, enabled, requires_authorization FROM source WHERE key = %s", [body.source]).fetchone()
        if not s:
            raise HTTPException(404, "Fonte desconhecida")
        if not s["enabled"]:
            msg = " Requer autorização escrita para este uso (ver página de licenças)." if s["requires_authorization"] else ""
            raise HTTPException(403, f"A fonte {s['name']} está desligada.{msg}")
        params = {"bbox": body.bbox} if body.bbox else {}
        j = conn.execute("""INSERT INTO job (municipality_id, source_id, name, params, created_by)
                            VALUES (%s, %s, %s, %s, %s) RETURNING id""",
                         [t["municipality_id"], s["id"], body.name, json.dumps(params), t["name"]]).fetchone()
    return get_job(j["id"], t)


class JobImport(BaseModel):
    pasta: str = Field(..., description="Pasta da entrega, relativa à pasta de dados (ex.: entregas/pedido_12)")


@app.post("/jobs/{job_id}/importar", tags=["processamento"],
          summary="Junta ao catálogo a entrega produzida pelo pipeline para este pedido e dá-o como concluído")
def import_job(job_id: int, body: JobImport, t: dict = Depends(technician)):
    from . import importar
    folder = os.path.abspath(os.path.join(importar.MEDIA_DIR, body.pasta))
    if os.path.commonpath([folder, os.path.abspath(importar.MEDIA_DIR)]) != os.path.abspath(importar.MEDIA_DIR):
        raise HTTPException(400, "A pasta tem de estar dentro da pasta de dados")
    if not os.path.isfile(os.path.join(folder, "elementos.geojson")):
        raise HTTPException(404, f"Não há elementos.geojson em {body.pasta}")
    with pool.connection() as conn:
        if not conn.execute("SELECT 1 FROM job WHERE id = %s", [job_id]).fetchone():
            raise HTTPException(404, "Pedido não encontrado")
        conn.execute("UPDATE job SET params = params || '{\"etapa\": \"importar para a plataforma\"}', progress = 97, updated_at = now() WHERE id = %s", [job_id])
    try:
        counts = importar.run(folder, juntar=True, database_url=os.environ.get("DATABASE_URL", importar.DATABASE_URL))
    except (Exception, SystemExit) as e:   # noqa: BLE001  o pipeline vê o erro na resposta e no pedido
        with pool.connection() as conn:
            conn.execute("UPDATE job SET status = 'erro', error = %s, updated_at = now() WHERE id = %s", [f"Importação: {e}", job_id])
        raise HTTPException(422, f"A importação falhou: {e}")
    with pool.connection() as conn:
        conn.execute("""UPDATE job SET status = 'concluido', progress = 100, n_images = %s, n_detections = %s, n_elements = %s,
                        params = params || '{"etapa": "concluído"}', updated_at = now() WHERE id = %s""",
                     [counts["images"], counts["detections"], counts["elements"], job_id])
    return {**get_job(job_id, t), "import": counts}


# ---------------------------------------------------------------- reclamações dos cidadãos

reclamacoes.register(app, technician, viewer, lambda: UPLOAD_DIR)
