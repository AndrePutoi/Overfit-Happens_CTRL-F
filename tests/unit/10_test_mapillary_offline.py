"""Testes OFFLINE do ingest/mapillary_download.py (sem token, sem rede). Não substituem uma corrida real com token."""
from __future__ import annotations

import sys
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.ingest import mapillary_download as m  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")
    if not ok:
        fails.append(name)


# 1) Caixas da zona piloto de Aveiro e do Porto: todas as células < 0.01° de lado e cobrem a caixa toda
for nome, bb in (("aveiro", (-8.6560, 40.6405, -8.6440, 40.6460)), ("porto", (-8.616, 41.140, -8.604, 41.149))):
    cs = m.cells(bb)
    lados = max(max(c[2] - c[0], c[3] - c[1]) for c in cs)
    area = sum((c[2] - c[0]) * (c[3] - c[1]) for c in cs)
    check(f"cells {nome}", lados < 0.01 and abs(area - (bb[2] - bb[0]) * (bb[3] - bb[1])) < 1e-12,
          f"{len(cs)} células, lado máx {lados:.4f}°")
check("cells caixa pequena = 1 célula", len(m.cells((-8.65, 40.64, -8.645, 40.643))) == 1)

# 2) hfov: foco normalizado 0.8 pela maior dimensão, imagem horizontal 4:3 e 16:9
h43 = m.hfov_from_params({"camera_parameters": [0.8, 0, 0], "width": 4000, "height": 3000})
h169 = m.hfov_from_params({"camera_parameters": [0.8, 0, 0], "width": 3840, "height": 2160})
check("hfov horizontal (mesmo valor: normalizado pela largura)", h43 == h169 and 50 < h43 < 80, f"{h43}°")
check("hfov sem parâmetros -> None", m.hfov_from_params({}) is None)

# 3) tipo de câmara
check("fisheye ignorado", m.camera_type({"camera_type": "fisheye"}) is None)
check("pano -> equirectangular", m.camera_type({"is_pano": True, "camera_type": "perspective"}) == "equirectangular")
check("perspetiva", m.camera_type({"camera_type": "perspective"}) == "perspective")

# 4) conversão de metadados: usa as coordenadas/rumo calculados quando existem
it = {"id": 1, "geometry": {"coordinates": [-8.0, 40.0]}, "computed_geometry": {"coordinates": [-8.6, 40.6]},
      "compass_angle": 10, "computed_compass_angle": 95.5, "captured_at": 1700000000000,
      "camera_type": "perspective", "camera_parameters": [0.8, 0, 0], "width": 4000, "height": 3000, "quality_score": 0.7}
mt = m.to_meta(it, Path("x.jpg"))
check("to_meta usa computed_*", (mt.lat, mt.lon, mt.heading) == (40.6, -8.6, 95.5), f"{mt.lat},{mt.lon},{mt.heading}")
check("to_meta licença/atribuição", "CC BY-SA" in mt.license and "Mapillary" in mt.attribution)
check("to_meta extra", mt.extra["quality_score"] == 0.7 and mt.extra["hfov_from_camera_parameters"] is True)

# 5) token: nunca impresso; sem token devolve None (num ambiente limpo)
import os  # noqa: E402
old = os.environ.pop("MAPILLARY_TOKEN", None)
env = ROOT / ".env"
check("load_token sem env/.env -> None ou do .env", (m.load_token() is None) or env.exists())
if old:
    os.environ["MAPILLARY_TOKEN"] = old

print("\noverall:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(1 if fails else 0)
