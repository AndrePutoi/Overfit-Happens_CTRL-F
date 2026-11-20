"""Adaptador RF-DETR da privacidade (privacy/rfdetr_boxes.py): interface do YOLO, BGR->RGB, ids de classe COCO->YOLO por nome.
Sem GPU nem pesos (modelo falso). Com UMS_MODELS_DIR e o COCO oficial presentes, corre também um teste real em CPU (veículos/pessoas numa imagem de Aveiro)."""
import os
import sys
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.privacy.rfdetr_boxes import YOLO_IDX, RFDETRBoxes, RFDETRBoxesError  # noqa: E402

res = {}


class Det:                                            # imita supervision.Detections
    def __init__(self, xyxy, conf, cid):
        self.xyxy, self.confidence, self.class_id = np.array(xyxy, float).reshape(-1, 4), np.array(conf, float), np.array(cid, int)


class Falso:
    vistas = []

    def predict(self, imgs, threshold):
        Falso.vistas = [(im.shape, int(im[0, 0, 0]), int(im[0, 0, 2]), threshold) for im in imgs]
        # ids COCO oficiais do RF-DETR: pessoa=1, bicicleta=2, carro=3, mota=4, autocarro=6, camião=8, banco=15, gato=17
        return [Det([[1, 2, 30, 40], [5, 5, 9, 9], [0, 0, 4, 4], [2, 2, 6, 6]], [.9, .8, .7, .6], [3, 1, 15, 17]) for _ in imgs]


COCO = {1: "person", 2: "bicycle", 3: "car", 4: "motorcycle", 6: "bus", 8: "truck", 15: "bench", 17: "cat"}
img = np.zeros((20, 30, 3), np.uint8)
img[..., 0], img[..., 2] = 10, 200                    # BGR: B=10, R=200


def loader_coco(w, kind, variant, dev):
    return Falso(), COCO


m = RFDETRBoxes("x.pth", kind="coco", model_loader=loader_coco)
r = m.predict([img, img], conf=0.15)
cls = r[0].boxes.cls.numpy().tolist()
res["T1 ids COCO->YOLO por nome (carro=2, pessoa=0; banco e gato saem)"] = (cls == [2.0, 0.0] and r[0].boxes.xyxy.shape == (2, 4) and len(r) == 2)
res["T2 BGR->RGB (a 1.ª componente que o modelo vê é o vermelho) e limiar passado"] = (Falso.vistas[0][1:] == (200, 10, 0.15) and len(Falso.vistas) == 2)
res["T3 interface do YOLO: .cpu().numpy() nas caixas, confianças e classes"] = all(hasattr(getattr(r[0].boxes, a), "cpu") and getattr(r[0].boxes, a).cpu().numpy() is not None for a in ("xyxy", "conf", "cls"))
res["T4 o mapa só tem as classes que o anonimizador usa"] = set(m.map_cls.values()) == set(YOLO_IDX.values())
r1 = m.predict(img)                                    # uma só imagem (não lista) também funciona
res["T5 imagem única devolve lista de 1"] = len(r1) == 1


def loader_um(w, kind, variant, dev):
    return Falso(), {0: "rosto"}


u = RFDETRBoxes("x.pth", kind="checkpoint", model_loader=loader_um).predict(img)
res["T6 detetor de uma classe: cls = 0 em todas as caixas"] = set(u[0].boxes.cls.numpy().tolist()) == {0.0}


def loader_sem_carro(w, kind, variant, dev):
    return Falso(), {1: "person"}


try:
    RFDETRBoxes("x.pth", kind="coco", model_loader=loader_sem_carro)
    res["T7 COCO sem as classes necessárias falha fechado"] = False
except RFDETRBoxesError:
    res["T7 COCO sem as classes necessárias falha fechado"] = True
try:
    RFDETRBoxes(ROOT / "nao_existe.pth", kind="checkpoint")
    res["T8 pesos em falta falham fechado"] = False
except RFDETRBoxesError:
    res["T8 pesos em falta falham fechado"] = True

# T9 (opcional): COCO oficial real, em CPU, numa imagem de Aveiro
coco_w = Path(os.environ.get("UMS_MODELS_DIR", ROOT / "models")) / "bench_detector" / "rf-detr-small.pth"
amostra = ROOT / "tests" / "fixtures" / "samples" / "aveiro_2.jpg"
if coco_w.is_file() and amostra.is_file():
    import cv2
    real = RFDETRBoxes(coco_w, kind="coco", variant="small", device="cpu")
    out = real.predict(cv2.imread(str(amostra)), conf=0.3)[0].boxes
    ids = set(out.cls.numpy().astype(int).tolist())
    res["T9 COCO real em CPU: só devolve ids YOLO de pessoas/veículos"] = ids <= set(YOLO_IDX.values())
    print(f"     (T9: {len(out.cls)} caixas em aveiro_2.jpg, ids {sorted(ids)})")
else:
    print("     (T9 saltado: sem os pesos COCO ou sem a imagem de amostra)")

for k, v in res.items():
    print(f"{'PASS' if v else 'FAIL'}  {k}")
ok = all(res.values())
print("overall:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
