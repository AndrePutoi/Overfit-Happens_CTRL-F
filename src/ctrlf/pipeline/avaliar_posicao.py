"""Mede o ERRO DE POSIÇÃO do catálogo em metros, contra o OpenStreetMap, e separa o erro em distância e rumo.

    python -m ctrlf.pipeline.avaliar_posicao aveiro            # -> reports/posicao/aveiro.json + .md
    python -m ctrlf.pipeline.avaliar_posicao aveiro --gate 30

Verdade-terreno usada: ecopontos do OSM (data/reference/osm_<cidade>_reciclagem.geojson, sem as máquinas de reembolso) e, em
Aveiro, os 4 subterrâneos da zona piloto. É uma verdade APROXIMADA: o OSM guarda um ponto por ilha (não por contentor), pode
estar desatualizado e tem uns metros de erro. Serve para ordens de grandeza e para comparar métodos, não para um erro absoluto.

O que mede
  * curvas por elemento: fração dos elementos detetados com um ecoponto OSM a <= r m (proxy de PRECISÃO) e fração dos
    ecopontos OSM com um elemento a <= r m (RECOLHA), para r = 5, 10, 15, 25 m. Não dependem de nenhum emparelhamento.
  * emparelhamento 1-para-1 ótimo (húngaro) dentro de --gate m: erro mediano/IQR/p90 dos pares. TRUNCADO pelo gate: o que
    ficou fora do gate não entra (ver "sem par").
  * por método (vista única vs triangulado) e por nº de vistas.
  * por OBSERVAÇÃO (nos elementos emparelhados): o raio da câmara até ao objeto estimado é comparado com a posição OSM:
        erro de rumo      = azimute estimado - rumo câmara->OSM          (graus, com sinal)
        razão de distância = distância estimada / distância câmara->OSM  (1 = certa; > 1 = posto longe demais)
        erro lateral       = distância do ponto OSM ao raio (m)           ~ d_real * sin(erro de rumo)
        erro ao longo      = dist. estimada - projeção do ponto OSM no raio (m, + = longe demais)
    Isto diz se o erro vem sobretudo da DISTÂNCIA (profundidade) ou do RUMO (heading/hfov/yaw). Como só entram elementos
    emparelhados, subestima o erro dos que falharam por completo.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.geometry.geometry import to_m  # noqa: E402

RADII = (5, 10, 15, 25)
PILOT = (-8.6560, 40.6405, -8.6440, 40.6460)          # minLon, minLat, maxLon, maxLat
UNDER = ("underground", "partially_underground")


# ------------------------------------------------------------------ peças puras (testáveis)
def pct(a, qs=(25, 50, 75, 90)):
    return {f"p{q}": round(float(np.percentile(a, q)), 2) for q in qs} if len(a) else {}


def obs_error(cam_xy: np.ndarray, az_deg: float, dist_m: float, ref_xy: np.ndarray) -> dict | None:
    """Decompõe o erro de UMA observação face à posição de referência (todas em metros, sistema métrico local)."""
    v = ref_xy - cam_xy
    dt = float(np.hypot(*v))
    if dt < 3.0:                                        # demasiado perto: o rumo não é definido
        return None
    bt = math.degrees(math.atan2(v[0], v[1])) % 360
    daz = ((az_deg - bt + 180) % 360) - 180
    return {"daz": daz, "ratio": dist_m / dt, "lateral": dt * math.sin(math.radians(daz)),
            "ao_longo": dist_m - dt * math.cos(math.radians(daz)), "d_real": dt}


def match_pairs(elem_xy: np.ndarray, ref_xy: np.ndarray, gate: float) -> list[tuple[int, int, float]]:
    """Emparelhamento 1-1 ótimo (soma das distâncias mínima), só pares a <= gate m. -> [(i_elem, j_ref, dist_m)]."""
    if not len(elem_xy) or not len(ref_xy):
        return []
    d = np.hypot(elem_xy[:, None, 0] - ref_xy[None, :, 0], elem_xy[:, None, 1] - ref_xy[None, :, 1])
    cost = np.where(d <= gate, d, 1e6)
    ii, jj = linear_sum_assignment(cost)
    return [(int(i), int(j), float(d[i, j])) for i, j in zip(ii, jj) if d[i, j] <= gate]


def curves(a_xy: np.ndarray, b_xy: np.ndarray) -> dict:
    """Fração dos pontos de `a` com algum ponto de `b` a <= r m (para cada r) e a distância mediana ao mais próximo."""
    if not len(a_xy):
        return {"n": 0}
    if not len(b_xy):
        return {"n": len(a_xy), **{f"<={r}m": 0.0 for r in RADII}}
    d = np.hypot(a_xy[:, None, 0] - b_xy[None, :, 0], a_xy[:, None, 1] - b_xy[None, :, 1]).min(axis=1)
    return {"n": int(len(a_xy)), **{f"<={r}m": round(float((d <= r).mean()), 3) for r in RADII},
            "mais_proximo_mediano_m": round(float(np.median(d)), 1)}


def evaluate_from(elements: list[dict], obs: dict, refs: list[dict], pilot_pts: list[dict], gate: float = 40.0) -> dict:
    """elements: {id, xy, cls, geo_method, n_views, lat, lon}; refs: {id, xy, lat, lon, loc}; obs: id -> [{cam_xy, az, dist_m}]."""
    E = np.array([e["xy"] for e in elements]) if elements else np.zeros((0, 2))
    R = np.array([r["xy"] for r in refs]) if refs else np.zeros((0, 2))
    out: dict = {"n_elementos": len(elements), "n_ref_osm": len(refs), "gate_m": gate}
    out["precisao_proxy"] = curves(E, R)                    # elementos com OSM perto
    out["recolha_proxy"] = curves(R, E)                     # ecopontos OSM com elemento perto
    by_m = {}
    for m in sorted({e["geo_method"] for e in elements}):
        idx = [i for i, e in enumerate(elements) if e["geo_method"] == m]
        by_m[m] = curves(E[idx], R)
    out["por_metodo"] = by_m
    out["por_n_vistas"] = {k: curves(E[[i for i, e in enumerate(elements) if (e["n_views"] >= 2) == (k == ">=2")]], R) for k in ("1", ">=2")}

    pairs = match_pairs(E, R, gate)
    errs = np.array([p[2] for p in pairs])
    out["pares_1a1"] = {"n": len(pairs), "sem_par_elementos": len(elements) - len(pairs),
                        "sem_par_ref": len(refs) - len(pairs), "erro_m": pct(errs)}
    for m in by_m:
        e_m = np.array([p[2] for p in pairs if elements[p[0]]["geo_method"] == m])
        out["pares_1a1"].setdefault("erro_m_por_metodo", {})[m] = {"n": int(len(e_m)), **pct(e_m)}

    rows = []
    for i, j, _ in pairs:
        for o in obs.get(elements[i]["id"], []):
            r = obs_error(np.asarray(o["cam_xy"]), o["az"], o["dist_m"], R[j])
            if r:
                r["yaw"] = o.get("yaw")
                rows.append(r)
    if rows:
        g = lambda k: np.array([r[k] for r in rows])  # noqa: E731
        out["por_observacao"] = {
            "n": len(rows),
            "erro_rumo_graus": {**pct(g("daz")), "abs_mediano": round(float(np.median(np.abs(g("daz")))), 1)},
            "razao_distancia": pct(g("ratio")),
            "erro_lateral_m_abs_mediano": round(float(np.median(np.abs(g("lateral")))), 1),
            "erro_ao_longo_m": {**pct(g("ao_longo")), "abs_mediano": round(float(np.median(np.abs(g("ao_longo")))), 1)},
            "erro_rumo_por_yaw": {str(y): {"n": len(v), "mediana": round(float(np.median(v)), 1)}
                                  for y in sorted({r["yaw"] for r in rows if r["yaw"] is not None})
                                  for v in [[r["daz"] for r in rows if r["yaw"] == y]]},
            "distancia_real_mediana_m": round(float(np.median(g("d_real"))), 1),
            "distancia_estimada_mediana_m": round(float(np.median([o["dist_m"] for v in obs.values() for o in v])), 1),
        }
    if pilot_pts:
        P = np.array([p["xy"] for p in pilot_pts])
        sub = [i for i, e in enumerate(elements) if e["cls"] == "subterraneo"]
        out["subterraneos_piloto"] = {"n": len(pilot_pts), "qualquer_elemento": curves(P, E), "elemento_subterraneo": curves(P, E[sub])}
    under = [r for r in refs if r.get("loc") in UNDER]
    if under:
        U = np.array([r["xy"] for r in under])
        sub = [i for i, e in enumerate(elements) if e["cls"] == "subterraneo"]
        out["ref_osm_subterraneos"] = {"n": len(under), "elemento_subterraneo": curves(U, E[sub]), "qualquer_elemento": curves(U, E)}
    out["_pares"] = [(i, j, d) for i, j, d in pairs]
    return out


# ------------------------------------------------------------------ dados reais
def _feats(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))["features"] if path.exists() else []


def load_all(city: str, catalog: str = "catalog.geojson"):
    base = ROOT / "data" / "catalog" / city
    refd = ROOT / "data" / "reference"
    x0, y0, x1, y1 = PILOT
    m = 0.0003                                             # ~30 m de margem à volta da caixa
    elements = []
    for f in _feats(base / catalog):
        p = f["properties"]
        if p.get("family") != "residuos":
            continue
        lon, lat = f["geometry"]["coordinates"][:2]
        elements.append({"id": p["id"], "xy": to_m(lat, lon), "cls": p["class"], "geo_method": p.get("geo_method", "?"),
                         "n_views": p.get("n_views", 1), "lat": lat, "lon": lon})
    refs = []
    for f in _feats(refd / f"osm_{city}_reciclagem.geojson"):
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        if p.get("recycling_type") == "reverse_vending_machine":
            continue
        if not (x0 - m <= lon <= x1 + m and y0 - m <= lat <= y1 + m):
            continue
        refs.append({"id": p.get("osm_id"), "xy": to_m(lat, lon), "lat": lat, "lon": lon, "loc": p.get("location")})
    obs_raw = json.loads((base / "observacoes.json").read_text(encoding="utf-8")) if (base / "observacoes.json").exists() else {}
    ids = {e["id"] for e in elements}
    def yaw_of(image_id: str):                              # "<pano>_y180" -> 180 (rumo da vista relativo ao do panorama)
        m = re.search(r"_y(\d+)$", image_id or "")
        return int(m.group(1)) if m else None

    obs = {k: [{"cam_xy": to_m(*o["cam"]), "az": o["az"], "dist_m": o["dist_m"], "yaw": yaw_of(o.get("image_id"))} for o in v]
           for k, v in obs_raw.items() if k in ids}
    pilot = []
    for f in _feats(refd / "subterraneos_aveiro.geojson") if city == "aveiro" else []:
        lon, lat = f["geometry"]["coordinates"][:2]
        pilot.append({"xy": to_m(lat, lon), "lat": lat, "lon": lon})
    return elements, obs, refs, pilot


def evaluate(city: str, gate: float = 40.0, catalog: str = "catalog.geojson") -> dict:
    elements, obs, refs, pilot = load_all(city, catalog)
    res = evaluate_from(elements, obs, refs, pilot, gate)
    res["pares"] = [{"elemento": elements[i]["id"], "ref_osm": refs[j]["id"], "erro_m": round(d, 1),
                     "elem": [elements[i]["lat"], elements[i]["lon"]], "ref": [refs[j]["lat"], refs[j]["lon"]],
                     "cls": elements[i]["cls"]} for i, j, d in res.pop("_pares")]
    res["cidade"] = city
    return res


def to_markdown(r: dict) -> str:
    c = lambda d: " | ".join(f"{k} {d[k]:.0%}" for k in d if k.startswith("<="))  # noqa: E731
    L = [f"# Erro de posição — {r['cidade']}", "",
         f"{r['n_elementos']} elementos de resíduos no catálogo · {r['n_ref_osm']} ecopontos OSM na zona (verdade aproximada) · gate {r['gate_m']:.0f} m", "",
         "## Elementos vs OSM (sem emparelhar)", "",
         f"- **Precisão (proxy)**, elementos com ecoponto OSM a ≤ r: {c(r['precisao_proxy'])} (mais próximo mediano {r['precisao_proxy'].get('mais_proximo_mediano_m')} m)",
         f"- **Recolha (proxy)**, ecopontos OSM com elemento a ≤ r: {c(r['recolha_proxy'])}"]
    for m, v in r["por_metodo"].items():
        L.append(f"- método `{m}` (n={v['n']}): {c(v)}")
    for k, v in r["por_n_vistas"].items():
        L.append(f"- vistas {k} (n={v['n']}): {c(v)}")
    p = r["pares_1a1"]
    L += ["", "## Emparelhamento 1-1 (dentro do gate)", "",
          f"- {p['n']} pares · {p['sem_par_elementos']} elementos sem par · {p['sem_par_ref']} ecopontos OSM sem par",
          f"- erro (m): {p['erro_m']}"]
    for m, v in p.get("erro_m_por_metodo", {}).items():
        L.append(f"  - `{m}` (n={v['n']}): mediana {v.get('p50')} m, p90 {v.get('p90')} m")
    if "por_observacao" in r:
        o = r["por_observacao"]
        L += ["", "## Distância ou rumo? (por observação, elementos emparelhados)", "",
              f"- {o['n']} observações. Distância real câmara→objeto mediana {o['distancia_real_mediana_m']} m; estimada (todas as obs) {o['distancia_estimada_mediana_m']} m",
              f"- **razão distância estimada/real**: {o['razao_distancia']}  (1 = certo; >1 = posto longe demais)",
              f"- **erro ao longo do raio**: {o['erro_ao_longo_m']} m  → mediana |erro| {o['erro_ao_longo_m']['abs_mediano']} m",
              f"- **erro de rumo**: {o['erro_rumo_graus']} °  → |erro| mediano {o['erro_rumo_graus']['abs_mediano']}°",
              f"- **erro lateral** mediano |.| = {o['erro_lateral_m_abs_mediano']} m",
              "- **erro de rumo por orientação da vista (yaw)** (mediana, °; se for igual em todas é um desvio de heading; "
              "se mudar com o yaw é convenção do yaw ou hfov): " + ", ".join(f"y{y}: {v['mediana']}° (n={v['n']})" for y, v in o["erro_rumo_por_yaw"].items())]
    if "subterraneos_piloto" in r:
        s = r["subterraneos_piloto"]
        L += ["", f"## 4 subterrâneos do piloto: qualquer elemento {c(s['qualquer_elemento'])} | elemento `subterraneo` {c(s['elemento_subterraneo'])}"]
    if "ref_osm_subterraneos" in r:
        s = r["ref_osm_subterraneos"]
        L += [f"## {s['n']} ecopontos OSM subterrâneos/semi: elemento `subterraneo` {c(s['elemento_subterraneo'])}"]
    return "\n".join(L) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?", default="aveiro")
    ap.add_argument("--gate", type=float, default=40.0, help="distância máxima (m) para emparelhar elemento e ecoponto OSM")
    ap.add_argument("--catalog", default="catalog.geojson", help="ficheiro em data/catalog/<cidade>/ (ex.: catalog_ajustado.geojson)")
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "posicao")
    a = ap.parse_args()
    r = evaluate(a.city, a.gate, a.catalog)
    r["catalogo"] = a.catalog
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / f"{a.city}.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    md = to_markdown(r)
    (a.out / f"{a.city}.md").write_text(md, encoding="utf-8")
    print(md)
    print(f"-> {a.out / (a.city + '.md')}")


if __name__ == "__main__":
    main()
