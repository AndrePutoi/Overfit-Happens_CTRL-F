"""Testes das reclamações dos cidadãos (corre depois de test_api.py, sobre a mesma base de teste)."""
import json

AUTH = {"X-Tecnico-Token": "demo-ana"}
PUBLIC = {"X-Tecnico-Token": ""}
PNG = (b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89"
       b"\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82")


def el(c, ref):
    return c.get(f"/elements/{ref}", headers=AUTH).json()["properties"]


def verify(c, ref):
    if el(c, ref)["status"] not in ("validado", "corrigido"):
        assert c.post(f"/elements/{ref}/validate", headers=AUTH).status_code == 200


def test_migracao_pode_correr_varias_vezes(client):
    from app import reclamacoes
    reclamacoes.migrate()
    reclamacoes.migrate()


def test_publico_so_reclama_de_elementos_verificados(client):
    client.post("/elements/sin-aveiro-00113/restore", headers=AUTH)   # pode estar validado de testes anteriores
    r = client.post("/complaints", headers=PUBLIC, data={"element_id": "res-aveiro-00007", "kind": "estado", "condition": "sujo"})
    if el(client, "res-aveiro-00007")["status"] == "auto":
        assert r.status_code == 404
    verify(client, "res-aveiro-00007")
    r = client.post("/complaints", headers=PUBLIC,
                    data={"element_id": "res-aveiro-00007", "kind": "estado", "condition": "vandalizado", "message": "Tampa partida"},
                    files={"photo": ("foto.png", PNG, "image/png")})
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["status"] == "por_resolver" and c["has_photo"] and c["condition_label"] == "Vandalizado"
    assert "message" not in c                 # o público não vê a mensagem
    tech = client.get("/complaints", headers=AUTH, params={"ids": str(c["id"])}).json()["items"][0]
    assert tech["message"] == "Tampa partida"
    # a foto só o técnico a vê
    assert client.get(f"/complaints/{c['id']}/photo", headers=PUBLIC).status_code == 401
    ph = client.get(f"/complaints/{c['id']}/photo", headers=AUTH)
    assert ph.status_code == 200 and ph.content == PNG


def test_validacoes(client):
    verify(client, "sin-aveiro-00160")
    base = {"element_id": "sin-aveiro-00160"}
    bad = [
        {**base, "kind": "inventado"},
        {**base, "kind": "estado"},                                              # falta o estado
        {**base, "kind": "estado", "condition": "lindo"},
        {**base, "kind": "posicao"},                                             # falta o ponto
        {**base, "kind": "posicao", "lat": "40.70", "lon": "-8.60"},             # a vários km
        {**base, "kind": "tipo", "suggested": json.dumps({"subclass": "regulatory_stop"})},   # igual ao atual
        {**base, "kind": "tipo", "suggested": json.dumps({"subclass": "nao_existe"})},
        {**base, "kind": "duplicado"},
        {**base, "kind": "duplicado", "duplicate_of": "sin-aveiro-00160"},       # ele próprio
    ]
    for data in bad:
        assert client.post("/complaints", headers=PUBLIC, data=data).status_code == 422, data
    assert client.post("/complaints", headers=PUBLIC, data={**base, "kind": "estado", "condition": "sujo"},
                       files={"photo": ("x.txt", b"ola", "text/plain")}).status_code == 415


def test_posicao_tipo_e_duplicado(client):
    p = el(client, "sin-aveiro-00160")
    r = client.post("/complaints", headers=PUBLIC, data={"element_id": "sin-aveiro-00160", "kind": "posicao",
                                                         "lat": p["lat"] + 0.0001, "lon": p["lon"]})
    assert r.status_code == 201, r.text
    assert 9 < r.json()["suggested_distance_m"] < 13

    r = client.post("/complaints", headers=PUBLIC, data={"element_id": "sin-aveiro-00160", "kind": "tipo",
                                                         "suggested": json.dumps({"subclass": "regulatory_yield"})})
    assert r.status_code == 201, r.text
    assert r.json()["suggested"] == {"class": "sinal", "subclass": "regulatory_yield"}
    assert r.json()["suggested_label"]

    verify(client, "sin-aveiro-00001")
    r = client.post("/complaints", headers=PUBLIC, data={"element_id": "sin-aveiro-00160", "kind": "duplicado",
                                                         "duplicate_of": "sin-aveiro-00001"})
    assert r.status_code == 201, r.text
    assert r.json()["duplicate_of"] == "sin-aveiro-00001"


def test_tecnico_muda_estado_e_responde(client):
    lst = client.get("/complaints", headers=AUTH).json()
    cid = lst["items"][0]["id"]
    before = lst["counts"]
    r = client.patch(f"/complaints/{cid}", headers=AUTH, json={"status": "a_resolver"}).json()
    assert r["status"] == "a_resolver" and r["resolved_at"] is None and r["updated_by"] == "Ana Teixeira"
    r = client.patch(f"/complaints/{cid}", headers=AUTH, json={"status": "resolvido", "response": "Corrigido no local."}).json()
    assert r["status"] == "resolvido" and r["resolved_at"] and r["response"] == "Corrigido no local."
    pub = client.get("/complaints", headers=PUBLIC, params={"status": "resolvido"}).json()
    assert any(i["id"] == cid and i["response"] == "Corrigido no local." for i in pub["items"])
    assert pub["counts"]["resolvido"] == before["resolvido"] + 1
    assert client.patch(f"/complaints/{cid}", headers=AUTH, json={"status": "feito"}).status_code == 422
    assert client.patch(f"/complaints/{cid}", headers=PUBLIC, json={"status": "resolvido"}).status_code == 401
    assert client.patch("/complaints/999999", headers=AUTH, json={"status": "resolvido"}).status_code == 404


def test_exportar_csv(client):
    assert client.get("/complaints/export.csv", headers=PUBLIC).status_code == 401
    r = client.get("/complaints/export.csv", headers=AUTH)
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    lines = r.text.lstrip("﻿").strip().splitlines()
    assert lines[0].startswith("id;criada_em;elemento")
    assert len(lines) - 1 == sum(client.get("/complaints", headers=AUTH).json()["counts"].values())


def test_reclamacoes_sobrevivem_a_reimportacao(client):
    from app import importar
    n = len(client.get("/complaints", headers=AUTH).json()["items"])
    importar.run(str(client.media_dir / "entrega"), database_url=__import__("os").environ["DATABASE_URL"])
    assert len(client.get("/complaints", headers=AUTH).json()["items"]) == n


def test_nao_mobiliario_e_outros(client):
    verify(client, "sin-aveiro-00160")
    r = client.post("/complaints", headers=PUBLIC, data={"element_id": "sin-aveiro-00160", "kind": "nao_mobiliario"})
    assert r.status_code == 201, r.text
    assert r.json()["kind_label"] == "Não é mobiliário urbano"
    assert client.post("/complaints", headers=PUBLIC, data={"element_id": "sin-aveiro-00160", "kind": "outro"}).status_code == 422
    r = client.post("/complaints", headers=PUBLIC, data={"element_id": "sin-aveiro-00160", "kind": "outro",
                                                         "message": "O sinal está tapado por uma árvore"})
    assert r.status_code == 201, r.text
    assert r.json()["kind_label"] == "Outros" and "message" not in r.json()


def test_historico_global(client):
    client.post("/elements/sin-aveiro-00113/validate", headers=AUTH)
    r = client.get("/history", headers=AUTH)
    assert r.status_code == 200
    h = r.json()
    assert h["total"] >= 1 and h["items"][0]["action_label"]
    assert all(i["action"] == "validar" for i in client.get("/history", headers=AUTH, params={"action": "validar"}).json()["items"])
    assert client.get("/history", headers=PUBLIC).status_code == 401
    csv = client.get("/history/export.csv", headers=AUTH)
    assert csv.status_code == 200 and csv.text.lstrip("﻿").startswith("data_hora;tecnico;acao")


def test_pipeline_atualiza_pedidos(client):
    j = client.post("/jobs/source", headers=AUTH, json={"source": "mapillary", "name": "Rua teste"}).json()
    fila = client.get("/jobs", headers=AUTH, params={"status": "na_fila"}).json()
    assert any(x["id"] == j["id"] for x in fila)
    r = client.patch(f"/jobs/{j['id']}", headers=AUTH, json={"status": "a_processar", "progress": 40}).json()
    assert r["status"] == "a_processar" and r["progress"] == 40
    r = client.patch(f"/jobs/{j['id']}", headers=AUTH, json={"status": "concluido", "n_images": 120, "n_elements": 30}).json()
    assert r["status"] == "concluido" and r["progress"] == 100 and r["n_images"] == 120
    assert client.patch(f"/jobs/{j['id']}", headers=AUTH, json={"status": "feito"}).status_code == 422
    assert client.patch(f"/jobs/{j['id']}", headers=PUBLIC, json={"status": "erro"}).status_code == 401


def test_pedido_importa_e_junta(client, tmp_path):
    import shutil
    from app import importar
    n0 = len(client.get("/elements", headers=AUTH).json()["features"])
    j = client.post("/jobs/source", headers=AUTH, json={"source": "mapillary", "name": "Rua nova"}).json()
    r = client.patch(f"/jobs/{j['id']}", headers=AUTH, json={"status": "a_processar", "progress": 50, "etapa": "deteccao"}).json()
    assert r["params"]["etapa"] == "deteccao"
    dst = client.media_dir / "entregas" / "pedido_teste"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(client.media_dir / "entrega", dst)
    r = client.post(f"/jobs/{j['id']}/importar", headers=AUTH, json={"pasta": "entregas/pedido_teste"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "concluido" and r.json()["n_elements"] == r.json()["import"]["elements"]
    feats = client.get("/elements", headers=AUTH).json()["features"]
    assert len(feats) == n0 + r.json()["import"]["elements"]             # somou, não substituiu
    assert any(f["properties"]["id"].startswith("pedido_teste:") for f in feats)   # ids repetidos com prefixo
    assert client.post(f"/jobs/{j['id']}/importar", headers=AUTH, json={"pasta": "../../etc"}).status_code == 400
    # repor o catálogo dos outros testes
    importar.run(str(client.media_dir / "entrega"), database_url=__import__("os").environ["DATABASE_URL"])


def test_confianca_minima_por_familia(client):
    todos = client.get("/elements", headers=AUTH).json()["features"]
    r = client.get("/elements", headers=AUTH, params={"min_conf": 0.99, "min_conf_family": "sinal,residuos"}).json()["features"]
    fams = {f["properties"]["family"] for f in r}
    assert all(f["properties"]["confidence"] >= 0.99 for f in r if f["properties"]["family"] in ("sinal", "residuos"))
    n_luz = sum(1 for f in todos if f["properties"]["family"] == "iluminacao")
    assert sum(1 for f in r if f["properties"]["family"] == "iluminacao") == n_luz   # a luz não é filtrada


def test_confianca_minima_cada_familia(client):
    todos = client.get("/elements", headers=AUTH).json()["features"]
    r = client.get("/elements", headers=AUTH, params={"min_conf_familia": "sinal:0.99,iluminacao:0.5"}).json()["features"]
    for f in r:
        p = f["properties"]
        if p["family"] == "sinal":
            assert p["confidence"] >= 0.99
        if p["family"] == "iluminacao":
            assert p["confidence"] >= 0.5
    for fam in ("residuos", "mobiliario"):   # sem limite: passam todos
        assert sum(1 for f in r if f["properties"]["family"] == fam) == sum(1 for f in todos if f["properties"]["family"] == fam)
    assert client.get("/elements", headers=AUTH, params={"min_conf_familia": "sinal:abc"}).status_code == 422
    assert client.get("/export.csv", headers=AUTH, params={"min_conf_familia": "sinal:0.5"}).status_code == 200
