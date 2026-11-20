"""Anonimização de rostos e matrículas ANTES de qualquer deteção (secção 11 do Plano).

    python -m ctrlf.privacy.blur_privacy data/raw/kartaview data/images/kartaview --audit 100

Os dois mecanismos correm SEMPRE (rostos e matrículas). Backend por omissão: RF-DETR (Apache-2.0), treinado no Open Images; o backend `yolo` (YuNet + YOLO, AGPL-3.0, pesos por conta própria) é opcional: UMS_PRIVACY_BACKEND=yolo.
Modos (diferem no veículo e no corpo):
  faces-plates (por omissão): SÓ rostos e matrículas; carros e corpos ficam intactos. Auditar com --audit (recall de matrículas < 100 %).
  strict: desfoca também a CAIXA INTEIRA de cada veículo e de cada pessoa (YOLO COCO). Mais seguro, mas o Grounding DINO vê blocos
        desfocados que confunde com contentores.
Falta de qualquer modelo => PrivacyConfigError (falha fechada). O Detector usa isto via privacy/gate.py.

--audit N gera <saída>/_audit/veiculos_*.jpg: os maiores veículos de N imagens JÁ desfocadas, em resolução legível,
para contares à mão matrículas/rostos que escaparam (objetivo: 0). A saída é re-codificada com OpenCV (perde o EXIF);
o meta.jsonl é copiado com `blurred=true` e escreve-se privacy_report.json.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import shutil
from pathlib import Path

import cv2
import numpy as np

from ctrlf.paths import ROOT
MODELS = Path(os.environ.get("UMS_MODELS_DIR", ROOT / "models"))     # pasta dos pesos (UMS_MODELS_DIR; por omissão <raiz>/models)
COCO_PERSON = {0}
COCO_VEHICLES = {1, 2, 3, 5, 7}      # bicicleta, carro, mota, autocarro, camião


def _iou(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0]); h = min(a[3], b[3]) - max(a[1], b[1])
    if w <= 0 or h <= 0:
        return 0.0
    i = w * h
    return i / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - i)


def _blur_box(img, x1, y1, x2, y2, margin=0.15):
    h, w = img.shape[:2]
    bw, bh = x2 - x1, y2 - y1
    x1 = int(max(0, x1 - margin * bw)); x2 = int(min(w, x2 + margin * bw))
    y1 = int(max(0, y1 - margin * bh)); y2 = int(min(h, y2 + margin * bh))
    if x2 <= x1 or y2 <= y1:
        return
    roi = img[y1:y2, x1:x2]
    k = max(15, (max(x2 - x1, y2 - y1) // 3) | 1)          # kernel ímpar proporcional
    img[y1:y2, x1:x2] = cv2.GaussianBlur(roi, (k, k), 0)
    # 2.ª passagem: pixelização, para um blur gaussiano não ser "des-desfocável"
    small = cv2.resize(img[y1:y2, x1:x2], (max(2, (x2 - x1) // 12), max(2, (y2 - y1) // 12)))
    img[y1:y2, x1:x2] = cv2.resize(small, (x2 - x1, y2 - y1), interpolation=cv2.INTER_NEAREST)


DEFAULT_PLATES = MODELS / "plates" / "morsetech_v1l" / "license-plate-finetune-v1l.pt"
DEFAULT_FACES = MODELS / "faces" / "uralman_yolo26l" / "best.pt"
# Backend RF-DETR (Apache-2.0; substitui os YOLO, AGPL-3.0). Escolha: argumento `backend=` ou UMS_PRIVACY_BACKEND=yolo|rfdetr (omissão: rfdetr, decisão do utilizador 2026-11-20; o yolo continua a existir mas exige instalar o ultralytics e ter os pesos YOLO por sua conta).
RFDETR_COCO = MODELS / "bench_detector" / "rf-detr-small.pth"                  # COCO oficial: pessoas e veículos
RFDETR_PLATES = MODELS / "detector_matriculas" / "checkpoint_best_total.pth"    # treinado com Open Images (scripts/privacidade_fila.sh)
RFDETR_FACES = MODELS / "detector_rostos" / "checkpoint_best_total.pth"


class PrivacyConfigError(RuntimeError):
    """Falta um modelo de anonimização. A deteção NUNCA corre sem ele (falha fechada)."""


def _nms(boxes, thr=0.3):
    keep = []
    for b in sorted(boxes, key=lambda b: -b[4]):
        if all(_iou(b, k) < thr for k in keep):
            keep.append(b)
    return keep


def _tiled_predict(model, bgr, tile, imgsz, conf, device):
    """[(x1, y1, x2, y2, score)] na imagem inteira. `tile` px por mosaico (0 = imagem inteira), 25 % de sobreposição."""
    H, W = bgr.shape[:2]
    if not tile or (H <= tile and W <= tile):
        r = model.predict(bgr, imgsz=imgsz, conf=conf, device=device, verbose=False)[0]
        return [(*map(float, b), float(s)) for b, s in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy())]
    S = max(1, int(tile * 0.75))
    xs = sorted({min(x, max(0, W - tile)) for x in range(0, max(W - tile, 0) + S, S)})
    ys = sorted({min(y, max(0, H - tile)) for y in range(0, max(H - tile, 0) + S, S)})
    origins = [(x, y) for y in ys for x in xs]
    tiles = [bgr[y:y + tile, x:x + tile] for x, y in origins]
    out = []
    for i in range(0, len(tiles), 4):                                       # lotes de 4 mosaicos (cabe em 6 GB)
        rs = model.predict(tiles[i:i + 4], imgsz=imgsz, conf=conf, device=device, verbose=False)
        for (x, y), r in zip(origins[i:i + 4], rs):
            for bx, sc in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.conf.cpu().numpy()):
                out.append((bx[0] + x, bx[1] + y, bx[2] + x, bx[3] + y, float(sc)))
    return _nms(out)


class Anonymizer:
    """Os DOIS mecanismos de privacidade correm SEMPRE, em qualquer modo:
         rostos     = YuNet (OpenCV)  U  YOLO26l-WIDER FACE em mosaicos
         matrículas = YOLO11l em mosaicos
       `mode` só decide o resto: "strict" desfoca ainda a caixa inteira de cada veículo; "faces-plates" não.
       Em faces-plates os corpos não se desfocam; em strict sim.  Se faltar qualquer modelo -> PrivacyConfigError (falha fechada).
    """

    def __init__(self, mode="faces-plates", plate_weights=DEFAULT_PLATES, face_weights=DEFAULT_FACES, device=0,
                 face_thr=0.3, det_conf=0.15, plate_tile=None, plate_imgsz=1280, plate_conf=0.1,
                 face_tile=960, face_imgsz=1280, face_conf=0.25, backend=None):
        backend = backend or os.environ.get("UMS_PRIVACY_BACKEND", "rfdetr")
        if backend not in ("yolo", "rfdetr"):
            raise PrivacyConfigError(f"backend de privacidade {backend!r} desconhecido (yolo | rfdetr)")
        if mode not in ("strict", "faces-plates"):
            raise PrivacyConfigError(f"modo {mode!r} desconhecido")
        self.backend = backend
        self.mode, self.det_conf, self.face_thr, self.device = mode, det_conf, face_thr, device
        # Mosaico das matrículas por modo (benchmark em 113 fotos: quanto mais pequeno, mais matrículas; ver reports/privacidade.md):
        # strict já desfoca o veículo inteiro -> 960 px; faces-plates só tem a matrícula como proteção -> 640 px.
        if plate_tile is None:
            plate_tile = 960 if mode == "strict" else 640
        self.plate_tile, self.plate_imgsz, self.plate_conf = plate_tile, plate_imgsz, plate_conf
        self.face_tile, self.face_imgsz, self.face_conf = face_tile, face_imgsz, face_conf
        self.face_model = MODELS / "face_detection_yunet_2023mar.onnx"
        if backend == "rfdetr":
            # caminhos .pt são os dos YOLO (omissão e configs/pipeline.yaml): com este backend usam-se os do RF-DETR (.pth), salvo se o chamador passar .pth
            plate_weights = plate_weights if Path(plate_weights).suffix == ".pth" else RFDETR_PLATES
            face_weights = face_weights if Path(face_weights).suffix == ".pth" else RFDETR_FACES
            coco_w = RFDETR_COCO
            for nome, f in (("RF-DETR COCO (pessoas/veículos)", coco_w), ("matrículas (RF-DETR)", plate_weights),
                            ("rostos (RF-DETR)", face_weights), ("rostos (YuNet)", self.face_model)):
                if not f or not Path(f).is_file():
                    raise PrivacyConfigError(f"falta o modelo de {nome}: {f}")
            from ctrlf.privacy.rfdetr_boxes import RFDETRBoxes
            dev = "cpu" if device == "cpu" else None
            self.coco = RFDETRBoxes(coco_w, kind="coco", variant="small", device=dev)
            self.plates = RFDETRBoxes(plate_weights, kind="checkpoint", device=dev)
            self.face_yolo = RFDETRBoxes(face_weights, kind="checkpoint", device=dev)
        else:
            try:
                from ultralytics import YOLO
            except ImportError as e:
                raise PrivacyConfigError("o backend `yolo` precisa do pacote `ultralytics` (AGPL-3.0, fora dos requirements por omissão: pip install -r requirements-yolo-opcional.txt) e dos pesos YOLO em models/: "
                                         "use UMS_PRIVACY_BACKEND=rfdetr (omissão)") from e
            yolo_w = next(iter(sorted(MODELS.glob("yolo*.pt"))), None)
            for nome, f in (("YOLO COCO (pessoas/veículos)", yolo_w), ("matrículas", plate_weights),
                            ("rostos (YOLO WIDER FACE)", face_weights), ("rostos (YuNet)", self.face_model)):
                if not f or not Path(f).is_file():
                    raise PrivacyConfigError(f"falta o modelo de {nome}: {f}")
            self.coco, self.plates, self.face_yolo = YOLO(str(yolo_w)), YOLO(str(plate_weights)), YOLO(str(face_weights))
        self.faces = None
        self.last_boxes = {"vehicles": [], "people": []}

    def _yunet(self, img):
        h, w = img.shape[:2]
        if self.faces is None:
            self.faces = cv2.FaceDetectorYN.create(str(self.face_model), "", (w, h), self.face_thr, 0.3, 5000)
        self.faces.setInputSize((w, h))
        _, f = self.faces.detect(img)
        return [] if f is None else [(float(r[0]), float(r[1]), float(r[0] + r[2]), float(r[1] + r[3]), float(r[14]))
                                     for r in f]

    def face_boxes(self, bgr):
        boxes = self._yunet(bgr) + _tiled_predict(self.face_yolo, bgr, self.face_tile, self.face_imgsz,
                                                  self.face_conf, self.device)
        H = bgr.shape[0]
        # um rosto real não ocupa > 30 % da altura da vista (os YOLO dão blocos enormes em paredes); só no faces-plates
        return [b[:4] for b in _nms(boxes) if self.mode == "strict" or (b[3] - b[1]) <= 0.3 * H]

    def plate_boxes(self, bgr, vehicles=None, free_conf=0.4):
        """Caixas de matrícula. Com `vehicles` (modo faces-plates), uma deteção fraca (< free_conf) só conta se o seu
        centro estiver dentro de um veículo (caixa alargada 15 %): corta os falsos em fachadas/janelas sem desfocar carros."""
        out = []
        W = bgr.shape[1]
        for x1, y1, x2, y2, s in _tiled_predict(self.plates, bgr, self.plate_tile, self.plate_imgsz,
                                                self.plate_conf, self.device):
            w, h = x2 - x1, y2 - y1
            if vehicles is not None and (w > 0.15 * W or w < 1.6 * h):   # matrícula = larga e baixa; blocos ~quadrados/enormes são artefactos
                continue
            if vehicles is not None and s < free_conf:
                cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
                if not any(v[0] - .15 * (v[2] - v[0]) <= cx <= v[2] + .15 * (v[2] - v[0]) and
                           v[1] - .15 * (v[3] - v[1]) <= cy <= v[3] + .15 * (v[3] - v[1]) for v in vehicles):
                    continue
            out.append((x1, y1, x2, y2))
        return out

    def __call__(self, bgr: np.ndarray) -> tuple[np.ndarray, dict]:
        img = bgr.copy()
        counts = {"faces": 0, "people": 0, "vehicles": 0, "plates": 0}
        for x1, y1, x2, y2 in self.face_boxes(bgr):                        # mecanismo 1: rostos
            _blur_box(img, x1, y1, x2, y2, margin=0.4); counts["faces"] += 1
        r = self.coco.predict(bgr, conf=self.det_conf, device=self.device, verbose=False)[0]
        self.last_boxes = {"vehicles": [], "people": []}                   # caixas (xyxy), úteis para filtrar deteções
        for (x1, y1, x2, y2), c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int)):
            box = (float(x1), float(y1), float(x2), float(y2))
            if c in COCO_VEHICLES:
                self.last_boxes["vehicles"].append(box)
                if self.mode == "strict":
                    _blur_box(img, x1, y1, x2, y2, margin=0.05); counts["vehicles"] += 1
            elif c in COCO_PERSON:
                self.last_boxes["people"].append(box)
                if self.mode == "strict":                                  # faces-plates: o corpo NÃO se desfoca, só a cara
                    _blur_box(img, x1, y1, x2, y2, margin=0.05); counts["people"] += 1
        veh = self.last_boxes["vehicles"] if self.mode == "faces-plates" else None
        for x1, y1, x2, y2 in self.plate_boxes(bgr, veh):                  # mecanismo 2: matrículas
            _blur_box(img, x1, y1, x2, y2, margin=0.3); counts["plates"] += 1
        return img, counts


def _audit_sheet(anon: "Anonymizer", sample: list[Path], ad: Path, per_img: int = 3, cell: int = 360) -> None:
    """Folha de auditoria: os maiores veículos das imagens JÁ desfocadas, em resolução legível (cell px de largura).

    As miniaturas da imagem inteira (320x180) não deixam ver nenhuma matrícula; aqui vê-se se alguma escapou.
    Os recortes saem das imagens de saída (já anonimizadas), nunca das originais.
    """
    tiles = []
    for p in sample:
        im = cv2.imread(str(p))
        r = anon.coco.predict(im, conf=anon.det_conf, device=anon.device, verbose=False)[0]
        veh = [(b, c) for b, c in zip(r.boxes.xyxy.cpu().numpy(), r.boxes.cls.cpu().numpy().astype(int))
               if c in COCO_VEHICLES]
        veh.sort(key=lambda bc: -(bc[0][2] - bc[0][0]) * (bc[0][3] - bc[0][1]))
        for (x1, y1, x2, y2), _ in veh[:per_img]:
            crop = im[int(y1):int(y2), int(x1):int(x2)]
            if crop.size == 0:
                continue
            s = cell / crop.shape[1]
            crop = cv2.resize(crop, (cell, max(1, int(crop.shape[0] * s))))[:cell]
            canvas = np.zeros((cell, cell, 3), np.uint8)
            canvas[:crop.shape[0]] = crop
            cv2.putText(canvas, p.stem[-8:], (4, cell - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            tiles.append(canvas)
    if not tiles:
        return
    cols = 5
    while len(tiles) % cols:
        tiles.append(np.zeros_like(tiles[0]))
    rows = [np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)]
    for n, i in enumerate(range(0, len(rows), 4)):                    # folhas de 4 linhas
        cv2.imwrite(str(ad / f"veiculos_{n + 1:02d}.jpg"), np.vstack(rows[i:i + 4]), [cv2.IMWRITE_JPEG_QUALITY, 90])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--mode", choices=["strict", "faces-plates"], default="faces-plates")
    ap.add_argument("--plate-weights", default=str(DEFAULT_PLATES))
    ap.add_argument("--face-weights", default=str(DEFAULT_FACES))
    ap.add_argument("--plate-tile", type=int, default=None, help="lado do mosaico em px (0 = imagem inteira; omissão: 960 strict, 640 faces-plates)")
    ap.add_argument("--plate-imgsz", type=int, default=1280)
    ap.add_argument("--plate-conf", type=float, default=0.1)
    ap.add_argument("--audit", type=int, default=0, help="N imagens de saída para auditar à mão")
    args = ap.parse_args()

    src, dst = Path(args.src), Path(args.dst); dst.mkdir(parents=True, exist_ok=True)
    try:
        anon = Anonymizer(args.mode, args.plate_weights, args.face_weights, plate_tile=args.plate_tile,
                          plate_imgsz=args.plate_imgsz, plate_conf=args.plate_conf)
    except PrivacyConfigError as e:
        raise SystemExit(f"ERRO de privacidade: {e}")
    files = sorted(p for p in src.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    tot = {"faces": 0, "people": 0, "vehicles": 0, "plates": 0}
    per_image = {}
    for p in files:
        bgr = cv2.imread(str(p))
        if bgr is None:
            continue
        out, c = anon(bgr)
        cv2.imwrite(str(dst / (p.stem + ".jpg")), out, [cv2.IMWRITE_JPEG_QUALITY, 90])
        per_image[p.stem] = c
        for k in tot:
            tot[k] += c[k]
    print(f"{len(files)} imagens -> {dst}   desfocados: {tot}")
    (dst / "privacy_report.json").write_text(json.dumps({
        "mode": args.mode, "plate_weights": args.plate_weights, "face_weights": args.face_weights,
        "plate": {"tile": args.plate_tile, "imgsz": args.plate_imgsz, "conf": args.plate_conf},
        "totals": tot, "per_image": per_image}, indent=1), encoding="utf-8")

    meta_in = src / "meta.jsonl"
    if meta_in.exists():
        with open(meta_in, encoding="utf-8") as fi, open(dst / "meta.jsonl", "w", encoding="utf-8") as fo:
            for line in fi:
                m = json.loads(line)
                m["path"] = str(dst / (Path(m["path"]).stem + ".jpg"))
                m.setdefault("extra", {})["blurred"] = True
                fo.write(json.dumps(m, ensure_ascii=False) + "\n")

    if args.audit:
        ad = dst / "_audit"; shutil.rmtree(ad, ignore_errors=True); ad.mkdir()
        rnd = random.Random(0)
        sample = rnd.sample(sorted(dst.glob("*.jpg")), min(args.audit, len(per_image)))
        _audit_sheet(anon, sample, ad)
        print(f"Auditoria: abre as folhas {ad}/veiculos_*.jpg e conta matrículas/rostos legíveis (objetivo: 0).")


if __name__ == "__main__":
    main()
