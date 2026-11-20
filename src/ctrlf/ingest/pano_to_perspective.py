"""Converte panoramas equirectangulares (360°) em vistas em perspetiva, para ANOTAR e para o detetor.

O Grounding DINO / RF-DETR e a anotação em CVAT não funcionam bem na projeção equirectangular (as formas ficam
distorcidas). Cada panorama dá N vistas de `--fov` graus; cada vista tem o seu rumo (rumo do panorama + yaw).

    python -m ctrlf.ingest.pano_to_perspective data/raw/_panoramas_originais/porto data/raw/porto
    python -m ctrlf.ingest.pano_to_perspective SRC DST --yaws 0 60 120 180 240 300 --fov 90 --pitch 0

Lê SRC/meta.jsonl. Imagens em perspetiva passam inalteradas (cópia). Panoramas (camera_type=equirectangular) geram
DST/<id>_y<yaw>.jpg e uma linha nova no DST/meta.jsonl (camera_type=perspective, hfov_deg=fov, heading=rumo+yaw,
extra.pano_id/yaw/pitch). O centro do panorama aponta para o rumo (compass_angle) do panorama (convenção Mapillary,
A CONFIRMAR em imagens reais: ver tests/unit/11_test_pano_to_perspective.py para o que está verificado).
Estas vistas ainda NÃO passaram pelo portão de privacidade (privacy/gate.py).
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))


def equirect_to_persp(pano: np.ndarray, yaw_deg: float, pitch_deg: float, fov_deg: float, out_w: int, out_h: int) -> np.ndarray:
    """Vista em perspetiva. yaw>0 = virar para a direita (rumo aumenta); pitch>0 = olhar para cima."""
    H, W = pano.shape[:2]
    f = (out_w / 2) / math.tan(math.radians(fov_deg) / 2)
    xs = (np.arange(out_w) - (out_w - 1) / 2) / f
    ys = -(np.arange(out_h) - (out_h - 1) / 2) / f            # y para cima
    x, y = np.meshgrid(xs, ys)
    z = np.ones_like(x)
    p, t = math.radians(pitch_deg), math.radians(yaw_deg)
    y1 = y * math.cos(p) + z * math.sin(p)                    # pitch em torno de X
    z1 = -y * math.sin(p) + z * math.cos(p)
    x2 = x * math.cos(t) + z1 * math.sin(t)                   # yaw em torno de Y
    z2 = -x * math.sin(t) + z1 * math.cos(t)
    lon = np.arctan2(x2, z2)
    lat = np.arcsin(y1 / np.sqrt(x2 ** 2 + y1 ** 2 + z2 ** 2))
    u = ((lon / (2 * math.pi) + 0.5) * W - 0.5).astype(np.float32)
    v = ((0.5 - lat / math.pi) * H - 0.5).astype(np.float32)
    return cv2.remap(pano, u, v, cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("src"); ap.add_argument("dst")
    ap.add_argument("--yaws", type=float, nargs="+", default=[0, 60, 120, 180, 240, 300])
    ap.add_argument("--fov", type=float, default=90.0)
    ap.add_argument("--pitch", type=float, default=0.0)
    ap.add_argument("--max-width", type=int, default=2048, help="largura máxima de cada vista (px)")
    a = ap.parse_args()
    src, dst = Path(a.src), Path(a.dst); dst.mkdir(parents=True, exist_ok=True)
    n_pano = n_views = n_copy = 0
    with open(src / "meta.jsonl", encoding="utf-8") as fi, open(dst / "meta.jsonl", "a", encoding="utf-8") as fo:
        for line in fi:
            m = json.loads(line)
            img_path = src / Path(m["path"]).name
            if m.get("camera_type") != "equirectangular":
                d = dst / img_path.name
                if img_path.exists() and not d.exists():
                    shutil.copy(img_path, d)
                m["path"] = str(d); fo.write(json.dumps(m, ensure_ascii=False) + "\n"); n_copy += 1
                continue
            pano = cv2.imread(str(img_path))
            if pano is None:
                continue
            n_pano += 1
            Hp, Wp = pano.shape[:2]
            out_w = min(a.max_width, int(Wp * a.fov / 360)); out_h = out_w * 3 // 4
            for yaw in a.yaws:
                view = equirect_to_persp(pano, yaw, a.pitch, a.fov, out_w, out_h)
                name = f"{m['source_image_id']}_y{int(yaw)}.jpg"
                cv2.imwrite(str(dst / name), view, [cv2.IMWRITE_JPEG_QUALITY, 92])
                v = dict(m)
                v.update(source_image_id=f"{m['source_image_id']}_y{int(yaw)}", camera_type="perspective",
                         hfov_deg=a.fov, heading=(float(m["heading"]) + yaw) % 360, path=str(dst / name))
                v["extra"] = {**(m.get("extra") or {}), "pano_id": m["source_image_id"], "yaw": yaw, "pitch": a.pitch}
                fo.write(json.dumps(v, ensure_ascii=False) + "\n"); n_views += 1
    print(f"{n_pano} panoramas -> {n_views} vistas | {n_copy} imagens em perspetiva copiadas | {dst}")


if __name__ == "__main__":
    main()
