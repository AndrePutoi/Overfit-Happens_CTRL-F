"""Pontuação p(mesmo objeto) entre duas observações: aparência (cosseno DINOv2, inliers do EfficientLoFTR dentro do objeto) + geometria com a profundidade encolhida por k.

Modelo = regressão logística (padronizada) sobre as características `+vistas` validadas nas rondas 2 e 3 (AUC 0,897 em pares novos, ronda 3). Treino: scripts/treinar_pontuacao_dedup.py.
`obs` = dicts de scripts/gerar_pares_duplicados.carregar (cam_xy, az, dist, bbox, elem...). Sem dependências do resto do projeto além de numpy/sklearn.
Escala k: a profundidade monocular parece sobrestimar a distância (desvio mediano de -0,6·d face à triangulação, `scripts/sigma_posicao.py`); K_PAR = 0,3 foi o ótimo da deduplicação.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
K_PAR = 0.3
_SIG = next(p for p in (ROOT / "configs" / "sigma_posicao.json", ROOT / "reports" / "sigma_posicao.json") if p.exists())          # configs/: vai no pacote; reports/: gerado por scripts/sigma_posicao.py
_S = json.loads(_SIG.read_text(encoding="utf-8"))
A_M, B_REL, TAN_AZ = _S["modelo_along"]["a_m"], _S["modelo_along"]["b"], float(np.tan(np.radians(_S["sigma_az_graus"])))
FAMILIAS_DUM = ("residuos", "sinal", "mobiliario")


def sigma(d: float, k: float = 1.0) -> float:
    """σ (m) da posição de vista única para profundidade estimada d, com distância encolhida por k."""
    dd = k * d
    return float(np.hypot(A_M + B_REL * dd, dd * TAN_AZ))


def pos_vista_unica(o: dict, k: float) -> np.ndarray:
    az = np.radians(o["az"])
    return o["cam_xy"] + k * o["dist"] * np.array([np.sin(az), np.cos(az)])


def geo(a: dict, b: dict, k: float = K_PAR) -> tuple[float, float, float, float]:
    """-> (distância entre posições, distância/σ, σ do par, diferença de rumo em graus)."""
    dist = float(np.hypot(*(pos_vista_unica(a, k) - pos_vista_unica(b, k))))
    sp = float(np.hypot(sigma(a["dist"], k), sigma(b["dist"], k)))
    return dist, dist / sp, sp, abs((a["az"] - b["az"] + 180) % 360 - 180)


def lado(o: dict) -> float:
    return min(o["bbox"][2] - o["bbox"][0], o["bbox"][3] - o["bbox"][1])


def X(rows: list[dict]) -> np.ndarray:
    """rows: {a, b (obs), cos, inl, geo (0/1: o catálogo diz mesmo elemento), fam, nv_a, nv_b}."""
    G = np.array([geo(r["a"], r["b"]) for r in rows])
    fam = np.array([r["fam"] for r in rows])
    dum = np.c_[[fam == f for f in FAMILIAS_DUM]].T.astype(float)
    dmed = np.log(0.5 * np.array([r["a"]["dist"] + r["b"]["dist"] for r in rows]) + 1)
    nv = np.array([[r["nv_a"], r["nv_b"]] for r in rows], float)
    lmin = np.log(np.array([min(lado(r["a"]), lado(r["b"])) for r in rows]))
    return np.c_[[r["cos"] for r in rows], np.log1p([r["inl"] for r in rows]), np.log1p(G[:, 0]), G[:, 1], dmed, np.log1p(G[:, 3]), [r["geo"] for r in rows], dum, nv.min(1), nv.max(1), lmin]


def carregar_modelo(path: Path | None = None):
    import joblib
    return joblib.load(path or Path(os.environ.get("UMS_MODELS_DIR", ROOT / "models")) / "dedup" / "pontuacao_p.joblib")


def prever(modelo, rows: list[dict]) -> np.ndarray:
    return modelo.predict_proba(X(rows))[:, 1]
