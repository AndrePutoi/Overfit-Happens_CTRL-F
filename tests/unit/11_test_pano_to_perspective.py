"""Verifica a geometria de ingest/pano_to_perspective.py com um panorama SINTÉTICO que codifica a direção em cada pixel:
canal R = longitude (0..255 ao longo de 360°), canal G = latitude (0 em cima .. 255 em baixo). Sem imagens reais."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.ingest.pano_to_perspective import equirect_to_persp  # noqa: E402

W, H = 4000, 2000
u = np.linspace(0, 255, W, dtype=np.float32)[None, :].repeat(H, 0)
v = np.linspace(0, 255, H, dtype=np.float32)[:, None].repeat(W, 1)
pano = np.dstack([np.zeros_like(u), v, u]).astype(np.uint8)       # BGR: B=0, G=v, R=u
fails = []


def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")
    if not ok:
        fails.append(name)


def centre(view):
    h, w = view.shape[:2]
    px = view[h // 2, w // 2]
    return int(px[2]), int(px[1])              # R (longitude), G (latitude)


# longitude lon ∈ [-180,180] -> R = (lon/360 + .5)*255 ; latitude lat ∈ [-90,90] -> G = (.5 - lat/180)*255
R_of = lambda lon: (lon / 360 + .5) * 255
G_of = lambda lat: (.5 - lat / 180) * 255
for yaw, pitch in ((0, 0), (90, 0), (-90, 0), (180, 0), (45, 0), (0, 30), (0, -30), (90, 20)):
    r, g = centre(equirect_to_persp(pano, yaw, pitch, 90, 400, 300))
    # o centro da vista aponta para longitude=yaw (se pitch=0) e latitude=pitch
    exp_lon = yaw if abs(pitch) < 1e-9 else None
    ok_g = abs(g - G_of(pitch)) < 3
    ok_r = True if exp_lon is None else min(abs(r - R_of(((exp_lon + 180) % 360) - 180)), abs(abs(r - R_of(((exp_lon + 180) % 360) - 180)) - 255)) < 3
    check(f"centro yaw={yaw:4d} pitch={pitch:3d}", ok_r and ok_g, f"R={r} G={g}")

# direita da vista ↔ longitude maior (rumo aumenta para a direita)
v0 = equirect_to_persp(pano, 0, 0, 90, 400, 300)
check("direita > esquerda (R)", int(v0[150, 380, 2]) > int(v0[150, 20, 2]))
# cima da vista ↔ latitude maior (G menor)
check("cima < baixo (G)", int(v0[10, 200, 1]) < int(v0[290, 200, 1]))
print("\noverall:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(1 if fails else 0)
