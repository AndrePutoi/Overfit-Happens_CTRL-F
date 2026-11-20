"""Afinar o RF-DETR no dataset COCO (4 classes de configs/classes.yaml), seguro para 6 GB.

    python -m ctrlf.treino.train_detector --dataset data/aveiro_coco --size small --epochs 30

O dataset tem de ter a estrutura (formato COCO, como o exporta o CVAT/Roboflow):
    data/aveiro_coco/train/_annotations.coco.json + imagens
    data/aveiro_coco/valid/_annotations.coco.json + imagens
    data/aveiro_coco/test/_annotations.coco.json  + imagens   (pode ser cópia de valid; a avaliação a sério é à parte)

Medido nesta máquina (RTX 3060 Laptop 6 GB), pico de memória a treinar:
    small  batch 4 x accum 4 -> 3.1 GiB        (recomendado)
Se falhar por memória: --batch 2 --accum 8.

Saída: models/detector/checkpoint_best_total.pth  (lido por inference.Detector).
Imagens de treino de ruas: o RF-DETR já faz augmentations (flip horizontal incluído; para
sinais com setas/sentidos isto é aceitável no detetor — o TIPO decide o sub-classificador).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.common.rfdetr_patch import apply as patch_rfdetr  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--size", choices=["nano", "small", "medium"], default="small")
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=4)
    ap.add_argument("--accum", type=int, default=4)
    ap.add_argument("--out", default=str(ROOT / "models" / "detector"))
    ap.add_argument("--resume", default=None)
    ap.add_argument("--resolution", type=int, default=None,
                    help="resolução de entrada do RF-DETR (múltiplo de 32; omissão = a do modelo, 512 no small)."
                         " Mais alta ajuda objetos pequenos (sinais) mas gasta mais memória: baixar --batch")
    a = ap.parse_args()

    import rfdetr
    patch_rfdetr()
    Model = {"nano": rfdetr.RFDETRNano, "small": rfdetr.RFDETRSmall, "medium": rfdetr.RFDETRMedium}[a.size]
    model = Model(**({"resolution": a.resolution} if a.resolution else {}))
    model.train(dataset_dir=a.dataset, epochs=a.epochs, batch_size=a.batch, grad_accum_steps=a.accum,
                output_dir=a.out, num_workers=4, early_stopping=True, tensorboard=False,
                **({"resume": a.resume} if a.resume else {}))
    print("\nPesos em", a.out)


if __name__ == "__main__":
    main()
