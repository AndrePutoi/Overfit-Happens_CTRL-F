"""Guarda UMA vez cada imagem anonimizada e reutiliza-a em todas as inferências seguintes.

    from ctrlf.privacy.anon_cache import anonymized_cached
    anon = anonymized_cached("data/cvat_upload/lisboa/xxx.jpg")     # -> privacy.gate.Anonymized (RGB uint8)
    Detector().detect(anon, 0.3)                                    # o portão reconhece-a e não volta a desfocar

    python -m ctrlf.privacy.anon_cache data/cvat_upload/porto data/cvat_upload/lisboa     # enche a cache em lote

Porquê: o desfoque (rostos + matrículas) é o passo mais lento (~3 a 4 s por imagem) e repetia-se em cada script.
Agora corre uma vez por imagem; as seguintes só descodificam um JPEG.

Garantia (falha fechada, como o gate.py): o portão continua a não ter parâmetro para saltar o desfoque.  Um ficheiro só é
aceite como "já anonimizado" se existir no manifesto `data/images_anon/manifest.jsonl` COM o mesmo SHA-256 do ficheiro guardado,
do ficheiro de origem e dos parâmetros de privacidade.  Qualquer falha (origem alterada, ficheiro editado/apagado, outros
modelos ou limiares) -> volta a anonimizar a partir da ORIGEM e substitui a entrada.  Nunca confia num JPEG que não conheça.

O ficheiro guardado tem o MESMO nome que a origem (`<source_image_id>.jpg`): é a pasta que C serve em /images/<image_id>.jpg.
"""
from __future__ import annotations

import hashlib
import json
import sys
import threading
from pathlib import Path

import numpy as np
from PIL import Image

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))

STORE = ROOT / "data" / "images_anon"
QUALITY = 95
_lock = threading.Lock()
_manifest: dict[str, dict] = {}
_loaded_from: Path | None = None
_params: str | None = None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def _privacy_params() -> str:
    """Impressão digital das definições de privacidade (limiares, pesos, modo): se mudarem, a cache invalida-se."""
    from ctrlf.privacy.gate import _settings
    kw = _settings()
    return hashlib.sha256(json.dumps(sorted((k, str(v)) for k, v in kw.items())).encode()).hexdigest()[:16]


def _load_manifest(store: Path) -> None:
    global _manifest, _loaded_from
    if _loaded_from == store:
        return
    _manifest = {}
    mf = store / "manifest.jsonl"
    if mf.exists():
        for line in mf.read_text(encoding="utf-8").splitlines():
            if line.strip():
                e = json.loads(line)
                _manifest[e["file"]] = e                     # a última entrada de cada ficheiro vence
    _loaded_from = store


def _decode(path: Path, entry: dict):
    from ctrlf.privacy.gate import Anonymized
    rgb = np.asarray(Image.open(path).convert("RGB"))
    res = np.ascontiguousarray(rgb).view(Anonymized)
    res.privacy_counts = entry.get("counts", {})
    res.privacy_vehicles = entry.get("vehicles", [])
    return res


def anonymized_cached(src, store: Path | None = None):
    """Imagem anonimizada de `src`: da cache se verificada, senão desfoca, guarda e devolve (já a versão guardada)."""
    global _params
    src, store = Path(src), Path(store) if store else STORE
    with _lock:
        _load_manifest(store)
        if _params is None:
            _params = _privacy_params()
        src_sha = _sha(src)
        out = store / src.name
        e = _manifest.get(src.name)
        if (e and e["src_sha256"] == src_sha and e["params"] == _params and out.exists() and _sha(out) == e["sha256"]):
            return _decode(out, e)
        from ctrlf.privacy.gate import anonymize
        res = anonymize(Image.open(src).convert("RGB"))
        store.mkdir(parents=True, exist_ok=True)
        tmp = out.with_suffix(".tmp.jpg")
        Image.fromarray(np.asarray(res)).save(tmp, quality=QUALITY, subsampling=0)
        tmp.replace(out)
        e = {"file": src.name, "sha256": _sha(out), "src_sha256": src_sha, "params": _params,
             "counts": dict(res.privacy_counts), "vehicles": [[float(v) for v in b] for b in res.privacy_vehicles]}
        with open(store / "manifest.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")
        _manifest[src.name] = e
        return _decode(out, e)           # devolve a versão GUARDADA: a 1.ª e as seguintes execuções dão os mesmos píxeis


def main() -> None:
    import time
    dirs = [Path(a) for a in sys.argv[1:]]
    if not dirs:
        sys.exit("uso: anon_cache.py <pasta_de_imagens>...")
    files = sorted(p for d in dirs for p in d.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
    t0 = time.time()
    for i, p in enumerate(files, 1):
        anonymized_cached(p)
        if i % 25 == 0 or i == len(files):
            print(f"  {i}/{len(files)} ({time.time()-t0:.0f}s)", flush=True)
    print(f"-> {STORE}")


if __name__ == "__main__":
    main()
