"""Autoteste de pipeline/avaliar_posicao.py com dados sintéticos (sem ficheiros)."""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.pipeline import avaliar_posicao as a  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")
    if not ok:
        fails.append(name)


# 1) erro de uma observação: câmara na origem, ecoponto a 10 m a norte; estimado com 10° de rumo a mais e 16 m
r = a.obs_error(np.array([0.0, 0.0]), 10.0, 16.0, np.array([0.0, 10.0]))
check("erro de rumo +10°", abs(r["daz"] - 10) < 1e-9, f"{r['daz']:.2f}")
check("razão de distância 1,6", abs(r["ratio"] - 1.6) < 1e-9)
check("erro lateral = 10*sin(10°)", abs(r["lateral"] - 10 * math.sin(math.radians(10))) < 1e-9, f"{r['lateral']:.2f}")
check("erro ao longo = 16-10*cos(10°)", abs(r["ao_longo"] - (16 - 10 * math.cos(math.radians(10)))) < 1e-9, f"{r['ao_longo']:.2f}")
r2 = a.obs_error(np.array([0.0, 0.0]), 350.0, 10.0, np.array([0.0, 10.0]))
check("rumo com volta (350 vs 0 = -10°)", abs(r2["daz"] + 10) < 1e-9, f"{r2['daz']:.2f}")
check("muito perto -> None", a.obs_error(np.array([0.0, 0.0]), 0, 5, np.array([1.0, 1.0])) is None)

# 2) emparelhamento 1-1: dois elementos, dois refs; o cruzado seria pior
E = np.array([[0.0, 0.0], [20.0, 0.0]])
R = np.array([[19.0, 1.0], [1.0, 0.0]])
p = a.match_pairs(E, R, 40)
check("1-1 ótimo", sorted((i, j) for i, j, _ in p) == [(0, 1), (1, 0)], str(p))
check("gate recusa pares longos", a.match_pairs(np.array([[0.0, 0.0]]), np.array([[100.0, 0.0]]), 40) == [])

# 3) curvas
c = a.curves(np.array([[0.0, 0.0], [0.0, 30.0]]), np.array([[0.0, 4.0]]))
check("curvas: 1 de 2 a <=5 m, 1 de 2 a <=25 m", c["<=5m"] == 0.5 and c["<=25m"] == 0.5, str(c))

# 4) avaliação completa: 2 elementos, 2 refs, 1 observação com distância 1,5x
els = [{"id": "e1", "xy": np.array([0.0, 12.0]), "cls": "contentor", "geo_method": "vista_unica_profundidade", "n_views": 1, "lat": 0, "lon": 0},
       {"id": "e2", "xy": np.array([200.0, 0.0]), "cls": "subterraneo", "geo_method": "triangulado", "n_views": 2, "lat": 0, "lon": 0}]
refs = [{"id": 1, "xy": np.array([0.0, 10.0]), "lat": 0, "lon": 0, "loc": "overground"},
        {"id": 2, "xy": np.array([201.0, 0.0]), "lat": 0, "lon": 0, "loc": "underground"}]
obs = {"e1": [{"cam_xy": np.array([0.0, 0.0]), "az": 0.0, "dist_m": 15.0}]}
res = a.evaluate_from(els, obs, refs, [{"xy": np.array([200.5, 0.0])}], gate=40)
check("pares 1-1 = 2", res["pares_1a1"]["n"] == 2)
check("precisão <=5 m = 100%", res["precisao_proxy"]["<=5m"] == 1.0, str(res["precisao_proxy"]))
check("razão de distância mediana 1,5", abs(res["por_observacao"]["razao_distancia"]["p50"] - 1.5) < 1e-6, str(res["por_observacao"]["razao_distancia"]))
check("subterrâneo piloto encontrado", res["subterraneos_piloto"]["elemento_subterraneo"]["<=5m"] == 1.0)
check("ref OSM subterrâneo encontrado", res["ref_osm_subterraneos"]["elemento_subterraneo"]["<=5m"] == 1.0)

print("\noverall:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(1 if fails else 0)
