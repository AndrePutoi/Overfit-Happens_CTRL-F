"""Divide o dataset de contentores por tipo de resíduo em train/val (80/20, ALEATÓRIO por classe, semente fixa).

    python -m ctrlf.treino.split_residuos
    python -m ctrlf.detection.subclass.sign_classifier train residuos --data data/crops/residuos --epochs 4

Origem : data/external/waste_container/dataset_waste_container/<classe>/*.jpg   (já recortes de contentores)
Destino: data/crops/residuos/{train,val}/<classe>/  (atalhos simbólicos; não duplica imagens)

A divisão é aleatória POR IMAGEM, como pedido. Atenção: se o dataset tem várias imagens do mesmo contentor (nomes como
0124_1_0_1_0142_20925.jpg parecem frames seguidos do mesmo vídeo), imagens quase iguais caem nos dois lados e a
exatidão em `val` sai otimista.  Divisão por vídeo/contentor seria mais honesta.
"""
from __future__ import annotations

import os
import random
import shutil
from pathlib import Path

from ctrlf.paths import ROOT
SRC = ROOT / "data" / "external" / "waste_container" / "dataset_waste_container"
DST = ROOT / "data" / "crops" / "residuos"
SEED, FRAC = 0, 0.8


def main() -> None:
    if DST.exists():
        shutil.rmtree(DST)
    rng = random.Random(SEED)
    tot_tr = tot_va = 0
    for cdir in sorted(p for p in SRC.iterdir() if p.is_dir()):
        files = sorted(p for p in cdir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"})
        rng.shuffle(files)
        n_tr = max(1, round(len(files) * FRAC))
        if len(files) > 1:
            n_tr = min(n_tr, len(files) - 1)          # pelo menos 1 em val
        for split, chunk in (("train", files[:n_tr]), ("val", files[n_tr:])):
            out = DST / split / cdir.name
            out.mkdir(parents=True, exist_ok=True)
            for f in chunk:
                os.symlink(f, out / f.name)
        tot_tr += n_tr; tot_va += len(files) - n_tr
        print(f"{cdir.name:24s} total {len(files):4d} | train {n_tr:4d} | val {len(files) - n_tr:4d}")
    print(f"\ntrain {tot_tr} | val {tot_va} -> {DST}")


if __name__ == "__main__":
    main()
