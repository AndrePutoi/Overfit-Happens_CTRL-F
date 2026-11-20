"""Testes da API sobre a amostra da entrega (tests/fixture/entrega, 10 elementos).

A ordem importa: os primeiros testes leem, os seguintes alteram dados e o último reimporta.
"""
import json

AUTH = {"X-Tecnico-Token": "demo-ana"}
PUBLIC = {"X-Tecnico-Token": ""}


def ids(fc):
    return {f["id"] for f in fc["features"]}


def props(c, ref):
    return c.get(f"/elements/{ref}").json()["properties"]


# ------------------------------------------------------------ leitura

def test_health_config(client):
    assert client.get("/health").json() == {"ok": True}
    cfg = client.get("/config").json()
    assert cfg["last_import"]["counts"]["elements"] == 10
    assert cfg["privacy"]["images_blur_audited"] == 0


def test_elements_keep_pipeline_format(client):
    fc = client.get("/elements").json()
    assert fc["total"] == 10
    p = next(f for f in fc["features"] if f["id"] == "sin-aveiro-00160")["properties"]
    # campos obrigatórios de elementos.schema.json
    for k in ("id", "family", "class", "confidence", "n_views", "status", "geo_method", "position_reliable",
              "position_original", "observations", "best_detection_id", "duplicate_group_id"):
        assert k in p
    assert p["subclass"] == "regulatory_stop" and p["code"] == "B2" and p["sign_group"] == "prioridade"
    assert p["position_reliable"] is True and p["uncertainty_m"] >= 3
    assert p["observations"][0]["rank"] == 1
    assert p["best"]["crop_url"].startswith("/media/entrega/recortes/")


def test_filters(client):
    assert ids(client.get("/elements", params={"sign_group": "prioridade"}).json()) == {"sin-aveiro-00160", "sin-aveiro-00113"}
    assert client.get("/elements", params={"reliable": "true"}).json()["total"] == 1
    assert ids(client.get("/elements", params={"install_type": "por_classificar"}).json()) == {"res-aveiro-00001"}
    assert ids(client.get("/elements", params={"duplicates": "true"}).json()) == {"ilu-aveiro-00012", "ilu-aveiro-00015"}
    assert client.get("/elements", params={"q": "stop"}).json()["total"] == 1
    assert ids(client.get("/elements", params={"kind": "stop,cedencia"}).json()) == {"sin-aveiro-00160", "sin-aveiro-00113"}
    assert ids(client.get("/elements", params={"kind": "subterraneo"}).json()) == {"res-aveiro-00007"}
    assert ids(client.get("/elements", params={"kind": "subterraneo", "subclass": "regulatory_stop"}).json()) == {"res-aveiro-00007", "sin-aveiro-00160"}
    assert client.get("/elements", params={"bbox": "x"}).status_code == 400


def test_unknown_sign_named_by_group(client):
    p = props(client, "sin-aveiro-00002")
    assert p["subclass"] == "desconhecido" and p["name"].startswith("Sinal não identificado")


def test_detail_detections_images(client):
    p = props(client, "ilu-aveiro-00012")
    assert p["duplicates"]["others"][0]["id"] == "ilu-aveiro-00015"
    assert len(p["observations_detail"]) == 2 and p["observations_detail"][0]["is_best"]
    dets = client.get("/detections", params={"element_id": "ilu-aveiro-00012"}).json()
    assert {d["id"] for d in dets} == {"det-lz-00062", "det-lz-00063"}
    out = client.get("/detections", params={"excluded_reason": "papeleira_filter"}).json()
    assert out[0]["suggested_class"] == "papeleira" and out[0]["element_id"] is None
    img = client.get(f"/images/{dets[0]['image_id']}").json()
    assert img["license"] == "CC BY-SA 4.0" and img["blurred"] and not img["blur_audited"]
    assert client.get("/images/nao-existe").status_code == 404


def test_duplicates_and_queue(client):
    d = client.get("/duplicates").json()
    assert d["groups"][0]["id"] == "dup-lz-0001" and len(d["groups"][0]["members"]) == 2
    q = client.get("/review-queue").json()
    confs = [f["properties"]["confidence"] for f in q["features"]]
    assert confs == sorted(confs)


# ------------------------------------------------------------ correção

def test_auth_required(client):
    assert client.post("/elements/sin-aveiro-00001/validate", headers=PUBLIC).status_code == 401
    for path in ("/review-queue", "/stats", "/decisions", "/jobs", "/imports", "/detections", "/duplicates"):
        assert client.get(path, headers=PUBLIC).status_code == 401, path
    assert client.get("/elements", headers={"X-Tecnico-Token": "errado"}).status_code == 401


def test_correct_sign_and_waste(client):
    r = client.patch("/elements/sin-aveiro-00001", headers=AUTH, json={"subclass": "regulatory_yield"}).json()["properties"]
    assert r["name"] == "Cedência de passagem" and r["code"] == "B1" and r["status"] == "corrigido"
    r = client.patch("/elements/res-aveiro-00001", headers=AUTH, json={"install_type": "ilha", "color": "azul"}).json()["properties"]
    assert r["install_label"] == "Ilha de reciclagem" and "azul" in r["name"]
    assert client.patch("/elements/res-aveiro-00001", headers=AUTH, json={"install_type": "subterraneo"}).status_code == 422
    assert client.patch("/elements/sin-aveiro-00001", headers=AUTH, json={"subclass": "nao_existe"}).status_code == 422
    r = client.patch("/elements/ilu-aveiro-00002", headers=AUTH, json={"class": "poste_luz"}).json()["properties"]
    assert r["class"] == "poste_luz" and r["name"] == "Poste de iluminação"


def test_move_makes_position_manual(client):
    r = client.patch("/elements/ilu-aveiro-00001", headers=AUTH, json={"lat": 40.64169, "lon": -8.65347}).json()["properties"]
    assert r["geo_method"] == "manual" and r["position_reliable"] is True
    assert client.get("/elements/ilu-aveiro-00001/history").json()[0]["action"] == "mover"


def test_status_actions(client):
    assert client.post("/elements/sin-aveiro-00113/validate", headers=AUTH).json()["properties"]["status"] == "validado"
    assert client.post("/elements/sin-aveiro-00002/reject", headers=AUTH).json()["properties"]["status"] == "rejeitado"
    assert "sin-aveiro-00002" not in ids(client.get("/elements").json())
    assert client.post("/elements/sin-aveiro-00002/restore", headers=AUTH).json()["properties"]["status"] == "auto"
    assert client.post("/elements/sin-aveiro-00002/reject", headers=AUTH).status_code == 200


def test_best_detection(client):
    r = client.put("/elements/sin-aveiro-00160/best-detection", headers=AUTH, json={"detection_id": "det-sn-00055"})
    assert r.json()["properties"]["best_detection_id"] == "det-sn-00055"
    bad = client.put("/elements/sin-aveiro-00160/best-detection", headers=AUTH, json={"detection_id": "det-lz-00062"})
    assert bad.status_code == 422


def test_merge_and_split(client):
    r = client.post("/elements/ilu-aveiro-00015/merge", headers=AUTH, json={"into": "ilu-aveiro-00012"}).json()["properties"]
    assert r["id"] == "ilu-aveiro-00012" and len(r["observations"]) == 3
    assert props(client, "ilu-aveiro-00015")["merged_into"] == "ilu-aveiro-00012"
    assert client.get("/duplicates").json()["groups"] == []  # grupo resolvido
    assert client.post("/elements/res-aveiro-00007/merge", headers=AUTH, json={"into": "ilu-aveiro-00012"}).status_code == 422

    new = client.post("/elements/ilu-aveiro-00012/split", headers=AUTH, json={"detection_ids": ["det-lz-00062"]})
    assert new.status_code == 201
    n = new.json()["properties"]
    assert n["id"] == "ilu-aveiro-00012-s1" and n["split_from"] == "ilu-aveiro-00012" and n["n_views"] == 1
    assert len(props(client, "ilu-aveiro-00012")["observations"]) == 2
    one = props(client, "ilu-aveiro-00012-s1")["observations"][0]["detection_id"]
    assert client.post("/elements/ilu-aveiro-00012-s1/split", headers=AUTH, json={"detection_ids": [one]}).status_code == 422


def test_decisions_roundtrip(client):
    data = json.loads(client.get("/decisions").text)
    assert data["schema_version"] == "1.0"
    kinds = {k for d in data["decisions"] for k in d}
    assert {"merge_into", "split_detection_ids", "best_detection_id", "status", "decided_by", "decided_at"} <= kinds
    r = client.post("/decisions", headers=AUTH, json={"schema_version": "1.0", "decisions": [
        {"element_id": "res-aveiro-00007", "status": "validado", "decided_by": "Ana Teixeira", "decided_at": "2026-11-17T10:00:00Z"}]})
    assert r.json()["applied"] == 1 and props(client, "res-aveiro-00007")["status"] == "validado"
    bad = client.post("/decisions", headers=AUTH, json={"decisions": [{"element_id": "nao-existe", "status": "validado"}]})
    assert bad.status_code == 404


def test_public_profile_sees_only_verified(client):
    pub = client.get("/elements", headers=PUBLIC).json()
    assert pub["total"] > 0
    assert {f["properties"]["status"] for f in pub["features"]} <= {"validado", "corrigido"}
    assert client.get("/elements", headers=PUBLIC, params={"status": "por_rever"}).json()["total"] == 0
    assert client.get("/elements/sin-aveiro-00160", headers=PUBLIC).status_code == 404  # por rever
    ok = client.get("/elements/sin-aveiro-00001", headers=PUBLIC).json()["properties"]  # corrigido
    assert ok["history"] == [] and ok["duplicates"] is None and ok["observations_detail"]
    csv_ = client.get("/export.csv", headers=PUBLIC).text.lstrip("\ufeff").splitlines()
    assert len(csv_) - 1 == pub["total"]


def test_stats_me_exports(client):
    s = client.get("/stats").json()
    assert s["by_status"]["fundido"] == 1 and s["waste_unclassified"] == 0
    me = client.get("/me", headers=AUTH).json()
    assert me["initials"] == "AT" and me["validated_today"] >= 1
    g = json.loads(client.get("/export.geojson", params={"family": "residuos"}).text)
    assert {f["properties"]["familia"] for f in g["features"]} == {"residuos"}
    csv_ = client.get("/export.csv").text.lstrip("﻿").splitlines()
    assert csv_[0].startswith("id;familia;classe;tipo")
    assert len(csv_) == 1 + 9  # 10 + 1 separado - 1 fundido - 1 rejeitado


def test_jobs(client):
    assert client.post("/jobs/source", headers=AUTH, json={"source": "streetview", "name": "x"}).status_code == 403
    assert client.post("/jobs/source", headers=AUTH, json={"source": "mapillary", "name": "Av."}).status_code == 201


# ------------------------------------------------------------ reimportação

def test_reimport_keeps_decisions(client):
    from app import importar
    from tests.conftest import TEST_URL
    res = importar.run(str(client.media_dir / "entrega"), database_url=TEST_URL)
    assert res["decisions_skipped"] == 0 and res["decisions_applied"] > 5
    assert props(client, "sin-aveiro-00001")["name"] == "Cedência de passagem"
    assert props(client, "ilu-aveiro-00015")["status"] == "fundido"
    assert props(client, "ilu-aveiro-00012-s1")["n_views"] == 1
    assert props(client, "sin-aveiro-00002")["status"] == "rejeitado"
    assert props(client, "sin-aveiro-00160")["best_detection_id"] == "det-sn-00055"
