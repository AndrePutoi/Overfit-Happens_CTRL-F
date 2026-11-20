"""Importa uma entrega do pipeline (elementos.geojson, deteccoes.json, imagens.json, duplicados.json).

Uso, dentro do contentor da API:
    python -m app.importar                       # pasta por omissão: $MEDIA_DIR/entrega
    python -m app.importar /data/media/entrega   # outra pasta
    python -m app.importar --sem-decisoes        # não volta a aplicar as decisões do técnico

    python -m app.importar /data/media/entregas/pedido_12 --juntar   # soma ao catálogo (pedidos de novas imagens)

Por omissão, cada importação substitui os elementos, as deteções, as imagens e os duplicados pelo
conteúdo da entrega. Com --juntar, a entrega soma-se ao catálogo atual: os elementos, deteções e
grupos de duplicados cujo id já exista recebem o prefixo "<pasta>:"; as imagens já conhecidas são
reutilizadas; as decisões do técnico não são tocadas. O histórico do técnico (edit_log) fica e as decisões voltam a ser aplicadas aos
elementos com o mesmo id. As que já não encontram o elemento contam como ignoradas.

As imagens e os recortes não são copiados: a pasta da entrega tem de estar dentro de MEDIA_DIR
para a API os servir em /media.
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import psycopg
from psycopg.rows import dict_row

from . import acoes
from . import taxonomia as tx

MEDIA_DIR = os.environ.get("MEDIA_DIR", "/data/media")
DATABASE_URL = os.environ.get("DATABASE_URL", "postgresql://ctrlf:ctrlf@localhost:5432/ctrlf")
REQUIRED = ("elementos.geojson", "deteccoes.json", "imagens.json", "duplicados.json")
SCHEMAS = {"elementos.geojson": "elementos", "deteccoes.json": "deteccoes",
           "imagens.json": "imagens", "duplicados.json": "duplicados",
           "elementos_unicos.geojson": "elementos_unicos", "ilhas.json": "ilhas"}
# Opcionais (entrega v1.3): inventário único (fusões automáticas já aplicadas) e ilhas de reciclagem
OPTIONAL = ("elementos_unicos.geojson", "ilhas.json")


def log(msg: str):
    print(msg, flush=True)


def load_files(folder: str) -> dict:
    missing = [f for f in REQUIRED if not os.path.isfile(os.path.join(folder, f))]
    if missing:
        sys.exit(f"Faltam ficheiros em {folder}: {', '.join(missing)}")
    data = {}
    for f in REQUIRED:
        with open(os.path.join(folder, f), encoding="utf-8") as fh:
            data[f] = json.load(fh)
    for f in OPTIONAL:
        if os.path.isfile(os.path.join(folder, f)):
            with open(os.path.join(folder, f), encoding="utf-8") as fh:
                data[f] = json.load(fh)
    manifest = os.path.join(folder, "manifest.json")
    data["manifest"] = json.load(open(manifest, encoding="utf-8")) if os.path.isfile(manifest) else {}
    return data


def validate_schemas(folder: str, data: dict):
    try:
        import jsonschema
    except ImportError:
        log("  (jsonschema não instalado: validação saltada)")
        return
    for f, name in SCHEMAS.items():
        path = os.path.join(folder, "schema", f"{name}.schema.json")
        if f in data and os.path.isfile(path):
            jsonschema.validate(data[f], json.load(open(path, encoding="utf-8")))
    log("  esquemas JSON: válidos")


def media_prefix(folder: str) -> str | None:
    folder, media = os.path.abspath(folder), os.path.abspath(MEDIA_DIR)
    if os.path.commonpath([folder, media]) != media:
        return None
    rel = os.path.relpath(folder, media)
    return "" if rel == "." else rel.replace(os.sep, "/") + "/"


def _namespace(conn, data: dict, tag: str):
    """--juntar: dá um prefixo aos ids que já existem na base de dados (cada zona do pipeline numera de 1)."""
    els = data.get("elementos_unicos.geojson", data["elementos.geojson"])["features"]
    all_els = data["elementos.geojson"]["features"]
    el_ids = {f["properties"]["id"] for f in all_els + els}
    det_ids = {d["id"] for d in data["deteccoes.json"]}
    grp_ids = {g["id"] for g in data["duplicados.json"]["groups"]}
    taken_el = {r["ext_id"] for r in conn.execute("SELECT ext_id FROM element WHERE ext_id = ANY(%s)", [list(el_ids)]).fetchall()}
    taken_det = {r["ext_id"] for r in conn.execute("SELECT ext_id FROM detection WHERE ext_id = ANY(%s)", [list(det_ids)]).fetchall()}
    taken_grp = {r["id"] for r in conn.execute("SELECT id FROM duplicate_group WHERE id = ANY(%s)", [list(grp_ids)]).fetchall()}
    re = lambda x: f"{tag}:{x}" if x in taken_el else x      # noqa: E731
    rd = lambda x: f"{tag}:{x}" if x in taken_det else x     # noqa: E731
    rg = lambda x: f"{tag}:{x}" if x in taken_grp else x     # noqa: E731
    for coll in {id(all_els): all_els, id(els): els}.values():
        for f in coll:
            p = f["properties"]
            p["id"] = re(p["id"])
            if p.get("best_detection_id"):
                p["best_detection_id"] = rd(p["best_detection_id"])
            if p.get("duplicate_group_id"):
                p["duplicate_group_id"] = rg(p["duplicate_group_id"])
            if p.get("merged_from"):
                p["merged_from"] = [re(m) for m in p["merged_from"]]
            for o in p.get("observations") or []:
                o["detection_id"] = rd(o["detection_id"])
    for d in data["deteccoes.json"]:
        d["id"] = rd(d["id"])
        if d.get("element_id"):
            d["element_id"] = re(d["element_id"])
    for g in data["duplicados.json"]["groups"]:
        g["id"] = rg(g["id"])
        g["members"] = [re(m) for m in g["members"]]
        if g.get("suggested_keep"):
            g["suggested_keep"] = re(g["suggested_keep"])
    for pr in data["duplicados.json"]["pairs"]:
        pr["a"], pr["b"] = re(pr["a"]), re(pr["b"])
    for i in data.get("ilhas.json", []):
        i["element_id"] = re(i["element_id"])
    n = len(taken_el) + len(taken_det) + len(taken_grp)
    if n:
        log(f"  ids repetidos com prefixo '{tag}:': {len(taken_el)} elementos, {len(taken_det)} deteções, {len(taken_grp)} grupos")


def run(folder: str, reapply: bool = True, database_url: str = DATABASE_URL, juntar: bool = False) -> dict:
    log(f"A importar {folder}" + (" (a juntar ao catálogo atual)" if juntar else ""))
    data = load_files(folder)
    if juntar:
        reapply = False
        with psycopg.connect(database_url, row_factory=dict_row) as c0:
            _namespace(c0, data, os.path.basename(os.path.normpath(folder)))
    validate_schemas(folder, data)
    prefix = media_prefix(folder)
    if prefix is None:
        log(f"  AVISO: {folder} não está dentro de {MEDIA_DIR}; as imagens e os recortes não ficam disponíveis em /media")

    # v1.3: o inventário único já traz as fusões automáticas (os absorvidos ficam de fora; merged_from guarda-os)
    if "elementos_unicos.geojson" in data:
        elements = data["elementos_unicos.geojson"]["features"]
        log(f"  a usar elementos_unicos.geojson (inventário único): {len(elements)} elementos "
            f"de {len(data['elementos.geojson']['features'])}")
    else:
        elements = data["elementos.geojson"]["features"]
    dups = data["duplicados.json"]
    ilhas = {i["element_id"]: i for i in data.get("ilhas.json", [])}
    present = {f["properties"]["id"] for f in elements}
    # grupos de duplicados: só os que ainda têm pelo menos dois elementos no inventário
    for g in dups["groups"]:
        g["members"] = [m for m in g["members"] if m in present]
    kept_groups = {g["id"]: g for g in dups["groups"] if len(g["members"]) >= 2}
    detections = data["deteccoes.json"]
    images = data["imagens.json"]
    dups = data["duplicados.json"]
    manifest = data["manifest"]

    def path_or_none(rel):
        if prefix is None or not rel:
            return None
        return prefix + rel

    missing_imgs = sum(1 for i in images if i.get("path") and not os.path.isfile(os.path.join(folder, i["path"])))
    if missing_imgs:
        log(f"  AVISO: {missing_imgs} imagens referidas em imagens.json não estão na pasta")

    with psycopg.connect(database_url, row_factory=dict_row) as conn:
        from .reclamacoes import migrate_conn
        migrate_conn(conn)   # colunas novas (v1.3) numa base de dados antiga
        with conn.transaction():
            if not juntar:
                conn.execute("TRUNCATE duplicate_pair, detection, element, duplicate_group, image RESTART IDENTITY CASCADE")

            # fontes
            sources = {r["key"]: r["id"] for r in conn.execute("SELECT id, key FROM source").fetchall()}
            for img in images:
                if img["source"] not in sources:
                    r = conn.execute("""INSERT INTO source (key, name, license, attribution) VALUES (%s, %s, %s, %s)
                                        RETURNING id""", [img["source"], img["source"], img["license"], img["attribution"]]).fetchone()
                    sources[img["source"]] = r["id"]

            # imagens (desfocadas pelo pipeline; auditoria ainda por fazer)
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO image (ext_id, source_id, source_image_id, pano_id, yaw, captured_at, cam, heading,
                                       hfov_deg, camera_type, width, height, blurred, blur_audited, image_path)
                    VALUES (%s, %s, %s, %s, %s, %s, ST_SetSRID(ST_MakePoint(%s, %s), 4326), %s, %s, %s, %s, %s, true, false, %s)
                    ON CONFLICT (ext_id) DO NOTHING""",
                    [(i["id"], sources[i["source"]], i.get("source_image_id"), i.get("pano_id"), i.get("yaw"),
                      i.get("captured_at"), i["lon"], i["lat"], i["heading"], i.get("hfov_deg"), i.get("camera_type"),
                      i["width"], i["height"], path_or_none(i.get("path"))) for i in images])
            image_ids = {r["ext_id"]: r["id"] for r in conn.execute(
                "SELECT id, ext_id FROM image WHERE ext_id = ANY(%s)", [[i["id"] for i in images]]).fetchall()}

            # grupos de duplicados
            with conn.cursor() as cur:
                cur.executemany("INSERT INTO duplicate_group (id, family, suggested_keep, max_distance_m) VALUES (%s, %s, %s, %s)",
                                [(g["id"], g["family"], g["suggested_keep"] if g["suggested_keep"] in present else g["members"][0],
                                  g.get("max_distance_m")) for g in kept_groups.values()])
                cur.executemany("UPDATE duplicate_group SET level = %s, confidence = %s, recommendation = %s WHERE id = %s",
                                [(g.get("level"), g.get("confidence"), g.get("recommendation"), g["id"]) for g in kept_groups.values()])

            # elementos
            det_by_ext = {d["id"]: d for d in detections}
            unknown_types = set()
            rows = []
            for f in elements:
                p = f["properties"]
                lon, lat = f["geometry"]["coordinates"]
                best = det_by_ext.get(p["best_detection_id"], {})
                install = "subterraneo" if p["class"] == "subterraneo" else p.get("install_type")
                ilha = ilhas.get(p["id"])
                if ilha and p["class"] == "contentor" and not install and (ilha.get("n_unidades") or 0) >= 2:
                    install = "ilha"   # vários caixotes juntos; o tipo de cada um fica como sugestão (ilha.composicao_estimada)
                if p["family"] == "sinal" and p.get("subclass") and not tx.sign_type(p["subclass"]):
                    unknown_types.add(p["subclass"])
                desc = tx.describe(p["family"], p["class"], p.get("subclass"), install, p.get("color"), best.get("class"))
                po = p.get("position_original") or {}
                # resíduos (entrega 1.3+): subclass é o tipo SUGERIDO pelo modelo; guarda-se à parte, como sugestão
                fluxo = p.get("subclass") if p["family"] == "residuos" else None
                rows.append((p["id"], p["family"], p["class"], None if p["family"] == "residuos" else p.get("subclass"),
                             desc["sign_group"], desc["code"],
                             desc["name"], install, p.get("color"), p.get("n_units"), lon, lat,
                             po.get("lon"), po.get("lat"), p.get("geo_method"), p.get("geo_residual"),
                             bool(p.get("position_reliable")), p.get("road_adjustment_m"), p.get("road_adjustment_method"),
                             p.get("osm_ref_match"), p.get("confidence"), p.get("n_views", 1),
                             p.get("duplicate_group_id") if p.get("duplicate_group_id") in kept_groups else None,
                             "auto" if p.get("status") in (None, "auto") else p["status"],
                             p.get("position_method"), p.get("position_sigma_m"), p.get("clip_suspect"),
                             bool(p.get("auto_merged")), p.get("merged_from") or None,
                             p.get("duplicate_level") if p.get("duplicate_group_id") in kept_groups else None,
                             json.dumps({k: ilha.get(k) for k in ("id", "n_unidades", "composicao_estimada", "confianca_tipo_media",
                                                                  "radius_m", "tipo_revisto_pelo_tecnico", "n_imagens")})
                             if ilha else None, fluxo, p.get("subclass_p") if fluxo else None))
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO element (ext_id, municipality_id, family, class, subclass, sign_group, code, name,
                                         install_type, color, n_units, geom, position_original, geo_method, geo_residual,
                                         position_reliable, road_adjustment_m, road_adjustment_method, osm_ref_match,
                                         confidence, n_views, duplicate_group_id, status, position_method,
                                         position_sigma_m, clip_suspect, auto_merged, merged_from, duplicate_level, ilha,
                                         fluxo_sugerido, fluxo_p)
                    VALUES (%s, 1, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                            CASE WHEN %s::float8 IS NULL THEN NULL ELSE ST_SetSRID(ST_MakePoint(%s::float8, %s::float8), 4326) END,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    [r[:12] + (r[12], r[12], r[13]) + r[14:] for r in rows])
            element_ids = {r["ext_id"]: r["id"] for r in conn.execute(
                "SELECT id, ext_id FROM element WHERE ext_id = ANY(%s)", [[f["properties"]["id"] for f in elements]]).fetchall()}

            # deteções (todas, incluindo as que ficaram fora do catálogo)
            rank = {o["detection_id"]: o["rank"] for f in elements for o in f["properties"]["observations"]}
            # a que elemento pertence cada deteção: pelas observações (no inventário único, as dos absorvidos
            # passaram para o elemento que ficou); senão pelo element_id da deteção
            obs_owner = {o["detection_id"]: f["properties"]["id"] for f in elements for o in f["properties"]["observations"]}
            skipped_det = 0
            det_rows = []
            for d in detections:
                if d["image_id"] not in image_ids:
                    skipped_det += 1
                    continue
                det_rows.append((d["id"], image_ids[d["image_id"]], element_ids.get(obs_owner.get(d["id"], d.get("element_id"))), d["family"],
                                 d["class"], d.get("subtype"), d["score"], d.get("quality"), rank.get(d["id"]),
                                 d["bbox"], d.get("azimuth"), d.get("est_distance"), d["in_catalog"],
                                 d.get("excluded_reason"), d.get("suggested_class"), path_or_none(d.get("crop_path")),
                                 json.dumps(d.get("extra") or {})))
            with conn.cursor() as cur:
                cur.executemany("""
                    INSERT INTO detection (ext_id, image_id, element_id, family, class, subtype, score, quality, rank, bbox,
                                           azimuth, est_distance, in_catalog, excluded_reason, suggested_class, crop_path, extra)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""", det_rows)
            if skipped_det:
                log(f"  AVISO: {skipped_det} deteções apontam para imagens que não existem em imagens.json")

            with conn.cursor() as cur:
                cur.executemany("""UPDATE element e SET best_detection_id = d.id
                                   FROM detection d WHERE d.ext_id = %s AND e.ext_id = %s""",
                                [(f["properties"]["best_detection_id"], f["properties"]["id"]) for f in elements])
            conn.execute("""
                UPDATE element e SET first_seen_at = s.t
                FROM (SELECT d.element_id, min(i.captured_at) AS t
                      FROM detection d JOIN image i ON i.id = d.image_id
                      WHERE d.element_id IS NOT NULL GROUP BY d.element_id) s
                WHERE e.id = s.element_id""")

            # pares de duplicados
            group_of = {m: g["id"] for g in kept_groups.values() for m in g["members"]}
            with conn.cursor() as cur:
                cur.executemany("""INSERT INTO duplicate_pair (group_id, element_a, element_b, family, distance_m, same_class, shared_image)
                                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                                [(group_of.get(p["a"]) if group_of.get(p["a"]) == group_of.get(p["b"]) else None,
                                  p["a"], p["b"], p.get("family"), p["distance_m"], p.get("same_class"), p["shared_image"])
                                 for p in dups["pairs"]])

            # voltar a aplicar as decisões do técnico
            applied = skipped = 0
            reasons = defaultdict(int)
            if reapply:
                for row in conn.execute("SELECT decision FROM edit_log ORDER BY at, id").fetchall():
                    try:
                        with conn.transaction():
                            acoes.apply_decision(conn, row["decision"], record=False)
                        applied += 1
                    except acoes.AcaoErro as e:
                        skipped += 1
                        reasons[e.message.split(":")[0]] += 1

            counts = {"elements": len(elements), "detections": len(det_rows), "images": len(images),
                      "duplicate_groups": len(kept_groups), "duplicate_pairs": len(dups["pairs"])}
            conn.execute("""INSERT INTO import_run (schema_version, pipeline_commit, generated_at, folder, counts,
                                                    decisions_applied, decisions_skipped)
                            VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                         [manifest.get("schema_version"), manifest.get("commit"), manifest.get("generated_at"),
                          folder, json.dumps(counts), applied, skipped])

    log(f"  elementos: {counts['elements']} · deteções: {counts['detections']} · imagens: {counts['images']} · "
        f"grupos de duplicados: {counts['duplicate_groups']}")
    if unknown_types:
        log(f"  AVISO: tipos de sinal sem nome em português (acrescentar a shared/taxonomia.json): {', '.join(sorted(unknown_types))}")
    if reapply:
        log(f"  decisões do técnico reaplicadas: {applied} · ignoradas: {skipped}"
            + (f" ({dict(reasons)})" if reasons else ""))
    log("Importação concluída.")
    return {**counts, "decisions_applied": applied, "decisions_skipped": skipped}


def main():
    ap = argparse.ArgumentParser(description="Importa uma entrega do pipeline para a base de dados")
    ap.add_argument("pasta", nargs="?", default=os.path.join(MEDIA_DIR, "entrega"))
    ap.add_argument("--sem-decisoes", action="store_true", help="não voltar a aplicar as decisões do técnico")
    ap.add_argument("--juntar", action="store_true", help="somar ao catálogo atual em vez de o substituir")
    args = ap.parse_args()
    if not os.path.isdir(args.pasta):
        sys.exit(f"Pasta não encontrada: {args.pasta}")
    run(args.pasta, reapply=not args.sem_decisoes, juntar=args.juntar)


if __name__ == "__main__":
    main()
