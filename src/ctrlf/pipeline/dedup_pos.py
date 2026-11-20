"""Posição de um elemento a partir das suas observações, com a profundidade encolhida por k e uma incerteza σ.

  triangulada  >= 2 posições de câmara com semirretas que se cruzam com ângulo >= MIN_ANG: mínimos quadrados ponderados (1/σ_lat²), o ponto tem de ficar à frente das câmaras e a <= 60 m
  vista única  caso contrário: média ponderada (1/σ²) das posições câmara + k·d·u
`k` mede-se nos elementos triangulados (desvio mediano da profundidade monocular face à triangulação, scripts/sigma_posicao.py); não foi validado com GPS no terreno.
"""
from __future__ import annotations

import numpy as np

from ctrlf.pipeline.dedup_p import A_M, B_REL, TAN_AZ, sigma
from ctrlf.geometry.geometry import to_deg, to_m

MIN_ANG = 8.0
MAX_RANGE = 60.0
MAX_SIGMA = 15.0


def _u(az: float) -> np.ndarray:
    a = np.radians(az)
    return np.array([np.sin(a), np.cos(a)])


def posicao(obs: list[dict], k: float) -> dict:
    """obs: {cam:[lat,lon], az, dist_m}. -> {lat, lon, sigma_m, metodo, n_cam}."""
    C = [to_m(*o["cam"]) for o in obs]
    U = [_u(o["az"]) for o in obs]
    D = [o["dist_m"] for o in obs]
    cams = {(round(o["cam"][0], 6), round(o["cam"][1], 6)) for o in obs}
    # triangulação
    if len(cams) >= 2:
        ang = max((abs((obs[i]["az"] - obs[j]["az"] + 180) % 360 - 180) for i in range(len(obs)) for j in range(i + 1, len(obs)) if np.hypot(*(C[i] - C[j])) >= 1.0), default=0.0)
        if ang >= MIN_ANG:
            Aq, bq, W = np.zeros((2, 2)), np.zeros(2), 0.0
            for c, u, d in zip(C, U, D):
                n = np.array([u[1], -u[0]])
                w = 1.0 / max(d * TAN_AZ, 1.0) ** 2
                M = w * np.outer(n, n)
                Aq += M; bq += M @ c
            try:
                P = np.linalg.solve(Aq, bq)
                frente = all(((P - c) @ u) > 0 and np.hypot(*(P - c)) <= MAX_RANGE for c, u in zip(C, U))
                sg = float(np.sqrt(np.trace(np.linalg.inv(Aq))))
                if frente and sg <= MAX_SIGMA:                           # semirretas quase paralelas dão σ enorme: não vale a pena triangular
                    lat, lon = to_deg(P)
                    return {"lat": lat, "lon": lon, "sigma_m": sg, "metodo": "triangulada", "n_cam": len(cams)}
            except np.linalg.LinAlgError:
                pass
    w = np.array([1.0 / sigma(d, k) ** 2 for d in D])
    pts = np.array([c + k * d * u for c, u, d in zip(C, U, D)])
    P = (pts * w[:, None]).sum(0) / w.sum()
    lat, lon = to_deg(P)
    return {"lat": lat, "lon": lon, "sigma_m": float(1.0 / np.sqrt(w.sum())), "metodo": "vista_unica_k", "n_cam": len(cams)}
