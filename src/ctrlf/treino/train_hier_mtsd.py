"""Treina o classificador hierárquico de sinais (router de grupo + 1 especialista por família) sobre data/crops/mtsd.

    python -m ctrlf.treino.mtsd_prepare ...        # 1.º: gerar os recortes
    python -m ctrlf.treino.train_hier_mtsd         # 2.º: treinar (router + 4 especialistas)
    python -m ctrlf.treino.train_hier_mtsd --only router --epochs 6

Reutiliza detection.subclass.sign_classifier.train (DINOv2-small + cabeça linear, 2 fases: cabeça congelada e depois
backbone com lr baixo, AMP, pesos inversos à frequência, sem flip).  Escreve os checkpoints em models/hier_sinal_mtsd/
ao lado do manifesto criado por mtsd_prepare.py.  Recomeçar: apagar o .pt em causa (ou usar --force).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.detection.subclass.sign_classifier import train  # noqa: E402

CROPS = ROOT / "data" / "crops" / "mtsd"
MODEL_DIR = ROOT / "models" / "hier_sinal_mtsd"
#            nome            épocas  épocas com backbone congelado
DEFAULT = {"router": (6, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", nargs="*", help="treinar só estes modelos (ex.: router esp_perigo)")
    ap.add_argument("--epochs", type=int, help="substitui o número de épocas")
    ap.add_argument("--batch", type=int, default=64)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()

    meta = json.loads((CROPS / "meta.json").read_text(encoding="utf-8"))
    names = ["router"] + [n for n in meta["models"] if n.startswith("esp_")]
    for name in names:
        if a.only and name not in a.only:
            continue
        out = MODEL_DIR / f"{name}.pt"
        if out.exists() and not a.force:
            print(f"[{name}] já existe ({out.name}); saltar (--force para refazer)")
            continue
        ep, fr = DEFAULT.get(name, (8, 2))
        ep = a.epochs or ep
        t0 = time.time()
        print(f"\n===== {name}: {len(meta['models'][name]['labels'])} classes, {ep} épocas ({fr} com backbone congelado)")
        train(name, ep, a.batch, a.lr, fr, data=CROPS / name, out=out)
        print(f"[{name}] concluído em {(time.time() - t0) / 60:.1f} min")


if __name__ == "__main__":
    main()
