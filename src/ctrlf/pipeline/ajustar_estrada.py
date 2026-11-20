"""Puxa a posição estimada de cada observação para o "corredor" da estrada OSM mais próxima, na direção da câmara.

    python -m ctrlf.pipeline.ajustar_estrada aveiro                 # -> data/catalog/aveiro/catalog_ajustado.geojson
    python -m ctrlf.pipeline.ajustar_estrada aveiro --varrer        # compara larguras do corredor contra os ecopontos OSM

Problema (reports/posicao/aveiro.md): a profundidade põe os objetos ~1,4x mais longe do que estão, para lá do passeio, até dentro de
edifícios. Mobiliário urbano (sinais, contentores) fica junto da estrada. Aqui o raio da câmara (azimute) é mantido e só se corrige a
DISTÂNCIA ao longo dele:

  1. posição estimada E = câmara + dist_m * direção(azimute)
  2. via OSM mais próxima de E (<= --max-via m); lado s = de que lado da via está E
  3. corredor = linha paralela à via, a --w metros dela, do lado s (--w ~ meia faixa + passeio)
  4. se E já está dentro do corredor, não mexe; senão o novo ponto é onde o RAIO cruza o corredor
  5. só se puxa PARA A CÂMARA: se o cruzamento fica mais longe que E, ou atrás da câmara, ou a < 2 m, ou o raio é quase paralelo
     à via, ou cai fora do troço da via (+10 m), mantém-se E.

Elementos com mais de 1 vista TRIANGULADOS mantêm a posição triangulada (não depende da profundidade); os de vista única usam a
média das observações ajustadas. Só usa o OSM (as vias) como referência; os ecopontos OSM servem apenas para MEDIR.
Escreve catalog_ajustado.geojson com `pos_original`, `ajuste_m` e `ajuste_metodo` por elemento.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.geometry.geometry import to_deg, to_m  # noqa: E402
from ctrlf.ingest.osm_vias import load as load_vias  # noqa: E402


class Roads:
    """Segmentos das vias em metros, com normal (esquerda do sentido do segmento)."""

    def __init__(self, vias: list[dict]):
        A, B = [], []
        for v in vias:
            pts = [to_m(la, lo) for la, lo in v["pts"]]
            for a, b in zip(pts[:-1], pts[1:]):
                if np.hypot(*(b - a)) > 0.5:
                    A.append(a); B.append(b)
        self.A, self.B = np.array(A), np.array(B)
        d = self.B - self.A
        self.L = np.hypot(d[:, 0], d[:, 1])
        self.u = d / self.L[:, None]
        self.n = np.stack([-self.u[:, 1], self.u[:, 0]], axis=1)

    def nearest(self, p: np.ndarray):
        """-> (índice do segmento mais próximo, distância em m)."""
        ap = p - self.A
        s = np.clip((ap * self.u).sum(1), 0, self.L)
        q = self.A + self.u * s[:, None]
        d = np.hypot(*(p - q).T)
        i = int(d.argmin())
        return i, float(d[i])


def snap(cam: np.ndarray, az: float, dist: float, roads: Roads, w: float, max_via: float = 40.0,
         min_t: float = 2.0, ext: float = 10.0) -> tuple[np.ndarray, str]:
    """-> (novo ponto em metros, método). Método: 'estrada' | 'ja_no_corredor' | 'mantido:<motivo>'."""
    d = np.array([math.sin(math.radians(az)), math.cos(math.radians(az))])
    E = cam + dist * d
    i, dv = roads.nearest(E)
    if dv > max_via:
        return E, "mantido:longe_de_vias"
    sdE = float((E - roads.A[i]) @ roads.n[i])
    if abs(sdE) <= w:
        return E, "ja_no_corredor"
    s = 1.0 if sdE > 0 else -1.0
    dn = float(d @ roads.n[i])
    if abs(dn) < 0.1:
        return E, "mantido:raio_paralelo"
    t = (s * w - float((cam - roads.A[i]) @ roads.n[i])) / dn
    if t < min_t:
        return E, "mantido:atras_ou_perto"
    if t >= dist:
        return E, "mantido:mais_longe"
    P = cam + t * d
    along = float((P - roads.A[i]) @ roads.u[i])
    if along < -ext or along > roads.L[i] + ext:
        return E, "mantido:fora_do_troco"
    return P, "estrada"


def view_geometry(city: str) -> dict[str, tuple[int, int, float]]:
    """image_id -> (largura, altura, hfov_deg) das vistas planas (tamanho vem do COCO; hfov do images_index)."""
    base = ROOT / "data" / "catalog" / city
    idx = json.loads((base / "images_index.json").read_text(encoding="utf-8"))
    coco = json.loads((ROOT / "data" / "preannot" / "ecopontos" / city / "annotations" / "instances_default.json").read_text(encoding="utf-8"))
    size = {i["file_name"].rsplit(".", 1)[0]: (i["width"], i["height"]) for i in coco["images"]}
    return {k: (*size[k], v["hfov_deg"] or 100.0) for k, v in idx.items() if k in size}


def ipm_distance(bbox, size: tuple[int, int, float], cam_h: float, d_max: float) -> float | None:
    """Distância (m) ao ponto de contacto com o chão = base da caixa, plano horizontal, horizonte no centro da imagem (pitch 0):
    d = h / tan(theta), theta = atan((y_base - cy) / f). None se a base está no horizonte ou acima (não há interseção)."""
    W, H, hfov = size
    dy = bbox[3] - H / 2
    if dy <= 1.0:
        return None
    f = (W / 2) / math.tan(math.radians(hfov) / 2)
    return min(cam_h / math.tan(math.atan(dy / f)), d_max)


def adjust_catalog(city: str, w: float, max_via: float = 40.0, out_name: str = "catalog_ajustado.geojson",
                   dist_mode: str = "profundidade", cam_h: float = 1.5, ipm_max: float = 40.0, scale: float = 1.0) -> dict:
    base = ROOT / "data" / "catalog" / city
    cat = json.loads((base / "catalog.geojson").read_text(encoding="utf-8"))
    obs = json.loads((base / "observacoes.json").read_text(encoding="utf-8"))
    roads = Roads(load_vias(city)["vias"])
    geo = view_geometry(city) if dist_mode == "ipm" else {}
    stats: dict = {}
    moved = []
    for f in cat["features"]:
        p = f["properties"]
        lon, lat = f["geometry"]["coordinates"][:2]
        p["pos_original"] = [round(lat, 7), round(lon, 7)]
        o = obs.get(p["id"], [])
        if p.get("geo_method") == "triangulado" or not o:
            p["ajuste_m"], p["ajuste_metodo"] = 0.0, "triangulado_mantido" if o else "sem_observacoes"
        else:
            pts, ms = [], []
            for x in o:
                dist = x["dist_m"] * scale
                if dist_mode == "ipm":                                   # plano do chão; sem interseção -> mantém a profundidade
                    dist = ipm_distance(x["bbox"], geo[x["image_id"]], cam_h, ipm_max) or dist
                P, m = snap(to_m(*x["cam"]), x["az"], dist, roads, w, max_via)
                pts.append(P); ms.append(m)
            P = np.mean(pts, axis=0)
            nl, nlo = to_deg(P)
            p["ajuste_m"] = round(float(np.hypot(*(P - to_m(lat, lon)))), 1)
            p["ajuste_metodo"] = "estrada" if "estrada" in ms else ms[0]
            f["geometry"]["coordinates"] = [round(nlo, 7), round(nl, 7)]
        stats[p["ajuste_metodo"]] = stats.get(p["ajuste_metodo"], 0) + 1
        if p["ajuste_metodo"] == "estrada":
            moved.append(p["ajuste_m"])
    cat["ajuste"] = {"w_m": w, "max_via_m": max_via, "distancia": dist_mode, "cam_h_m": cam_h if dist_mode == "ipm" else None, "escala": scale, "metodos": stats,
                     "deslocamento_mediano_m": round(float(np.median(moved)), 1) if moved else 0.0}
    (base / out_name).write_text(json.dumps(cat, ensure_ascii=False), encoding="utf-8")
    return cat["ajuste"]


def main() -> None:
    from ctrlf.pipeline.avaliar_posicao import evaluate
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?", default="aveiro")
    ap.add_argument("--w", type=float, default=3.0, help="largura do corredor: distância da via ao sítio onde se põem os objetos (m)")
    ap.add_argument("--max-via", type=float, default=40.0)
    ap.add_argument("--dist-modo", choices=["profundidade", "ipm"], default="profundidade",
                    help="distância de cada observação: profundidade monocular (omissão) ou plano do chão (IPM, base da caixa)")
    ap.add_argument("--cam-h", type=float, default=1.5, help="IPM: altura da câmara (m)")
    ap.add_argument("--ipm-max", type=float, default=40.0, help="IPM: teto de distância (m) para objetos perto do horizonte")
    ap.add_argument("--escala", type=float, default=1.0, help="fator sobre a distância da profundidade")
    ap.add_argument("--varrer-ipm", action="store_true", help="compara IPM (várias alturas) e profundidade, com e sem o corredor")
    ap.add_argument("--varrer", action="store_true", help="avalia vários --w contra os ecopontos OSM (sem escrever o catálogo final)")
    a = ap.parse_args()

    def row(name, r):
        pr, rc, p = r.get("precisao_proxy") or {}, r.get("recolha_proxy") or {}, r.get("pares_1a1") or {"n": 0, "erro_m": {}}
        pc = lambda d, k: f"{d[k]:.0%}" if k in d else "n/d"                      # zona sem pontos de referência do OSM para comparar: não há estatística (n/d), nunca um valor inventado
        return (f"{name:<18} pares {p.get('n', 0):>3} | erro mediano {p.get('erro_m', {}).get('p50', float('nan')):>5.1f} m | "
                f"elementos a <=5/10/15 m do OSM: {pc(pr, '<=5m')}/{pc(pr, '<=10m')}/{pc(pr, '<=15m')} | ecopontos OSM com elemento a <=10 m: {pc(rc, '<=10m')}")

    print(row("original", evaluate(a.city, catalog="catalog.geojson")))
    if a.varrer:
        for w in (0, 2, 3, 4, 5, 6, 8):
            adjust_catalog(a.city, w, a.max_via, out_name="_tmp_ajustado.geojson")
            print(row(f"w = {w} m", evaluate(a.city, catalog="_tmp_ajustado.geojson")))
        (ROOT / "data" / "catalog" / a.city / "_tmp_ajustado.geojson").unlink(missing_ok=True)
        return
    if a.varrer_ipm:
        for modo, hh, esc in (("profundidade", 0, 1.0), ("profundidade", 0, 0.68), ("ipm", 1.2, 1.0), ("ipm", 1.5, 1.0), ("ipm", 2.0, 1.0), ("ipm", 2.5, 1.0), ("ipm", 3.0, 1.0)):
            for ww in (3.0,):
                adjust_catalog(a.city, ww, a.max_via, "_tmp_ajustado.geojson", modo, hh or 1.5, a.ipm_max, esc)
                nome = f"{modo}{'' if modo == 'ipm' else f' x{esc:g}'}{f' h={hh:g}' if modo == 'ipm' else ''} +corredor"
                print(row(nome, evaluate(a.city, catalog="_tmp_ajustado.geojson")))
        (ROOT / "data" / "catalog" / a.city / "_tmp_ajustado.geojson").unlink(missing_ok=True)
        return
    info = adjust_catalog(a.city, a.w, a.max_via, dist_mode=a.dist_modo, cam_h=a.cam_h, ipm_max=a.ipm_max, scale=a.escala)
    print(row(f"ajustado (w={a.w:g})", evaluate(a.city, catalog="catalog_ajustado.geojson")))
    print("métodos:", info["metodos"], "| deslocamento mediano (os que mexeram):", info["deslocamento_mediano_m"], "m")


if __name__ == "__main__":
    main()
