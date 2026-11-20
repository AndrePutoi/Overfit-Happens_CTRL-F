"""Sub-classificador sobre RECORTES, com backbone DINOv2-small  (stage 2 do plano).

Serve para o tipo de sinal (stop/cedencia/limite_velocidade/outro) e para o tipo
de contentor (subterraneo/ilha_reciclagem/indiferenciado).

Estrutura de dados (uma pasta por classe):
    data/crops/sinal/train/stop/*.jpg        data/crops/sinal/val/stop/*.jpg
    data/crops/sinal/train/cedencia/*.jpg    ...
    data/crops/contentor/train/subterraneo/*.jpg ...

Treinar (cabe em 6 GB: pico ~1.8 GiB com batch 32):
    python -m ctrlf.detection.subclass.sign_classifier train sinal     --epochs 8
    python -m ctrlf.detection.subclass.sign_classifier train contentor --epochs 12

Fase 1 (--freeze, por omissão nas primeiras épocas): só a cabeça linear -> funciona com
poucas dezenas de exemplos por classe.  Fase 2 descongela o backbone com lr baixo.
Saída: models/subclassifier_<classe>.pt  (lido automaticamente por inference.Detector).
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader
from torchvision import datasets, transforms

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))

MEAN, STD = (0.485, 0.456, 0.406), (0.229, 0.224, 0.225)
TF_EVAL = transforms.Compose([transforms.Resize((224, 224)), transforms.ToTensor(), transforms.Normalize(MEAN, STD)])
TF_TRAIN = transforms.Compose([
    transforms.RandomResizedCrop(224, scale=(0.7, 1.0), ratio=(0.8, 1.25)),
    transforms.ColorJitter(0.3, 0.3, 0.3, 0.02),
    transforms.RandomRotation(8),
    transforms.ToTensor(), transforms.Normalize(MEAN, STD)])   # SEM flip horizontal: estragaria setas/sentidos


class Net(nn.Module):
    def __init__(self, n_classes: int):
        super().__init__()
        from transformers import AutoModel
        self.backbone = AutoModel.from_pretrained("facebook/dinov2-small")
        self.head = nn.Linear(384, n_classes)

    def forward(self, x):
        return self.head(self.backbone(pixel_values=x).pooler_output)


class Loaded:
    def __init__(self, net: Net, labels: list[str], device: str):
        self.net, self.labels, self.device = net.to(device).eval(), labels, device

    @torch.no_grad()
    def predict(self, crops: list[Image.Image]) -> list[tuple[str, float]]:
        x = torch.stack([TF_EVAL(c.convert("RGB")) for c in crops]).to(self.device)
        p = torch.softmax(self.net(x).float(), dim=1)
        s, i = p.max(1)
        return [(self.labels[int(k)], float(v)) for k, v in zip(i, s)]


def read_checkpoint(path: Path, expected_labels: list[str] | None = None) -> dict:
    """Lê e valida um checkpoint {state, labels[, meta]} sem construir a rede.  ValueError se incoerente."""
    path = Path(path)
    if not path.is_file():
        raise ValueError(f"{path}: checkpoint não existe")
    ck = torch.load(path, map_location="cpu", weights_only=True)
    if not isinstance(ck, dict) or "state" not in ck or "labels" not in ck:
        raise ValueError(f"{path}: checkpoint sem 'state'/'labels'")
    labels = list(ck["labels"])
    if expected_labels is not None and labels != list(expected_labels):
        raise ValueError(f"{path}: rótulos do checkpoint {labels} != esperados {list(expected_labels)}")
    w = ck["state"].get("head.weight")
    if w is None or tuple(w.shape) != (len(labels), 384):
        raise ValueError(f"{path}: head.weight com forma {None if w is None else tuple(w.shape)} "
                         f"incompatível com {len(labels)} rótulos")
    return ck


def load_classifier(path: Path, device: str = "cuda", expected_labels: list[str] | None = None) -> Loaded:
    ck = read_checkpoint(path, expected_labels)
    net = Net(len(ck["labels"])); net.load_state_dict(ck["state"])
    return Loaded(net, list(ck["labels"]), device)


def train(family: str, epochs: int, batch: int, lr: float, freeze_epochs: int,
          data: Path | None = None, out: Path | None = None, synthetic: bool = False) -> None:
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    base = Path(data) if data else ROOT / "data" / "crops" / family
    out = Path(out) if out else ROOT / "models" / f"subclassifier_{family}.pt"
    if not (base / "train").exists():
        sys.exit(f"Faltam recortes em {base}/train/<classe>/*.jpg (ver docstring).")
    tag = "SINTÉTICO " if synthetic else ""
    torch.manual_seed(0)
    tr = datasets.ImageFolder(base / "train", TF_TRAIN)
    va = datasets.ImageFolder(base / "val", TF_EVAL)
    labels = tr.classes
    if va.classes != labels:
        sys.exit(f"classes de val {va.classes} != treino {labels}")
    print(f"{tag}{family}: treino {len(tr)} recortes, val {len(va)}, classes {labels}")
    # Pesos inversos à frequência: classes raras (ex.: "stop") contam mais.
    counts = torch.bincount(torch.tensor(tr.targets), minlength=len(labels)).float()
    w = (counts.sum() / (len(labels) * counts.clamp(min=1))).to(dev)
    tl = DataLoader(tr, batch, shuffle=True, num_workers=4, drop_last=len(tr) > batch)
    vl = DataLoader(va, batch, num_workers=2)

    net = Net(len(labels)).to(dev)
    scaler = torch.amp.GradScaler()
    best = 0.0
    for ep in range(epochs):
        frozen = ep < freeze_epochs
        for p in net.backbone.parameters():
            p.requires_grad = not frozen
        params = [{"params": net.head.parameters(), "lr": lr * 10}]
        if not frozen:
            params.append({"params": net.backbone.parameters(), "lr": lr})
        opt = torch.optim.AdamW(params, weight_decay=0.05)
        net.train()
        for x, y in tl:
            x, y = x.to(dev), y.to(dev)
            with torch.autocast(dev, dtype=torch.float16):
                loss = nn.functional.cross_entropy(net(x), y, weight=w, label_smoothing=0.05)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
        net.eval(); ok = n = 0
        per = torch.zeros(len(labels)); tot = torch.zeros(len(labels))
        with torch.no_grad():
            for x, y in vl:
                pred = net(x.to(dev)).argmax(1).cpu()
                ok += (pred == y).sum().item(); n += len(y)
                for t, pr in zip(y, pred):
                    tot[t] += 1; per[t] += int(t == pr)
        acc = ok / max(n, 1)
        print(f"{tag}época {ep+1}/{epochs} {'(backbone congelado)' if frozen else ''}  val acc {acc:.3f}  "
              + "  ".join(f"{l}:{per[i]/max(tot[i],1):.2f}" for i, l in enumerate(labels)))
        if acc >= best:
            best = acc
            out.parent.mkdir(parents=True, exist_ok=True)
            meta = {"name": family, "synthetic": synthetic, "data": str(base), "epoch": ep + 1, "val_acc": acc,
                    "n_train": len(tr), "n_val": len(va),
                    "train_counts": [int(c) for c in counts.tolist()]}
            torch.save({"state": net.state_dict(), "labels": labels, "meta": meta}, out)
    print(f"{tag}melhor val acc {best:.3f} -> {out}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["train"])
    ap.add_argument("family", help="nome do modelo (ex.: sinal, contentor, router, esp_circular_vermelho)")
    ap.add_argument("--epochs", type=int, default=8); ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-5); ap.add_argument("--freeze-epochs", type=int, default=2)
    ap.add_argument("--data", type=Path, help="pasta com train/ e val/ (omissão: data/crops/<nome>)")
    ap.add_argument("--out", type=Path, help="checkpoint (omissão: models/subclassifier_<nome>.pt)")
    ap.add_argument("--synthetic", action="store_true", help="marca o checkpoint e os logs como SINTÉTICO")
    a = ap.parse_args()
    train(a.family, a.epochs, a.batch, a.lr, a.freeze_epochs, a.data, a.out, a.synthetic)
