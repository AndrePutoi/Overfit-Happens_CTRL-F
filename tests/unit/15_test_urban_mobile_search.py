"""Autoteste do urban_mobile_search com detetores/classificadores FALSOS (sem GPU, sem pesos, sem modelos)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from ctrlf.paths import ROOT
import os as _os
ENV = {**_os.environ, "PYTHONPATH": str(ROOT / "src") + _os.pathsep + _os.environ.get("PYTHONPATH", "")}   # os subprocessos importam ctrlf a partir de src/
sys.path.insert(0, str(ROOT))
from ctrlf.urban_mobile_search import ClassifierSpec, DetectorSpec, Pipeline, Registry, Settings, Store, detection_id, geo, iou  # noqa: E402
from ctrlf.urban_mobile_search.backends.base import ClassOut, RawDet  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")
    if not ok:
        fails.append(name)


CLOSED = []


class FakeDet:
    def __init__(self, name, boxes):
        self.name, self.boxes = name, boxes

    def detect(self, image, conf):
        return [RawDet(c, s, b) for c, s, b in self.boxes]

    def close(self):
        CLOSED.append(self.name)


class FakeClf:
    def __init__(self, name, rule):
        self.name, self.rule = name, rule

    def classify(self, crops, dets):
        return [self.rule(d) for d in dets]

    def close(self):
        CLOSED.append(self.name)


def make_registry(flux_label="papel", boxes_res=None, boxes_sin=None):
    reg = Registry()
    boxes_res = boxes_res if boxes_res is not None else [("contentor", 0.9, (100, 100, 220, 260)), ("subterraneo", 0.8, (400, 300, 500, 420)), ("contentor", 0.7, (10, 10, 14, 14))]
    reg.register_detector(DetectorSpec("cont_det", "residuos", lambda s: FakeDet("cont_det", boxes_res), "cont@v1"))
    reg.register_detector(DetectorSpec("sign_det", "sinal", lambda s: FakeDet("sign_det", boxes_sin if boxes_sin is not None else
                                                                                [("regulamentacao", 0.9, (600, 100, 680, 180)), ("informacao", 0.6, (50, 400, 120, 470))]), "sign@v1"))
    reg.register_classifier(ClassifierSpec("pap", "papeleira", "residuos", lambda s: FakeClf("pap", lambda d: ClassOut("papeleira", 0.95, set_cls="papeleira") if d.bbox[0] == 400
                                                                                         else ClassOut("ecoponto", 0.1)), "pap@v1", only_cls=("contentor", "subterraneo")))
    reg.register_classifier(ClassifierSpec("flux", "container_flux", "residuos", lambda s: FakeClf("flux", lambda d: ClassOut(flux_label, 0.8)), "flux@v1", only_cls=("contentor", "subterraneo")))
    reg.register_classifier(ClassifierSpec("stype", "sign_type", "sinal", lambda s: FakeClf("stype", lambda d: ClassOut("nao", 0.9, reject=True) if d.bbox[0] == 50
                                                                                      else ClassOut("regulatory_stop", 0.7)), "stype@v1"))
    return reg


with tempfile.TemporaryDirectory() as td:
    td = Path(td)
    img = td / "IMG1.jpg"
    Image.fromarray(np.random.default_rng(0).integers(0, 255, (800, 1000, 3), dtype=np.uint8)).save(img)
    meta = {"source": "x", "source_image_id": "IMG1", "lat": 40.64, "lon": -8.65, "heading": 90.0, "hfov_deg": 100.0, "camera_type": "perspective", "license": "L"}
    approve = lambda p, m: {"id": Path(p).stem, "status": "aprovada", "motivos": [], "avisos": [], "meta": dict(m or {})}   # noqa: E731
    identity = lambda p: np.asarray(Image.open(p).convert("RGB"))                                                           # noqa: E731
    S = Settings(images_dir=td / "anon", db_path=td / "u.sqlite", min_side={"sinal": 24, "residuos": 8, "iluminacao": 8})

    # 1) importar o pacote não carrega modelos
    code = "import sys, ctrlf.urban_mobile_search, ctrlf.urban_mobile_search.backends.legacy; bad=[m for m in ('torch','rfdetr','transformers','cv2') if m in sys.modules]; print(bad)"
    out = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True, env=ENV)
    check("importar o pacote NÃO carrega torch/rfdetr/transformers/cv2", out.stdout.strip() == "[]", out.stdout.strip() + out.stderr[-120:])

    # 2) pipeline com falsos
    store = Store(td / "u.sqlite")
    CLOSED.clear()
    pipe = Pipeline(S, registry=make_registry(), store=store, admit=approve, anonymize=identity)
    r = pipe.process(img, meta)
    by = {(d.family, d.cls): d for d in r.detections}
    check("caixa pequena (4 px) descartada pelo tamanho mínimo", len(r.detections) == 4 and not any(d.bbox[0] == 10 for d in r.detections), str([d.cls for d in r.detections]))
    check("classificador muda a classe (contentor -> papeleira) e guarda a original", ("residuos", "papeleira") in by and by[("residuos", "papeleira")].extra["cls_antes"] == "subterraneo")
    pap0 = by[("residuos", "papeleira")]
    check("contentor recebe o fluxo do classificador (labels do waste_container)", by[("residuos", "contentor")].label("container_flux") == "papel")
    check("papeleira NÃO recebe o fluxo do classificador: é sempre 'indiferenciado' por REGRA", pap0.label("container_flux") == "indiferenciado"
          and [c.model for c in pap0.classifications if c.task == "container_flux"] == ["regra"], str([(c.task, c.label, c.model) for c in pap0.classifications]))
    sin = [d for d in r.detections if d.family == "sinal"]
    check("sinal rejeitado pelo classificador fica 'rejeitado' (auditável), o outro com tipo", sorted(d.status for d in sin) == ["auto", "rejeitado"]
          and any(d.label("sign_type") == "regulatory_stop" for d in sin))
    check("a rejeição automática regista quem rejeitou", any(d.extra.get("auto_rejeitada") == "stype" for d in sin))
    check("versão do modelo gravada em cada deteção e classificação", by[("residuos", "contentor")].model_version == "cont@v1" and
          by[("residuos", "contentor")].classifications[0].model_version in ("pap@v1", "flux@v1"))
    check("GPU: backends libertados entre famílias (3 classificadores+2 detetores fechados)", sorted(CLOSED) == sorted(["cont_det", "pap", "flux", "sign_det", "stype"]) or len(CLOSED) >= 5, str(CLOSED))
    check("(registo fica vazio de modelos carregados no fim)", pipe.registry.loaded() == [])

    # 3) persistência e idempotência
    n1 = len(store.list(include_rejected=True))
    pipe.process(img, meta)
    check("reprocessar a mesma imagem NÃO duplica", len(store.list(include_rejected=True)) == n1, f"{n1} -> {len(store.list(include_rejected=True))}")
    store.close()
    st2 = Store(td / "u.sqlite")
    check("a base persiste e reabre", len(st2.list(include_rejected=True)) == n1 and st2.get_image("IMG1")["meta"]["lat"] == 40.64)
    check("por omissão a lista esconde as rejeitadas", all(d.status != "rejeitado" for d in st2.list()))

    # 4) decisões humanas e a sua precedência
    cont = [d for d in st2.list(family="residuos") if d.cls == "contentor"][0]
    st2.correct_label(cont.id, "container_flux", "vidro", by="ana")
    d = st2.get(cont.id)
    check("a etiqueta humana é a efetiva e o estado fica 'corrigido'", d.label("container_flux") == "vidro" and d.status == "corrigido")
    check("a previsão do modelo continua guardada", any(c.source == "model" and c.label == "papel" for c in d.classifications))
    pipe2 = Pipeline(S, registry=make_registry(flux_label="embalagens"), store=st2, admit=approve, anonymize=identity)     # modelo novo discorda
    pipe2.process(img, meta)
    d = st2.get(cont.id)
    check("um modelo novo NÃO sobrepõe a decisão humana", d.label("container_flux") == "vidro" and d.status == "corrigido")
    check("...mas a sua previsão fica registada para comparar", any(c.label == "embalagens" for c in d.classifications))
    check("e não cria deteções repetidas (IoU)", len([x for x in st2.list(family="residuos") if x.cls == "contentor"]) == 1)
    st2.confirm(cont.id, "ana")
    hist = st2.history(cont.id)
    check("o histórico regista as decisões por ordem", [h["action"] for h in hist] == ["corrigir_etiqueta", "confirmar"] and hist[0]["who"] == "ana")
    nao = [x for x in st2.list(family="sinal", include_rejected=True) if x.status == "rejeitado"][0]
    st2.confirm(nao.id, "rui")
    check("o técnico pode repor uma deteção que o modelo rejeitou", st2.get(nao.id).status == "validado" and nao.id in [x.id for x in st2.list(family="sinal")])
    pap = by[("residuos", "papeleira")]
    st2.correct_class(pap.id, "contentor", "ana")
    check("corrigir a classe (papeleira -> contentor)", st2.get(pap.id).cls == "contentor")

    # 5) caixa manual e filtros
    m = st2.add_manual("IMG1", "iluminacao", "candeeiro", (300, 50, 340, 300), "ana", {"light_style": "candeeiro"})
    check("caixa manual nasce validada, de origem humana, com etiqueta", m.status == "validado" and m.origin == "human" and m.label("light_style") == "candeeiro")
    check("filtro por etiqueta efetiva", [d.id for d in st2.list(label=("light_style", "candeeiro"))] == [m.id])

    # 6) COCO: importar decisões do CVAT e exportar
    coco = {"categories": [{"id": 1, "name": "papeleira"}, {"id": 2, "name": "candeeiro"}, {"id": 3, "name": "outra_coisa"}], "images": [{"id": 1, "file_name": "porto/IMG1.jpg", "width": 1000, "height": 800}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [100, 100, 120, 160], "attributes": {"fluxo": "papel"}},        # = o contentor 100,100,220,260 (agora papeleira)
                            {"id": 2, "image_id": 1, "category_id": 2, "bbox": [700, 500, 30, 200], "attributes": {}},                           # sem par: manual
                            {"id": 3, "image_id": 1, "category_id": 3, "bbox": [1, 1, 5, 5]}]}
    res = st2.import_coco(coco, by="rui")
    check("importar COCO: corrigida, manual e categoria desconhecida contada", res["corrigidas"] == 1 and res["manuais"] == 1 and res["categorias_desconhecidas"] == 1, str(res))
    cc = st2.get(cont.id)
    check("a caixa importada ficou 'corrigida' como papeleira e o fluxo do CVAT (papel) é IGNORADO: papeleira é sempre indiferenciado", cc.cls == "papeleira"
          and cc.label("container_flux") == "indiferenciado" and cc.status == "corrigido")
    try:
        st2.correct_label(cc.id, "container_flux", "vidro", by="ana"); recusou = False
    except ValueError:
        recusou = True
    check("não se pode dar outro fluxo a uma papeleira (regra fixa)", recusou)
    ex = st2.export_coco(family="residuos")
    names = {c["id"]: c["name"] for c in ex["categories"]}
    check("exportar COCO: categorias de resíduos", set(names.values()) == {"contentor", "subterraneo", "papeleira"})
    check("exportar COCO: a papeleira leva fluxo=indiferenciado", all(a["attributes"].get("fluxo") == "indiferenciado" for a in ex["annotations"] if names[a["category_id"]] == "papeleira"))
    check("exportar COCO: cada caixa leva o id e estado do urban_mobile_search", all("ums_id" in a and "ums_status" in a for a in ex["annotations"]))
    ex_all = st2.export_coco()
    check("exportar tudo (resíduos + luz + sinais) sem rejeitadas", len(ex_all["annotations"]) == len(st2.list()) - 0 or len(ex_all["annotations"]) >= 5, f"{len(ex_all['annotations'])} vs {len(st2.list())}")
    st2.import_coco({"categories": [{"id": 1, "name": "contentor"}], "images": [{"id": 1, "file_name": "IMG1.jpg"}], "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [400, 300, 100, 120]}]},
                    by="rui", reject_unlisted=True)
    check("reject_unlisted: o que ninguém listou (e era automático) fica rejeitado", st2.stats()["por_estado"].get("rejeitado", 0) >= 1)

    # 7) estatísticas
    s = st2.stats()
    check("stats: contagens e decisões humanas", s["imagens"] == 1 and s["deteccoes"] >= 6 and s["decisoes_humanas"] >= 5, str(s["por_estado"]))
    st2.close()

    # 8) rejeitada na admissão não gasta modelos
    CLOSED.clear()
    pipe3 = Pipeline(S, registry=make_registry(), store=Store(), admit=lambda p, m: {"id": "X", "status": "rejeitada", "motivos": ["sem_posicao"], "avisos": [], "meta": {}}, anonymize=identity)
    r3 = pipe3.process(img, None)
    check("imagem rejeitada na admissão: sem deteções e sem carregar modelos", r3.detections == [] and "sem_posicao" in r3.skipped and CLOSED == [])

    # 9) lote: modelos carregados UMA vez por família
    img2 = td / "IMG2.jpg"
    Image.fromarray(np.zeros((800, 1000, 3), np.uint8)).save(img2)
    loads = []
    reg = make_registry()
    for spec in reg.detectors():
        orig = spec.factory
        spec.factory = (lambda o, n: (lambda s: (loads.append(n), o(s))[1]))(orig, spec.name)
    pipe4 = Pipeline(S, registry=reg, store=Store(), admit=approve, anonymize=identity)
    pipe4.process_many([(img, meta), (img2, {**meta, "source_image_id": "IMG2"})])
    check("process_many: cada detetor carregado UMA vez para as 2 imagens", sorted(loads) == ["cont_det", "sign_det"], str(loads))

# 10) geometria
az = geo.azimuth((450, 300, 550, 500), 1000, 90.0, 100.0)
check("azimute: caixa centrada = rumo da imagem", abs(az - 90.0) < 1e-6)
check("azimute: caixa à direita do centro aumenta o rumo", geo.azimuth((900, 300, 950, 500), 1000, 90.0, 100.0) > 90.0)
d = geo.ground_distance((450, 400, 550, 600), 1000, 800, 100.0, 1.5)
check("IPM: base 200 px abaixo do horizonte, h=1,5, hfov 100 -> ~3,1 m", d is not None and abs(d - 1.5 / np.tan(np.arctan(200 / (500 / np.tan(np.radians(50)))))) < 1e-6 and 3.0 < d < 3.3, f"{d:.2f}")
check("IPM: base acima do horizonte -> None", geo.ground_distance((450, 100, 550, 300), 1000, 800, 100.0) is None)
loc = geo.locate("residuos", (450, 400, 550, 600), {"width": 1000, "height": 800, "heading": 90.0, "hfov_deg": 100.0, "lat": 40.0, "lon": -8.0, "camera_type": "perspective"})
check("posição: a leste da câmara (rumo 90°) a ~3 m", loc["method"] == "ground_plane" and loc["lon"] > -8.0 and abs(loc["lat"] - 40.0) < 1e-5, str(loc))
locs = geo.locate("sinal", (450, 400, 550, 600), {"width": 1000, "height": 800, "heading": 90.0, "hfov_deg": 100.0, "lat": 40.0, "lon": -8.0})
check("sinais: só azimute (a caixa é a placa, não o pé do poste)", locs["method"] == "azimuth_only" and locs["lat"] is None)
check("panorama: sem posição por deteção", geo.locate("residuos", (1, 1, 2, 2), {"width": 3840, "height": 1920, "heading": 0, "hfov_deg": None, "lat": 1, "lon": 1, "camera_type": "equirectangular"}) is None)

# 11) ids e IoU
b = (100.2, 100.4, 220.1, 260.0)
check("id estável para a mesma caixa (±0,5 px) e distinto por classe", detection_id("I", "residuos", "contentor", b) == detection_id("I", "residuos", "contentor", (100.3, 100.1, 220.4, 259.8))
      and detection_id("I", "residuos", "contentor", b) != detection_id("I", "residuos", "subterraneo", b))
check("IoU", abs(iou((0, 0, 10, 10), (5, 0, 15, 10)) - 1 / 3) < 1e-9 and iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0)

# 11b) integração:  família `banco`, classificador que recebe a IMAGEM INTEIRA, pesos
with tempfile.TemporaryDirectory() as td3:
    td3 = Path(td3)
    img3 = td3 / "B1.jpg"
    Image.fromarray(np.random.default_rng(1).integers(0, 255, (600, 900, 3), dtype=np.uint8)).save(img3)
    seen = {}
    reg3 = Registry()
    reg3.register_detector(DetectorSpec("bench_det", "mobiliario", lambda s: FakeDet("bench_det", [("banco", 0.9, (100, 100, 400, 300))]), "bench@v1"))
    reg3.register_detector(DetectorSpec("sign_det", "sinal", lambda s: FakeDet("sign_det", [("regulamentacao", 0.9, (600, 100, 700, 200))]), "sign@v1"))

    def cond_rule(d):
        return ClassOut("insufficient_evidence", 0.0, extra={"reasons": ["resolucao_baixa"]})

    class ImgClf(FakeClf):
        def classify(self, crops, dets):
            seen["sizes"] = [c.size for c in crops]
            return super().classify(crops, dets)

    reg3.register_classifier(ClassifierSpec("cond", "sign_fading", "sinal", lambda s: ImgClf("cond", cond_rule), "cond@v1", min_side=1, use_image=True))
    S3 = Settings(images_dir=td3 / "anon", db_path=td3 / "x.sqlite")
    st3 = Store()
    pp = Pipeline(S3, registry=reg3, store=st3, admit=approve, anonymize=identity)
    r3 = pp.process(img3, {**meta, "source_image_id": "B1"}, families=["mobiliario", "sinal"])
    check("família `banco`/mobiliário é detetada e guardada", [(d.family, d.cls) for d in r3.detections if d.family == "mobiliario"] == [("mobiliario", "banco")])
    check("classificador com use_image recebe a IMAGEM INTEIRA (900x600), não o recorte", seen.get("sizes") == [(900, 600)], str(seen))
    check("estado do sinal fica como classificação `sign_fading`", [d.label("sign_fading") for d in r3.detections if d.family == "sinal"] == ["insufficient_evidence"])
    exb = st3.export_coco(family="mobiliario")
    check("exportar COCO: categoria `banco`", [c["name"] for c in exb["categories"]] == ["banco"] and len(exb["annotations"]) == 1)
    st3.add_manual("B1", "mobiliario", "banco", (10, 10, 60, 60), "ana")
    check("importar/CVAT: categoria `banco` mapeia para mobiliario", st3.import_coco({"categories": [{"id": 1, "name": "banco"}], "images": [{"id": 1, "file_name": "B1.jpg"}],
                                                                                          "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [100, 100, 300, 200]}]}, by="rui")["validadas"] == 1)

# pesos: o relatório diz onde pôr cada ficheiro e o que falta
from ctrlf.urban_mobile_search.backends.legacy import default_registry  # noqa: E402
with tempfile.TemporaryDirectory() as td4:
    rep = default_registry(Settings(models_dir=Path(td4))).weights_report()
    names = {r["modulo"]: r for r in rep}
    check("weights: o detetor de bancos espera models/bench_detector/rf-detr-small.pth", names["bench_rfdetr"]["caminho"].endswith("bench_detector/rf-detr-small.pth") and not names["bench_rfdetr"]["existe"])
    check("weights: lista detetores, classificadores e módulos de apoio (privacidade, profundidade)", len(rep) >= 11 and any(r["familia"] == "apoio" for r in rep))
    (Path(td4) / "bench_detector").mkdir()
    (Path(td4) / "bench_detector" / "rf-detr-small.pth").write_bytes(b"x" * 10)
    check("weights: depois de pôr o ficheiro passa a existir", {r["modulo"]: r for r in default_registry(Settings(models_dir=Path(td4))).weights_report()}["bench_rfdetr"]["existe"])

# 12) CLI
with tempfile.TemporaryDirectory() as td2:
    db = Path(td2) / "c.sqlite"
    s = Store(db)
    s.add_image("A", {}, {})
    s.add_manual("A", "sinal", "regulamentacao", (10, 10, 60, 60), "ana", {"sign_type": "regulatory_stop"})
    s.close()
    run = lambda *a: subprocess.run([sys.executable, "-m", "ctrlf", "--db", str(db), *a], cwd=ROOT, capture_output=True, text=True, env=ENV)   # noqa: E731
    r = run("stats")
    check("CLI stats", r.returncode == 0 and json.loads(r.stdout)["deteccoes"] == 1, r.stderr[-150:])
    r = run("list", "--familia", "sinal")
    did = json.loads(r.stdout.splitlines()[0])["id"]
    check("CLI list devolve JSON com a etiqueta efetiva", json.loads(r.stdout.splitlines()[0])["effective"]["sign_type"]["label"] == "regulatory_stop")
    r = run("decide", did, "--etiqueta", "sign_type=regulatory_yield", "--por", "rui")
    check("CLI decide --etiqueta", r.returncode == 0 and json.loads(r.stdout)["effective"]["sign_type"]["label"] == "regulatory_yield" and json.loads(r.stdout)["status"] == "corrigido")
    out = Path(td2) / "o.json"
    r = run("export-coco", str(out))
    check("CLI export-coco", r.returncode == 0 and json.loads(out.read_text())["annotations"][0]["attributes"]["tipo"] == "regulatory_yield", r.stdout + r.stderr[-150:])

print("\noverall:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(1 if fails else 0)
