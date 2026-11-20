"""Deduplicação entre imagens/fontes (secção 8, "Entre imagens e fontes").

Versão Python (scikit-learn) para prototipar e medir.  A versão final pode passar
para SQL com ST_ClusterDBSCAN; os parâmetros por classe são os mesmos.

Autoteste:  python -m ctrlf.pipeline.dedup
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from sklearn.cluster import DBSCAN, AgglomerativeClustering

# Raio de agrupamento em metros, por classe do detetor.  Afinar com os dados reais.
EPS_M = {"sinal": 1.5, "candeeiro": 2.5, "poste": 2.5, "contentor": 2.0}
EMB_COS_THRESHOLD = 0.35   # distância cosseno acima da qual dois recortes são "diferentes"
AZ_MAX_DIFF_DEG = 60.0     # ângulos de vista muito diferentes não obrigam a embeddings parecidos


@dataclass
class Obs:
    cls: str
    xy: np.ndarray                  # metros (EPSG:3763)
    embedding: np.ndarray | None = None
    score: float = 1.0


def cluster(obs: list[Obs], eps_scale: float = 1.0) -> np.ndarray:
    """Devolve um id de grupo por observação (-1 nunca aparece: min_samples=1).

    `eps_scale` > 1 alarga os raios: usar ~2-3 quando as posições vêm de vista única
    (erro de vários metros) e 1 quando já vêm trianguladas."""
    labels = np.full(len(obs), -1, int)
    next_id = 0
    for cls in sorted({o.cls for o in obs}):
        idx = [i for i, o in enumerate(obs) if o.cls == cls]
        pts = np.array([obs[i].xy for i in idx])
        sp = DBSCAN(eps=EPS_M.get(cls, 2.0) * eps_scale, min_samples=1).fit_predict(pts)
        for g in np.unique(sp):
            members = [idx[k] for k in np.where(sp == g)[0]]
            embs = [obs[i].embedding for i in members]
            if len(members) > 1 and all(e is not None for e in embs):
                E = np.array(embs, float)
                E /= np.linalg.norm(E, axis=1, keepdims=True)
                sub = AgglomerativeClustering(
                    n_clusters=None, metric="cosine", linkage="average",
                    distance_threshold=EMB_COS_THRESHOLD).fit_predict(E)
            else:
                sub = np.zeros(len(members), int)
            for s in np.unique(sub):
                for k in np.where(sub == s)[0]:
                    labels[members[k]] = next_id
                next_id += 1
    return labels


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    # 3 candeeiros reais, a ~8 m uns dos outros; cada um visto 4 vezes com 0.7 m de ruído.
    truth = np.array([[0.0, 0.0], [8.0, 0.5], [16.0, -0.3]])
    proto = rng.normal(size=(3, 384))            # "aparência" de cada candeeiro
    obs, gt = [], []
    for k, c in enumerate(truth):
        for _ in range(4):
            obs.append(Obs("candeeiro", c + rng.normal(0, 0.7, 2),
                           proto[k] + rng.normal(0, 0.1, 384)))
            gt.append(k)
    # dois sinais na mesma haste (0.4 m): devem ficar separados pela aparência
    sa, sb = rng.normal(size=384), rng.normal(size=384)
    for _ in range(3):
        obs.append(Obs("sinal", np.array([30.0, 0.0]) + rng.normal(0, 0.1, 2), sa + rng.normal(0, .1, 384))); gt.append(10)
        obs.append(Obs("sinal", np.array([30.3, 0.3]) + rng.normal(0, 0.1, 2), sb + rng.normal(0, .1, 384))); gt.append(11)

    lab = cluster(obs)
    n_groups = len(set(lab))
    print(f"{len(obs)} observações -> {n_groups} elementos (esperado 5)")
    assert n_groups == 5, lab
    print("dedup.py OK")
