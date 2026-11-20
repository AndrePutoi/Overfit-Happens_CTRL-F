"""Fase 4 da deduplicação: recomendar duplicados entre os ELEMENTOS do catálogo de Aveiro, agrupando com restrições e recalculando posições.

    python -m ctrlf.scripts.deduplicar [--cidade aveiro] [--tau-alto 0.85] [--tau-baixo 0.5] [--limite N]   ->  data/catalog/<cidade>/dedup_v2/

Passos: (1) pares candidatos de elementos (mesma família; sinais: mesma família de sinal e tipo igual ou `desconhecido`; <= 20 m entre observações representativas; câmaras e imagens diferentes);
(2) p(mesmo objeto) por par com o modelo final (models/dedup/pontuacao_p.joblib) sobre o par de observações representativas (as 2 melhores de cada elemento, por pontuação x lado);
(3) restrições duras: elementos que partilham uma imagem nunca se ligam; luz candeeiro+poste só com p >= 0,9; (4) ligação média (pipeline/dedup_cluster.py) a dois níveis:
`provavel` (média >= 0,85) e `possivel` (>= 0,5); (5) posição recalculada por grupo e, para todos os elementos, com a profundidade encolhida por k (pipeline/dedup_pos.py).
POLÍTICA: nada se funde sozinho; cada grupo sai com `recomendacao` e a evidência medida da sua família. Validação: a ronda 3 mediu pares de observações (AUC 0,897) e a ronda 4, por revisão humana de 356 pares de elementos, mediu o p ao nível do elemento (AUC 0,898; provável: sinais 79/80, contentores 34/35). Ver docs/09_deduplicacao.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from ctrlf.paths import ROOT
from ctrlf.pipeline import dedup_modelos as DM  # noqa: E402
from ctrlf.geometry.geometry import to_m  # noqa: E402
from ctrlf.pipeline import dedup_p as DP  # noqa: E402
from ctrlf.pipeline.dedup_cluster import agrupar  # noqa: E402
from ctrlf.pipeline.dedup_pos import posicao  # noqa: E402

CAT = ROOT / "data" / "catalog" / "aveiro"
GRUPO_LIMIARES = {"sinal": "sinais", "residuos": "contentores", "mobiliario": "bancos", "iluminacao": "luz"}


def carregar_limiares() -> dict:
    """models/dedup/limiares.json (scripts/calibrar_confianca_dedup.py): calibração da confiança e limiar automático por família. Sem o ficheiro: p cru e sem fusão automática."""
    f = Path(__import__("os").environ.get("UMS_MODELS_DIR", ROOT / "models")) / "dedup" / "limiares.json"
    return json.loads(f.read_text(encoding="utf-8"))["grupos"] if f.exists() else {}


def confianca(p: float, lim: dict) -> float:
    """p médio de ligação -> probabilidade calibrada de serem o mesmo objeto (contentores: a mesma ilha). Logística sobre logit(p); sem calibração, o próprio p."""
    c = (lim or {}).get("logistica")
    if not c:
        return round(float(p), 3)
    x = float(np.log(np.clip(p, 1e-3, 1 - 1e-3) / (1 - np.clip(p, 1e-3, 1 - 1e-3))))
    return round(float(1 / (1 + np.exp(-(c["a"] * x + c["b"])))), 3)
OUT = CAT / "dedup_v2"
RAIO_M = 20.0
MIN_OBS_K = 20                 # mínimo de observações triangulação para calibrar o k de posição na própria zona
K_POS_PADRAO = 0.40            # k calibrado em Aveiro (vistas Mapillary de 100°); a recalibrar com GPS noutra câmara/cidade
EVIDENCIA = {
    "sinal": "ronda 3 (pares novos): p >= 0,85 -> 25 de 25 certos (limite inferior do IC95 0,87); AUC 0,98",
    "residuos": "ronda 3: p >= 0,85 -> 10 de 11 certos (limite inferior 0,62); AUC 0,82; rever sempre",
    "mobiliario": "ronda 3: p >= 0,85 -> 3 de 4; n muito pequeno; AUC 0,88 (n = 15); rever sempre",
    "iluminacao": "ronda 4: 6 de 6 com p >= 0,85 (n muito pequeno); fusão automática ao mesmo limiar dos sinais por DECISÃO DO UTILIZADOR; desfazer se errar",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tau-alto", type=float, default=0.85)
    ap.add_argument("--tau-baixo", type=float, default=0.5)
    ap.add_argument("--limite", type=int, default=None, help="só os N primeiros pares (teste)")
    ap.add_argument("--cidade", default="aveiro", help="zona: lê data/catalog/<cidade>/ (omissão: aveiro)")
    ap.add_argument("--out", type=Path, default=None, help="omissão: data/catalog/<cidade>/dedup_v2")
    a = ap.parse_args()
    CAT = ROOT / "data" / "catalog" / a.cidade
    a.out = a.out or CAT / "dedup_v2"
    LIM = carregar_limiares()
    t0 = time.time()
    a.out.mkdir(parents=True, exist_ok=True)
    obs_l = DM.carregar(CAT)
    idx = {o["oid"]: i for i, o in enumerate(obs_l)}
    feats = {f["properties"]["id"]: f for f in json.loads((CAT / "catalog_ajustado.geojson").read_text(encoding="utf-8"))["features"]}
    raw = json.loads((CAT / "observacoes.json").read_text(encoding="utf-8"))
    ids = sorted(feats)
    eix = {e: i for i, e in enumerate(ids)}
    fam = {e: feats[e]["properties"]["family"] for e in ids}
    ncam = {e: len({(round(m["cam"][0], 6), round(m["cam"][1], 6)) for m in raw[e]}) for e in ids}
    imagens = {e: {m["image_id"] for m in raw[e]} for e in ids}
    sc = {}
    for e, ms in raw.items():
        for m in ms:
            x1, y1, x2, y2 = m["bbox"]
            sc.setdefault(f"{m['image_id']}|{round(x1)},{round(y1)},{round(x2)},{round(y2)}", m["score"])
    por_el = defaultdict(list)
    for o in obs_l:
        por_el[o["elem"]].append(o)

    def reps(e):
        L = sorted(por_el[e], key=lambda o: -sc.get(o["oid"], 0) * DP.lado(o))
        out = []
        for o in L:
            if all(o["cam_id"] != p["cam_id"] for p in out):
                out.append(o)
            if len(out) == 2:
                break
        return out
    R = {e: reps(e) for e in por_el}

    def valido(x, y):
        return x["cam_id"] != y["cam_id"] and x["image_id"] != y["image_id"] and np.hypot(*(x["cam_xy"] - y["cam_xy"])) >= 1.0 and np.hypot(*(x["xy"] - y["xy"])) <= RAIO_M

    # --- 1. pares candidatos
    cand = []
    for f in ("sinal", "residuos", "iluminacao", "mobiliario"):
        els = [e for e in R if fam[e] == f]
        pts, own = [], []
        for e in els:
            for o in R[e]:
                pts.append(o["xy"]); own.append(e)
        pr = set()
        if len(pts) < 2:                                       # família sem elementos (p. ex. zona pequena sem bancos): não há pares
            continue
        for x, y in cKDTree(np.array(pts)).query_pairs(RAIO_M):
            if own[x] != own[y]:
                pr.add((min(own[x], own[y]), max(own[x], own[y])))
        for ea, eb in sorted(pr):
            if f == "sinal":
                if raw[ea][0]["cls"] != raw[eb][0]["cls"]:
                    continue
                ta, tb = feats[ea]["properties"]["subclass"], feats[eb]["properties"]["subclass"]
                if ta != tb and ta != "desconhecido" and tb != "desconhecido":
                    continue
            par = next(((x, y) for x in R[ea] for y in R[eb] if valido(x, y)), None)
            if par:
                cand.append((ea, eb, par[0], par[1]))
    if a.limite:
        cand = cand[: a.limite]
    print(f"{len(ids)} elementos; {len(cand)} pares de elementos a pontuar ({time.time() - t0:.0f}s)", flush=True)

    # --- 2. pontuar (com cache retomável)
    cache_f = a.out / "pares_p.jsonl"
    feitos = {}
    if cache_f.exists():
        for l in cache_f.read_text(encoding="utf-8").splitlines():
            if l.strip():
                try:
                    d = json.loads(l); feitos[(d["a"], d["b"])] = d
                except Exception:
                    pass
    falta = [c for c in cand if (c[0], c[1]) not in feitos]
    print(f"{len(feitos)} em cache; {len(falta)} por pontuar", flush=True)
    if falta:
        modelo = DP.carregar_modelo()
        need = sorted({idx[c[2]["oid"]] for c in falta} | {idx[c[3]["oid"]] for c in falta})
        emb = DM.embeddings(obs_l, need)
        import torch
        M = DM.Eloftr("cuda" if torch.cuda.is_available() else "cpu")
        falta.sort(key=lambda c: c[2]["image_id"])                              # imagens seguidas: aproveita a cache de imagens
        with open(cache_f, "a", encoding="utf-8") as fo:
            for n, (ea, eb, oa, ob) in enumerate(falta, 1):
                try:
                    s = DM.pontuar(M, oa, ob)
                except Exception:
                    continue
                cos = float(emb[idx[oa["oid"]]] @ emb[idx[ob["oid"]]])
                p = float(DP.prever(modelo, [{"a": oa, "b": ob, "cos": cos, "inl": s["inl_obj"], "geo": 0, "fam": fam[ea], "nv_a": ncam[ea], "nv_b": ncam[eb]}])[0])
                fo.write(json.dumps({"a": ea, "b": eb, "fam": fam[ea], "p": round(p, 4), "cos": round(cos, 4), "inl": s["inl_obj"], "obs_a": oa["oid"], "obs_b": ob["oid"]}) + "\n")
                if n % 250 == 0:
                    fo.flush(); print(f"  {n}/{len(falta)} ({time.time() - t0:.0f}s)", flush=True)
        feitos = {}
        for l in cache_f.read_text(encoding="utf-8").splitlines():
            if l.strip():
                d = json.loads(l); feitos[(d["a"], d["b"])] = d
    print(f"pares pontuados: {len(feitos)} ({time.time() - t0:.0f}s)", flush=True)

    # --- 3. restrições e arestas
    arestas, extra = {}, {}
    for (ea, eb), d in feitos.items():
        p = d["p"]
        if fam[ea] == "iluminacao" and feats[ea]["properties"]["class"] != feats[eb]["properties"]["class"] and p < 0.9:
            continue
        if p >= 0.1:
            arestas[(eix[ea], eix[eb])] = p
            extra[(eix[ea], eix[eb])] = d
    por_img = defaultdict(list)
    for e in ids:
        for im in imagens[e]:
            por_img[im].append(eix[e])
    proibidos = set()
    for im, L in por_img.items():
        for i in range(len(L)):
            for j in range(i + 1, len(L)):
                if L[i] != L[j] and fam[ids[L[i]]] == fam[ids[L[j]]]:
                    proibidos.add((min(L[i], L[j]), max(L[i], L[j])))
    print(f"{len(arestas)} arestas (p >= 0,1); {len(proibidos)} pares proibidos (partilham imagem)", flush=True)

    # --- 4. agrupar a dois níveis
    lv_hi, lv_lo = agrupar(len(ids), arestas, proibidos, [a.tau_alto, a.tau_baixo])

    def grupos_de(rot):
        g = defaultdict(list)
        for i, r in enumerate(rot):
            g[r].append(i)
        return [m for m in g.values() if len(m) > 1]
    G_hi, G_lo = grupos_de(lv_hi), grupos_de(lv_lo)
    chave_hi = {tuple(sorted(m)) for m in G_hi}

    # --- 5. posições
    ks = []
    for e in ids:
        if feats[e]["properties"]["geo_method"] == "triangulado":
            po = feats[e]["properties"]["pos_original"]; P = to_m(*po)
            for m in raw[e]:
                c = to_m(*m["cam"]); az = np.radians(m["az"]); u = np.array([np.sin(az), np.cos(az)])
                ks.append(float((P - (c + m["dist_m"] * u)) @ u) / m["dist_m"])
    if len(ks) >= MIN_OBS_K:
        k_pos = float(1 + np.median(ks))
        k_origem = f"calibrado em {len(ks)} observações de elementos triangulados desta zona"
    else:                                              # zona pequena: sem triangulações a mediana seria NaN e contaminava todas as posições
        k_pos = K_POS_PADRAO
        k_origem = f"PADRÃO de Aveiro ({K_POS_PADRAO}): só {len(ks)} observações trianguladas nesta zona (mínimo {MIN_OBS_K})"
    assert np.isfinite(k_pos), "k_pos não finito"
    print(f"k_pos (posição) = {k_pos:.3f} ({k_origem}); k da pontuação = {DP.K_PAR}", flush=True)

    def pos_el(e):
        p = feats[e]["properties"]
        if p["geo_method"] == "triangulado":
            lat, lon = p["pos_original"]
            return {"lat": lat, "lon": lon, "sigma_m": None, "metodo": "triangulada_catalogo", "n_cam": ncam[e]}
        return posicao(raw[e], k_pos)

    def xy_cat(e):
        c = feats[e]["geometry"]["coordinates"]
        return to_m(c[1], c[0])

    def descrever(membros, nivel):
        els = [ids[i] for i in membros]
        pares = [(i, j) for i in membros for j in membros if i < j]
        ps = [arestas.get(k, 0.0) for k in pares]
        com = [arestas[k] for k in pares if k in arestas]
        f = fam[els[0]]
        tipos = Counter(feats[e]["properties"]["subclass"] for e in els if feats[e]["properties"]["subclass"])
        pf = posicao([m for e in els for m in raw[e]], k_pos)
        dist = max((float(np.hypot(*(xy_cat(x) - xy_cat(y)))) for x in els for y in els if x < y), default=0.0)
        manter = max(els, key=lambda e: (ncam[e], feats[e]["properties"]["confidence"]))
        rec = ("Recomendado: duplicado (alta confiança). " if nivel == "provavel" else "Possível duplicado: rever. ") + f"p médio de ligação {np.mean(ps):.2f}."
        return {"elementos": els, "familia": f, "nivel": nivel, "n": len(els), "p_medio_ligacao": round(float(np.mean(ps)), 3), "p_min_aresta": round(float(min(com)), 3) if com else None,
                "arestas_com_p": len(com), "pares_total": len(pares), "tipos": dict(tipos), "classes": dict(Counter(feats[e]["properties"]["class"] for e in els)), "distancia_max_catalogo_m": round(dist, 1),
                "manter_sugerido": manter, "posicao_fundida": {k: (round(v, 7) if k in ("lat", "lon") else v) for k, v in pf.items()},
                "confianca": confianca(float(np.mean(ps)), LIM.get(GRUPO_LIMIARES[f])),
                "limiar_automatico_p": (LIM.get(GRUPO_LIMIARES[f]) or {}).get("limiar_automatico_p"),
                "auto_merge": bool(nivel == "provavel" and (LIM.get(GRUPO_LIMIARES[f]) or {}).get("fusao_automatica") and (LIM.get(GRUPO_LIMIARES[f]) or {}).get("limiar_automatico_p") is not None
                                   and float(np.mean(ps)) >= (LIM.get(GRUPO_LIMIARES[f]) or {}).get("limiar_automatico_p")),
                "fusao_automatica": False,
                "recomendacao": rec + (" Condição de sinais cumprida: mesma família e tipo." if f == "sinal" and nivel == "provavel" else ""), "evidencia_da_familia": EVIDENCIA[f]}
    grupos = [descrever(m, "provavel") for m in G_hi] + [descrever(m, "possivel") for m in G_lo if tuple(sorted(m)) not in chave_hi]
    for n, g in enumerate(grupos, 1):
        g["grupo_id"] = f"dup2-{n:04d}"
    gid = {}
    for g in grupos:
        for e in g["elementos"]:
            if e not in gid or g["nivel"] == "provavel":
                gid[e] = (g["grupo_id"], g["nivel"])
    # --- 6. saídas
    out_feats = []
    for e in ids:
        pe = pos_el(e)
        p = dict(feats[e]["properties"])
        p.update({"position_original": feats[e]["geometry"]["coordinates"][::-1], "position_method_v2": pe["metodo"], "position_sigma_m": None if pe["sigma_m"] is None else round(pe["sigma_m"], 1),
                  "duplicate_group_v2": gid.get(e, (None, None))[0], "duplicate_level_v2": gid.get(e, (None, None))[1]})
        out_feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [round(pe["lon"], 7), round(pe["lat"], 7)]}, "properties": p})
    (a.out / "elementos.geojson").write_text(json.dumps({"type": "FeatureCollection", "features": out_feats}, ensure_ascii=False), encoding="utf-8")
    (a.out / "grupos.json").write_text(json.dumps({"politica": "nada se funde sozinho; recomendações", "tau_alto": a.tau_alto, "tau_baixo": a.tau_baixo, "k_pontuacao": DP.K_PAR, "k_posicao": round(k_pos, 3), "grupos": grupos}, ensure_ascii=False), encoding="utf-8")
    res = {"elementos": len(ids), "pares_pontuados": len(feitos), "arestas": len(arestas), "proibidos": len(proibidos), "k_posicao": round(k_pos, 3), "k_posicao_origem": k_origem, "segundos": round(time.time() - t0)}
    for nivel in ("provavel", "possivel"):
        gs = [g for g in grupos if g["nivel"] == nivel]
        res[nivel] = {"grupos": len(gs), "elementos_envolvidos": sum(g["n"] for g in gs), "reducao_se_fundir": sum(g["n"] - 1 for g in gs), "tamanho_max": max((g["n"] for g in gs), default=0),
                      "tamanhos": dict(Counter(g["n"] for g in gs)), "por_familia": {f: {"grupos": sum(1 for g in gs if g["familia"] == f), "reducao": sum(g["n"] - 1 for g in gs if g["familia"] == f)} for f in ("sinal", "residuos", "iluminacao", "mobiliario")}}
    res["elementos_por_familia"] = dict(Counter(fam.values()))
    (a.out / "resumo.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1), flush=True)


if __name__ == "__main__":
    main()
