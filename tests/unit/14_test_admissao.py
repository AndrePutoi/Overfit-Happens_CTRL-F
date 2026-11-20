"""Autoteste de ctrlf/ingest/admissao.py com imagens sintéticas (sem dados reais)."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

from ctrlf.paths import ROOT
import os as _os
ENV = {**_os.environ, "PYTHONPATH": str(ROOT / "src") + _os.pathsep + _os.environ.get("PYTHONPATH", "")}   # os subprocessos importam ctrlf a partir de src/
sys.path.insert(0, str(ROOT))
from ctrlf.ingest import admissao as A  # noqa: E402

fails = []


def check(name, ok, info=""):
    print(f"{'PASS' if ok else 'FAIL'}  {name}  {info}")
    if not ok:
        fails.append(name)


rng = np.random.default_rng(0)
CFG = A.load_cfg()


def textured(w=1000, h=800):
    """Imagem nítida e com textura: ruído suavizado + quadriculado + riscas."""
    base = cv2.GaussianBlur(rng.integers(0, 255, (h, w), dtype=np.uint8), (0, 0), 1.2)
    yy, xx = np.mgrid[0:h, 0:w]
    base = np.where(((xx // 40 + yy // 40) % 2) == 0, base, 255 - base).astype(np.uint8)
    return cv2.cvtColor(base, cv2.COLOR_GRAY2BGR)


def wall(w=1000, h=800):
    """Fachada lisa (gradiente suave) com janelas de arestas nítidas: pouca textura mas NÍTIDA."""
    g = np.tile(np.linspace(150, 190, w, dtype=np.float32), (h, 1))
    img = cv2.cvtColor(g.astype(np.uint8), cv2.COLOR_GRAY2BGR)
    for x in (200, 500, 800):
        cv2.rectangle(img, (x, 250), (x + 90, 420), (40, 40, 40), -1)
    return cv2.add(img, rng.integers(0, 3, img.shape, dtype=np.uint8))


def save_exif(img, path, lat=40.6431, lon=-8.6503, heading=123.0, f35=26.0):
    im = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    ex = Image.Exif()
    ex[0x8825] = {1: "N" if lat >= 0 else "S", 2: (abs(int(lat)), int((abs(lat) % 1) * 60), ((abs(lat) % 1) * 60 % 1) * 60),
                  3: "E" if lon >= 0 else "W", 4: (abs(int(lon)), int((abs(lon) % 1) * 60), ((abs(lon) % 1) * 60 % 1) * 60), 17: heading}
    ex[0x8769] = {36867: "2026:11:17 10:00:00", 41989: f35}
    im.save(path, exif=ex, quality=95)


with tempfile.TemporaryDirectory() as td:
    d = Path(td)
    good_meta = {"source": "mapillary", "source_image_id": "A", "lat": 40.6431, "lon": -8.6503, "heading": 90.0, "captured_at": "1", "license": "CC BY-SA 4.0",
                 "camera_type": "perspective", "path": ""}

    cv2.imwrite(str(d / "ok.jpg"), textured())
    r = A.admit(d / "ok.jpg", good_meta, CFG)
    check("aprovada (meta completa)", r["status"] == "aprovada" and r["fonte_posicao"] == "meta" and r["geolocalizavel"], str(r["metricas"]))

    save_exif(textured(), d / "exif.jpg")
    r = A.admit(d / "exif.jpg", None, CFG)
    check("posição e rumo lidos do EXIF", r["fonte_posicao"] == "exif" and abs(r["meta"]["lat"] - 40.6431) < 1e-3 and abs(r["meta"]["lon"] + 8.6503) < 1e-3
          and r["fonte_rumo"] == "exif" and abs(r["meta"]["heading"] - 123) < 1e-6 and r["geolocalizavel"], str(r["meta"].get("lat")) + "," + str(r["meta"].get("lon")))
    check("EXIF dá data e campo de visão (26 mm eq. -> ~69°)", r["meta"].get("captured_at") and 60 < r["meta"].get("hfov_deg", 0) < 80, str(r["meta"].get("hfov_deg")))
    check("foto sem licença: aviso", "sem_licenca" in r["avisos"] and r["status"] == "aprovada_com_avisos")

    cv2.imwrite(str(d / "semgps.jpg"), textured())
    r = A.admit(d / "semgps.jpg", None, CFG)
    check("sem posição -> REJEITADA", r["status"] == "rejeitada" and "sem_posicao" in r["motivos"])

    cv2.imwrite(str(d / "zero.jpg"), textured())
    r = A.admit(d / "zero.jpg", {**good_meta, "lat": 0.0, "lon": 0.0}, CFG)
    check("posição 0,0 (ilha nula) -> posicao_invalida", "posicao_invalida" in r["motivos"])
    r = A.admit(d / "zero.jpg", {**good_meta, "lat": 95.0}, CFG)
    check("latitude fora de -90..90 -> posicao_invalida", "posicao_invalida" in r["motivos"])

    m2 = {k: v for k, v in good_meta.items() if k != "heading"}
    r = A.admit(d / "ok.jpg", m2, CFG)
    check("sem rumo -> aprovada com aviso e NÃO geolocalizável", r["status"] == "aprovada_com_avisos" and "sem_rumo" in r["avisos"] and not r["geolocalizavel"])

    # desfoque: com imagens REAIS (tests/fixtures/samples); um quadriculado sintético mantém arestas nítidas numa direção e engana a métrica
    real = cv2.imread(str(ROOT / "tests" / "fixtures" / "samples" / "aveiro_2.jpg"))
    cv2.imwrite(str(d / "real.jpg"), real)
    r = A.admit(d / "real.jpg", good_meta, CFG)
    check("foto real nítida -> aprovada (crete baixo)", r["status"] != "rejeitada" and r["metricas"]["crete"] < CFG["qualidade"]["desfoque_aviso"], f"crete {r['metricas']['crete']}")
    cv2.imwrite(str(d / "blur.jpg"), cv2.GaussianBlur(real, (0, 0), 3.0))
    r = A.admit(d / "blur.jpg", good_meta, CFG)
    check("foto real desfocada (gaussiano s=3) -> REJEITADA", "desfocada" in r["motivos"], f"crete {r['metricas'].get('crete')}")
    cv2.imwrite(str(d / "mov.jpg"), cv2.filter2D(real, -1, np.ones((1, 31), np.float32) / 31))
    r = A.admit(d / "mov.jpg", good_meta, CFG)
    check("foto real com desfoque de movimento (31 px) -> REJEITADA", "desfocada" in r["motivos"], f"crete {r['metricas'].get('crete')}")
    cv2.imwrite(str(d / "leve.jpg"), cv2.GaussianBlur(real, (0, 0), 1.0))
    r = A.admit(d / "leve.jpg", good_meta, CFG)
    check("desfoque ligeiro (s=1) NÃO se rejeita (por desenho, evita falsos positivos)", "desfocada" not in r["motivos"], f"crete {r['metricas'].get('crete')}")

    cv2.imwrite(str(d / "wall.jpg"), wall())
    r = A.admit(d / "wall.jpg", good_meta, CFG)
    check("fachada lisa NÍTIDA não é desfocada (o Laplaciano diria que sim)", "desfocada" not in r["motivos"] and r["status"] != "rejeitada",
          f"crete {r['metricas'].get('crete')}")
    lap_w = cv2.Laplacian(cv2.cvtColor(wall(), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    lap_r = cv2.Laplacian(cv2.cvtColor(cv2.resize(real, (1000, 800)), cv2.COLOR_BGR2GRAY), cv2.CV_64F).var()
    check("(o Laplaciano da fachada lisa é bem mais baixo que o de uma foto de rua: razão do porquê de não o usarmos)", lap_w < lap_r, f"fachada {lap_w:.0f} vs rua {lap_r:.0f}")

    cv2.imwrite(str(d / "dark.jpg"), (textured() * 0.05).astype(np.uint8))
    r = A.admit(d / "dark.jpg", good_meta, CFG)
    check("escura -> REJEITADA", "escura" in r["motivos"], f"brilho {r['metricas'].get('brilho')}")
    cv2.imwrite(str(d / "white.jpg"), np.full((800, 1000, 3), 245, np.uint8))
    r = A.admit(d / "white.jpg", good_meta, CFG)
    check("branca/sobreexposta -> REJEITADA", "sobreexposta" in r["motivos"] or "saturada" in r["motivos"], str(r["motivos"]))
    cv2.imwrite(str(d / "cover.jpg"), np.full((800, 1000, 3), 90, np.uint8) + rng.integers(0, 2, (800, 1000, 3), dtype=np.uint8))
    r = A.admit(d / "cover.jpg", good_meta, CFG)
    check("lente tapada (sem contraste) -> REJEITADA", "tapada" in r["motivos"], f"contraste {r['metricas'].get('contraste')}")
    cv2.imwrite(str(d / "small.jpg"), textured(300, 200))
    r = A.admit(d / "small.jpg", good_meta, CFG)
    check("resolução baixa -> REJEITADA", "resolucao_baixa" in r["motivos"])
    (d / "lixo.jpg").write_bytes(b"isto nao e uma imagem")
    r = A.admit(d / "lixo.jpg", good_meta, CFG)
    check("ficheiro ilegível -> REJEITADA", r["motivos"] == ["ficheiro_ilegivel"])
    r = A.admit(d / "ok.jpg", good_meta, CFG, known_ids={"A"})
    check("id já conhecido -> duplicada", "duplicada" in r["motivos"])
    r = A.admit(d / "ok.jpg", good_meta, CFG, zona="porto")
    check("fora da zona -> aviso (não rejeita)", "fora_da_zona" in r["avisos"] and r["status"] != "rejeitada")

    # CLI --aplicar: move as rejeitadas e filtra o meta.jsonl
    w = d / "lote"
    w.mkdir()
    for n, img in (("a.jpg", textured()), ("b.jpg", cv2.GaussianBlur(textured(), (0, 0), 3.0)), ("c.jpg", textured())):
        cv2.imwrite(str(w / n), img)
    rows = [{**good_meta, "source_image_id": s, "path": str(w / n)} for s, n in (("a", "a.jpg"), ("b", "b.jpg"))]   # c.jpg sem meta e sem EXIF
    (w / "meta.jsonl").write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
    p = subprocess.run([sys.executable, "-m", "ctrlf.ingest.admissao", str(w), "--aplicar"], capture_output=True, text=True, cwd=ROOT, env=ENV)
    left = sorted(x.name for x in w.glob("*.jpg"))
    kept = [json.loads(l)["source_image_id"] for l in (w / "meta.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    check("--aplicar: só ficam as aprovadas", left == ["a.jpg"] and kept == ["a"] and p.returncode == 0, f"{left} {kept} {p.stdout[-120:]!r}")
    check("--aplicar: rejeitadas em _rejeitadas/ e cópia do meta", sorted(x.name for x in (w / "_rejeitadas").glob("*.jpg")) == ["b.jpg", "c.jpg"] and (w / "meta.jsonl.antes_admissao").exists())

print("\noverall:", "PASS" if not fails else f"FAIL {fails}")
sys.exit(1 if fails else 0)
