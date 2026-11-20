"""Associação de observações do MESMO objeto entre panoramas por geometria dos raios (em vez de agrupar posições de vista única).

Problema: a posição de vista única (azimute + distância por profundidade) tem erro de vários metros; agrupar essas posições
(DBSCAN) junta objetos diferentes ou deixa o mesmo objeto repetido.  Aqui usa-se o que é fiável: o AZIMUTE de cada observação
(a distância só serve de verificação grosseira).

Algoritmo  (todas as observações são de UM balde: mesmo tipo de sinal, ou todos os contentores):
 1. Para cada par de observações de posições de câmara diferentes calcula-se onde os dois raios se cruzam.  O par é válido se
    o cruzamento fica à frente das duas câmaras, a <= max_range, com ângulo >= min_angle e com distâncias coerentes com a
    profundidade estimada (|t - d| <= max(depth_abs, depth_rel * d)).
 2. Os cruzamentos válidos agrupam-se (DBSCAN, eps m): cada grupo é um OBJETO candidato.
 3. Cada observação junta-se ao candidato mais próximo do seu raio (distância perpendicular <= perp_tol), os candidatos
    reajustam-se por mínimos quadrados e os que ficam com < 2 posições de câmara desfazem-se.
 4. O que sobra (vistas únicas) agrupa-se por posição de vista única, como antes, e junta-se a um candidato confirmado se o
    seu raio passa a <= perp_tol dele.

Devolve um id de grupo por observação e, por grupo, se foi CONFIRMADO por >= 2 posições de câmara.
Autoteste: python -m ctrlf.pipeline.assoc_rays
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN


@dataclass
class Params:
    max_range: float = 40.0
    min_angle: float = 8.0           # graus entre raios
    min_cam_sep: float = 1.0         # m entre câmaras (mesma posição = vistas do mesmo panorama)
    depth_abs: float = 6.0           # m: tolerância absoluta à distância por profundidade
    depth_rel: float = 0.45          # ... ou relativa
    eps: float = 3.0                 # m: DBSCAN dos cruzamentos
    perp_tol: float = 3.0            # m: distância raio-objeto para pertencer
    single_eps: float = 3.75         # m: agrupar vistas únicas pela posição (como o dedup original)


def _cross(a, b):
    return a[..., 0] * b[..., 1] - a[..., 1] * b[..., 0]


def intersections(origin: np.ndarray, d: np.ndarray, dist: np.ndarray, cam: np.ndarray, p: Params):
    """-> (i, j, pontos[k,2]) dos pares válidos.  origin[n,2], d[n,2] unitários, dist[n] estimada, cam[n] id da posição."""
    n = len(origin)
    O_i, O_j = origin[:, None, :], origin[None, :, :]
    D_i, D_j = d[:, None, :], d[None, :, :]
    den = _cross(D_i, D_j)                                   # sin(ângulo)
    diff = O_j - O_i
    with np.errstate(divide="ignore", invalid="ignore"):
        t_i = _cross(diff, D_j) / den
        t_j = _cross(diff, D_i) / den
    ang = np.degrees(np.arcsin(np.clip(np.abs(den), 0, 1)))
    sep = np.linalg.norm(diff, axis=-1)
    tol_i = np.maximum(p.depth_abs, p.depth_rel * dist)[:, None]
    tol_j = np.maximum(p.depth_abs, p.depth_rel * dist)[None, :]
    ok = ((t_i > 0) & (t_j > 0) & (t_i <= p.max_range) & (t_j <= p.max_range) & (ang >= p.min_angle) & (sep >= p.min_cam_sep)
          & (cam[:, None] != cam[None, :]) & (np.abs(t_i - dist[:, None]) <= tol_i) & (np.abs(t_j - dist[None, :]) <= tol_j))
    ok &= np.triu(np.ones((n, n), bool), 1)
    i, j = np.where(ok)
    pts = origin[i] + t_i[i, j][:, None] * d[i]
    return i, j, pts


def _perp(origin, d, c):
    v = c[None, :] - origin
    return np.abs(_cross(v, d)), np.einsum("ij,ij->i", v, d)       # distância perpendicular, projeção ao longo do raio


def _lsq(origin, d, idx):
    A, b = np.zeros((2, 2)), np.zeros(2)
    for k in idx:
        P = np.eye(2) - np.outer(d[k], d[k]); A += P; b += P @ origin[k]
    return np.linalg.solve(A + 1e-9 * np.eye(2), b)


def associate(origin: np.ndarray, az_deg: np.ndarray, dist: np.ndarray, cam: np.ndarray, single_xy: np.ndarray,
              p: Params | None = None):
    """-> (labels[n], confirmed{label: bool}).  `cam` = id inteiro da posição de câmara de cada observação."""
    p = p or Params()
    n = len(origin)
    az = np.radians(az_deg)
    d = np.stack([np.sin(az), np.cos(az)], 1)
    labels = np.full(n, -1, int)
    confirmed: dict[int, bool] = {}
    nxt = 0
    if n >= 2:
        i, j, pts = intersections(origin, d, dist, cam, p)
        if len(pts):
            cl = DBSCAN(eps=p.eps, min_samples=1).fit_predict(pts)
            centers = [pts[cl == g].mean(0) for g in np.unique(cl)]
            # candidatos por suporte decrescente (nº de posições de câmara cujos raios os atravessam)
            def support(c):
                pd, t = _perp(origin, d, c)
                tol = np.maximum(p.depth_abs, p.depth_rel * dist)
                m = (pd <= p.perp_tol) & (t > 0) & (t <= p.max_range) & (np.abs(t - dist) <= tol)
                return m, pd
            order = sorted(range(len(centers)), key=lambda g: -len(set(cam[support(centers[g])[0]])))
            for g in order:
                c = centers[g]
                for _ in range(2):                                      # reajusta 1x com os membros
                    m, pd = support(c)
                    free = m & (labels < 0)
                    if len(set(cam[free])) < 2:
                        break
                    c = _lsq(origin, d, np.where(free)[0])
                m, pd = support(c)
                free = m & (labels < 0)
                if len(set(cam[free])) >= 2:
                    # uma observação por posição de câmara mais próxima do raio; as outras vistas do mesmo panorama também entram
                    labels[free] = nxt
                    confirmed[nxt] = True
                    centers[g] = c
                    nxt += 1
    # vistas únicas: agrupar pela posição de vista única e juntar a candidatos confirmados cujo raio passa perto
    rest = np.where(labels < 0)[0]
    if len(rest):
        cen = {g: _lsq(origin, d, np.where(labels == g)[0]) for g in confirmed}
        for k in rest:
            best, bd = None, p.perp_tol
            for g, c in cen.items():
                pd, t = _perp(origin[k:k + 1], d[k:k + 1], c)
                if pd[0] <= bd and 0 < t[0] <= p.max_range:
                    best, bd = g, pd[0]
            if best is not None:
                labels[k] = best
        rest = np.where(labels < 0)[0]
        if len(rest):
            sp = DBSCAN(eps=p.single_eps, min_samples=1).fit_predict(single_xy[rest])
            for g in np.unique(sp):
                labels[rest[sp == g]] = nxt
                confirmed[nxt] = len(set(cam[rest[sp == g]])) >= 2
                nxt += 1
    return labels, confirmed


# ------------------------------------------------------------------ autoteste
if __name__ == "__main__":
    rng = np.random.default_rng(1)
    objs = np.array([[0.0, 12.0], [14.0, 15.0], [-9.0, 20.0], [30.0, 10.0]])          # 4 objetos reais
    O, A, D, C, S, truth = [], [], [], [], [], []
    for cid, x in enumerate(np.arange(-20, 40, 4.5)):                                  # câmaras ao longo de uma rua
        for k, ob in enumerate(objs):
            v = ob - np.array([x, 0.0]); r = np.hypot(*v)
            if r > 28:
                continue
            az = math.degrees(math.atan2(v[0], v[1])) + rng.normal(0, 2.5)             # erro de rumo 2,5 graus
            dist = r * rng.uniform(0.75, 1.3)                                          # profundidade com erro de 30%
            O.append([x, 0.0]); A.append(az); D.append(dist); C.append(cid); truth.append(k)
            a = math.radians(az); S.append([x, 0.0] + dist * np.array([math.sin(a), math.cos(a)]))
    lab, conf = associate(np.array(O), np.array(A), np.array(D), np.array(C), np.array(S))
    truth = np.array(truth)
    print(f"{len(truth)} observações de {len(objs)} objetos -> {len(set(lab))} grupos ({sum(conf.values())} confirmados)")
    purity = sum(np.bincount(truth[lab == g]).max() for g in set(lab)) / len(truth)
    frag = {k: len(set(lab[truth == k])) for k in range(len(objs))}
    print(f"pureza {purity:.0%} | grupos por objeto real: {frag}")
