"""Portão de ADMISSÃO de imagens: localização obrigatória + filtro de qualidade, ANTES da anonimização (o passo mais caro, ~1,3 s por vista).

    python -m ctrlf.ingest.admissao DIR                      # relatório (não mexe em nada) -> DIR/admissao.jsonl
    python -m ctrlf.ingest.admissao DIR --aplicar            # move as rejeitadas para DIR/_rejeitadas/ e filtra o meta.jsonl
    python -m ctrlf.ingest.admissao DIR --zona aveiro        # avisa fora_da_zona (caixas em configs/admissao.yaml)

DIR tem as imagens e (opcional) um meta.jsonl no formato ImageMeta (common/contract.py). Imagens sem linha no meta.jsonl (ex.: fotos de um técnico)
também se avaliam: a posição, o rumo, a data e o campo de visão tentam-se ler do EXIF.

REGRAS (limiares em configs/admissao.yaml)
  REJEITA   sem_posicao (nem no metadado nem no EXIF) · posicao_invalida (fora de -90..90/-180..180, ou 0,0) · ficheiro_ilegivel · resolucao_baixa ·
            duplicada (source_image_id já conhecido) · desfocada · escura · sobreexposta · tapada (contraste mínimo) · saturada
  AVISO     sem_rumo (aprovada mas geolocalizavel=false: não se calcula posição de objetos sem rumo) · sem_data · pouco_nitida · fora_da_zona · sem_licenca
Ordem de fontes da posição e do rumo: metadado (meta.jsonl) > EXIF. Nunca se inventa um rumo.

DESFOQUE = Crété (2007), NÃO a variância do Laplaciano: o Laplaciano mede textura e dava 14-60 em fachadas lisas nítidas (ver configs/admissao.yaml).
Uso em código (p. ex., o upload da API):  admit(path, meta, cfg, known_ids) -> dict com status, motivos, avisos, metricas, geolocalizavel, meta.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
import yaml
from PIL import Image

from ctrlf.paths import ROOT
CFG_PATH = ROOT / "configs" / "admissao.yaml"
IMG_EXT = {".jpg", ".jpeg", ".png"}


def load_cfg(path: Path = CFG_PATH) -> dict:
    cfg = yaml.safe_load(path.read_text(encoding="utf-8"))
    if str(ROOT) not in sys.path:                           # corrido como `python -m ctrlf.ingest.admissao`, a raiz do projeto não está no caminho
        sys.path.insert(0, str(ROOT))
    from ctrlf.ingest.zonas import caixa_swne, todas              # zonas novas (data/zonas/<nome>/zona.json) entram sem editar o YAML
    for nome, z in todas().items():
        cfg["zonas"].setdefault(nome, list(caixa_swne(z)))
    return cfg


# ------------------------------------------------------------------ EXIF
def _f(v) -> float:
    return float(v[0]) / float(v[1]) if isinstance(v, tuple) else float(v)


def _dms(v, ref) -> float | None:
    try:
        d, m, s = (_f(x) for x in v)
    except (TypeError, ValueError, ZeroDivisionError):
        return None
    deg = d + m / 60 + s / 3600
    return -deg if str(ref).upper() in ("S", "W") else deg


def exif_info(path: Path) -> dict:
    """lat, lon, heading, captured_at, hfov_deg que o EXIF consiga dar (chaves em falta = não há)."""
    out: dict = {}
    try:
        ex = Image.open(path).getexif()
        gps = ex.get_ifd(0x8825)
        if gps and 2 in gps and 4 in gps:
            lat, lon = _dms(gps[2], gps.get(1, "N")), _dms(gps[4], gps.get(3, "E"))
            if lat is not None and lon is not None:
                out["lat"], out["lon"] = lat, lon
        if gps and 17 in gps:
            out["heading"] = _f(gps[17]) % 360
        sub = ex.get_ifd(0x8769)
        dto = sub.get(36867) or ex.get(306)                       # DateTimeOriginal / DateTime
        if dto:
            out["captured_at"] = str(dto)
        f35 = sub.get(41989)                                      # FocalLengthIn35mmFilm -> campo de visão horizontal
        if f35 and _f(f35) > 0:
            out["hfov_deg"] = round(math.degrees(2 * math.atan(18.0 / _f(f35))), 1)
    except Exception:                                             # EXIF corrompido não deve rebentar a admissão
        pass
    return out


# ------------------------------------------------------------------ qualidade
def crete_blur(gray: np.ndarray) -> float:
    """Crété 2007: 0 = nítida, 1 = muito desfocada. Compara as variações entre vizinhos antes e depois de re-desfocar."""
    f = gray.astype(np.float32)
    b = cv2.blur(f, (9, 9))
    out = []
    for ax in (0, 1):
        df, db = np.abs(np.diff(f, axis=ax)), np.abs(np.diff(b, axis=ax))
        v = np.maximum(0, df - db)
        out.append((df.sum() - v.sum()) / max(float(df.sum()), 1e-6))
    return float(max(out))


def quality_metrics(img_bgr: np.ndarray, equirect: bool = False) -> dict:
    g = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2GRAY)
    h, w = g.shape
    lo, hi = (0.33, 0.67) if equirect else (0.2, 0.8)             # sem céu nem capô/chão (nos panoramas, perto do equador)
    c = g[int(lo * h):int(hi * h)]
    c = cv2.resize(c, (800, max(8, int(c.shape[0] * 800 / w))), interpolation=cv2.INTER_AREA)
    return {"crete": round(crete_blur(c), 3), "brilho": round(float(g.mean()), 1), "contraste": round(float(g.std()), 1),
            "sat_alta": round(float((g >= 250).mean()), 3), "sat_baixa": round(float((g <= 5).mean()), 3), "largura": w, "altura": h}


# ------------------------------------------------------------------ decisão
def admit(path: Path, meta: dict | None, cfg: dict, known_ids: set[str] | None = None, zona: str | None = None, com_qualidade: bool = True) -> dict:
    """Avalia UMA imagem. -> {id, ficheiro, status, motivos, avisos, geolocalizavel, fonte_posicao, fonte_rumo, metricas, meta}.
    status: 'aprovada' | 'aprovada_com_avisos' | 'rejeitada'."""
    path = Path(path)
    m = dict(meta or {})
    motivos: list[str] = []
    avisos: list[str] = []
    iid = str(m.get("source_image_id") or path.stem)
    fonte_pos = fonte_rumo = "-"

    img = cv2.imread(str(path))
    if img is None:
        return {"id": iid, "ficheiro": path.name, "status": "rejeitada", "motivos": ["ficheiro_ilegivel"], "avisos": [], "geolocalizavel": False,
                "fonte_posicao": "-", "fonte_rumo": "-", "metricas": {}, "meta": m}
    if known_ids and iid in known_ids:
        motivos.append("duplicada")

    # ---- posição e rumo: metadado > EXIF
    ex = exif_info(path) if (m.get("lat") is None or m.get("lon") is None or m.get("heading") is None
                            or not m.get("captured_at") or not m.get("hfov_deg")) else {}
    if m.get("lat") is not None and m.get("lon") is not None:
        fonte_pos = "meta"
    elif "lat" in ex:
        m["lat"], m["lon"], fonte_pos = ex["lat"], ex["lon"], "exif"
    if fonte_pos == "-":
        motivos.append("sem_posicao")
    else:
        lat, lon = float(m["lat"]), float(m["lon"])
        if not (-90 <= lat <= 90 and -180 <= lon <= 180) or (abs(lat) < 0.01 and abs(lon) < 0.01) or math.isnan(lat) or math.isnan(lon):
            motivos.append("posicao_invalida")
    if m.get("heading") is not None:
        m["heading"], fonte_rumo = float(m["heading"]) % 360, "meta"
    elif "heading" in ex:
        m["heading"], fonte_rumo = ex["heading"], "exif"
    else:
        avisos.append("sem_rumo")
    if not m.get("captured_at"):
        if "captured_at" in ex:
            m["captured_at"] = ex["captured_at"]
        else:
            avisos.append("sem_data")
    if not m.get("hfov_deg") and "hfov_deg" in ex:
        m["hfov_deg"] = ex["hfov_deg"]
    if not m.get("license"):
        avisos.append("sem_licenca")
    if zona and fonte_pos != "-" and "posicao_invalida" not in motivos:
        s, w, n, e = cfg["zonas"][zona]
        if not (s <= float(m["lat"]) <= n and w <= float(m["lon"]) <= e):
            avisos.append("fora_da_zona")
    if not cfg.get("exigir_posicao", True) and "sem_posicao" in motivos:
        motivos.remove("sem_posicao"); avisos.append("sem_posicao")
    if cfg.get("exigir_rumo", False) and "sem_rumo" in avisos:
        avisos.remove("sem_rumo"); motivos.append("sem_rumo")

    # ---- resolução e qualidade
    equi = m.get("camera_type") == "equirectangular"
    h, w = img.shape[:2]
    r = cfg["resolucao"]
    if (equi and w < r["largura_min_panorama"]) or (not equi and min(h, w) < r["lado_menor_min"]):
        motivos.append("resolucao_baixa")
    met: dict = {}
    if com_qualidade:
        q = cfg["qualidade"]
        met = quality_metrics(img, equi)
        if met["crete"] > q["desfoque_rejeitar"]:
            motivos.append("desfocada")
        elif met["crete"] > q["desfoque_aviso"]:
            avisos.append("pouco_nitida")
        if met["brilho"] < q["brilho_min"]:
            motivos.append("escura")
        if met["brilho"] > q["brilho_max"]:
            motivos.append("sobreexposta")
        if met["contraste"] < q["contraste_min"] and "escura" not in motivos and "sobreexposta" not in motivos:
            motivos.append("tapada")
        if met["sat_alta"] > q["saturacao_alta_max"] and "sobreexposta" not in motivos:
            motivos.append("saturada")
        if met["sat_baixa"] > q["saturacao_baixa_max"] and "escura" not in motivos:
            motivos.append("saturada")

    geo = fonte_pos != "-" and "posicao_invalida" not in motivos and m.get("heading") is not None
    status = "rejeitada" if motivos else ("aprovada_com_avisos" if avisos else "aprovada")
    # meta completa (ImageMeta) para o que for aprovado
    m.setdefault("source", "upload")
    m.setdefault("source_image_id", iid)
    m.setdefault("camera_type", "perspective")
    m.setdefault("license", "desconhecida")
    m.setdefault("attribution", "")
    m["path"] = m.get("path") or str(path)
    m.setdefault("extra", {})["admissao"] = {"status": status, "avisos": avisos, "geolocalizavel": geo, "fonte_posicao": fonte_pos, "fonte_rumo": fonte_rumo,
                                            **({"crete": met["crete"]} if met else {})}
    return {"id": iid, "ficheiro": path.name, "status": status, "motivos": motivos, "avisos": avisos, "geolocalizavel": geo,
            "fonte_posicao": fonte_pos, "fonte_rumo": fonte_rumo, "metricas": met, "meta": m}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("dir", type=Path)
    ap.add_argument("--meta", type=Path, help="omissão: DIR/meta.jsonl")
    ap.add_argument("--zona", choices=list(load_cfg()["zonas"]), help="avisa fora_da_zona")
    ap.add_argument("--aplicar", action="store_true", help="move as rejeitadas para DIR/_rejeitadas/ e reescreve o meta.jsonl só com as aprovadas")
    ap.add_argument("--sem-qualidade", action="store_true", help="só valida posição/rumo/duplicados")
    ap.add_argument("--conhecidos", type=Path, nargs="*", default=[], help="meta.jsonl cujos source_image_id contam como já existentes")
    a = ap.parse_args()
    cfg = load_cfg()
    d = a.dir
    mp = a.meta or d / "meta.jsonl"
    metas: dict[str, dict] = {}
    order: list[str] = []
    if mp.exists():
        for line in mp.read_text(encoding="utf-8").splitlines():
            if line.strip():
                m = json.loads(line)
                name = Path(m["path"]).name
                metas[name] = m
                order.append(name)
    files = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT)
    known: set[str] = set()
    for kp in a.conhecidos:
        known |= {json.loads(l)["source_image_id"] for l in kp.read_text(encoding="utf-8").splitlines() if l.strip()}
    seen: set[str] = set()
    decisions = []
    for p in files:
        dec = admit(p, metas.get(p.name), cfg, known | seen, a.zona, not a.sem_qualidade)
        if dec["status"] != "rejeitada" or "duplicada" not in dec["motivos"]:
            seen.add(dec["id"])
        decisions.append(dec)
    from collections import Counter
    st = Counter(x["status"] for x in decisions)
    why = Counter(r for x in decisions for r in x["motivos"])
    avs = Counter(r for x in decisions for r in x["avisos"])
    (d / "admissao.jsonl").write_text("\n".join(json.dumps({k: v for k, v in x.items() if k != "meta"}, ensure_ascii=False) for x in decisions) + "\n", encoding="utf-8")
    print(f"{len(decisions)} imagens: {dict(st)}")
    if why:
        print("motivos de rejeição:", dict(why))
    if avs:
        print("avisos:", dict(avs))
    print(f"geolocalizáveis (posição + rumo): {sum(x['geolocalizavel'] for x in decisions if x['status'] != 'rejeitada')} de {len(decisions) - st.get('rejeitada', 0)} aprovadas")
    if a.aplicar:
        rej = d / "_rejeitadas"
        rej.mkdir(exist_ok=True)
        keep = []
        for x in decisions:
            if x["status"] == "rejeitada":
                shutil.move(str(d / x["ficheiro"]), str(rej / x["ficheiro"]))
            else:
                keep.append(x["meta"])
        if mp.exists():
            shutil.copy2(mp, d / "meta.jsonl.antes_admissao")
        mp_out = d / "meta.jsonl"
        mp_out.write_text("\n".join(json.dumps(m, ensure_ascii=False) for m in keep) + "\n", encoding="utf-8")
        print(f"aplicado: {st.get('rejeitada', 0)} rejeitadas movidas para {rej}; meta.jsonl com {len(keep)} linhas (cópia: meta.jsonl.antes_admissao)")
    elif st.get("rejeitada"):
        print("(nada foi movido; repete com --aplicar)")
    sys.exit(0)


if __name__ == "__main__":
    main()
