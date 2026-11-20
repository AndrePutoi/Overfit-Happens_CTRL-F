"""DINOv2-small afinado para o TIPO de contentor (fluxo) com o waste_container, com divisão TREINO/VALIDAÇÃO POR GRUPO.

    python -m ctrlf.treino.train_residuos_grouped                         # -> models/subclassifier_residuos_v2.pt
    python -m ctrlf.treino.train_residuos_grouped --device cpu --max-per-class 8 --epochs 1 --out /tmp/x.pt   # fumo

Porquê uma v2: o treino antigo (models/subclassifier_residuos.pt, val 0,934) dividiu ao acaso POR IMAGEM, e o dataset tem frames seguidos do
mesmo contentor/percurso, por isso imagens quase iguais caíram nos dois lados e a exatidão sai otimista (aviso no split_residuos.py).
Aqui o GRUPO é o 1.º campo do nome do ficheiro (0124_1_0_1_0142_20925.jpg -> "0124", 66 grupos): um grupo inteiro fica só no treino ou só na
validação (~20% das imagens de cada classe em validação, pelo menos 1 grupo por classe quando há >= 2). Continua a ser o MESMO domínio
(camiões, contentores de corpo colorido): não mede a transferência para o Porto.

Aumentos: recorte aleatório mais agressivo, flip horizontal (contentores não têm sentido esquerda/direita), brilho/contraste/saturação e 10% de
tons de cinza (no Porto o corpo é cinzento e a cor do tipo está na ranhura: queremos que o modelo não dependa só do corpo colorido).
Seleção da melhor época por exatidão EQUILIBRADA (média da recolha por classe), não pela global, que o `default` (949 imagens) domina.
Classes raras (biodegradable 19 imagens em 3 grupos, oil 56 em 4): os números de validação delas valem muito pouco.
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import torch
from PIL import Image
from torch import nn
from torch.utils.data import DataLoader, Dataset
from torchvision import transforms

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
sys.path.insert(0, str(ROOT))
from ctrlf.detection.subclass.sign_classifier import MEAN, STD, TF_EVAL, Net  # noqa: E402

SRC = ROOT / "data" / "external" / "waste_container" / "dataset_waste_container"
TF_TRAIN_V2 = transforms.Compose([
    transforms.RandomResizedCrop(224, scale=(0.5, 1.0), ratio=(0.6, 1.6)),
    transforms.RandomHorizontalFlip(),
    transforms.ColorJitter(0.4, 0.4, 0.4, 0.02),
    transforms.RandomGrayscale(0.1),
    transforms.RandomRotation(8),
    transforms.ToTensor(), transforms.Normalize(MEAN, STD)])


class Crops(Dataset):
    def __init__(self, items: list[tuple[Path, int, str]], tf):
        self.items, self.tf = items, tf

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, y, _ = self.items[i]
        return self.tf(Image.open(p).convert("RGB")), y


def collect(max_per_class: int = 0, seed: int = 0):
    classes = sorted(d.name for d in SRC.iterdir() if d.is_dir())
    items = []
    rng = random.Random(seed)
    for y, c in enumerate(classes):
        files = sorted((SRC / c).glob("*.jpg"))
        if max_per_class:
            rng.shuffle(files)
            files = files[:max_per_class]
        items += [(f, y, f.name.split("_")[0]) for f in files]
    return classes, items


def split_by_group(items, n_classes: int, val_frac: float = 0.2, seed: int = 0):
    """Grupos inteiros para validação, por classe. Um grupo pode ter várias classes (poucos): fica onde o 1.º sorteio o puser."""
    rng = random.Random(seed)
    by_cls = defaultdict(lambda: defaultdict(list))
    for it in items:
        by_cls[it[1]][it[2]].append(it)
    val_groups: set[str] = set()
    for y in range(n_classes):
        groups = list(by_cls[y])
        rng.shuffle(groups)
        n_cls = sum(len(by_cls[y][g]) for g in groups)
        got = sum(len(by_cls[y][g]) for g in groups if g in val_groups)          # já vem de grupos escolhidos para outras classes
        for g in groups:
            if len(groups) < 2 or got >= val_frac * n_cls:
                break
            if g not in val_groups:
                val_groups.add(g); got += len(by_cls[y][g])
    tr = [it for it in items if it[2] not in val_groups]
    va = [it for it in items if it[2] in val_groups]
    return tr, va, sorted(val_groups)


def evaluate(net, loader, dev, n_classes):
    net.eval()
    conf = np.zeros((n_classes, n_classes), int)
    with torch.no_grad():
        for x, y in loader:
            pred = net(x.to(dev)).argmax(1).cpu().numpy()
            for t, p in zip(y.numpy(), pred):
                conf[t, p] += 1
    sup = conf.sum(1)
    rec = np.where(sup > 0, conf.diagonal() / np.maximum(sup, 1), np.nan)
    return conf, rec, float(conf.diagonal().sum() / max(conf.sum(), 1)), float(np.nanmean(rec))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=8)
    ap.add_argument("--freeze-epochs", type=int, default=2)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--lr", type=float, default=2e-5)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    ap.add_argument("--max-per-class", type=int, default=0, help="só para testes de fumo")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "subclassifier_residuos_v2.pt")
    ap.add_argument("--report", type=Path, default=ROOT / "reports" / "residuos_v2.json")
    a = ap.parse_args()
    torch.manual_seed(a.seed)
    dev = a.device

    classes, items = collect(a.max_per_class, a.seed)
    tr, va, val_groups = split_by_group(items, len(classes), a.val_frac, a.seed)
    ctr, cva = Counter(y for _, y, _ in tr), Counter(y for _, y, _ in va)
    print(f"{len(tr)} treino / {len(va)} validação | {len({g for *_, g in tr})} grupos treino / {len(val_groups)} grupos validação")
    for y, c in enumerate(classes):
        print(f"  {c:24s} treino {ctr[y]:4d} | validação {cva[y]:4d}")
    if any(cva[y] == 0 for y in range(len(classes))):
        print("AVISO: há classes sem validação (só 1 grupo): a exatidão delas não é medida.")

    counts = torch.tensor([ctr[y] for y in range(len(classes))], dtype=torch.float32)
    w = (counts.sum() / (len(classes) * counts.clamp(min=1))).to(dev)
    nw = 4 if dev == "cuda" else 0
    tl = DataLoader(Crops(tr, TF_TRAIN_V2), a.batch, shuffle=True, num_workers=nw, drop_last=len(tr) > a.batch)
    vl = DataLoader(Crops(va, TF_EVAL), a.batch, num_workers=min(2, nw))

    net = Net(len(classes)).to(dev)
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    best, history = -1.0, []
    for ep in range(a.epochs):
        frozen = ep < a.freeze_epochs
        for p in net.backbone.parameters():
            p.requires_grad = not frozen
        params = [{"params": net.head.parameters(), "lr": a.lr * 10}]
        if not frozen:
            params.append({"params": net.backbone.parameters(), "lr": a.lr})
        opt = torch.optim.AdamW(params, weight_decay=0.05)
        net.train()
        for x, y in tl:
            x, y = x.to(dev), y.to(dev)
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                loss = nn.functional.cross_entropy(net(x), y, weight=w, label_smoothing=0.05)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
        conf, rec, acc, bal = evaluate(net, vl, dev, len(classes))
        history.append({"epoca": ep + 1, "acc": round(acc, 4), "acc_equilibrada": round(bal, 4)})
        print(f"época {ep + 1}/{a.epochs} {'(backbone congelado)' if frozen else ''}  acc {acc:.3f}  equilibrada {bal:.3f}  "
              + "  ".join(f"{c.replace('container_', '')}:{rec[i]:.2f}" for i, c in enumerate(classes)), flush=True)
        if bal >= best:
            best = bal
            a.out.parent.mkdir(parents=True, exist_ok=True)
            torch.save({"state": net.state_dict(), "labels": classes,
                        "meta": {"name": "residuos_v2", "split": "por grupo (1.º campo do nome)", "epoch": ep + 1, "val_acc": acc, "val_acc_equilibrada": bal,
                                 "n_train": len(tr), "n_val": len(va), "train_counts": [int(c) for c in counts.tolist()]}}, a.out)
            best_conf, best_rec, best_acc = conf, rec, acc
    rep = {"modelo": str(a.out.relative_to(ROOT)) if a.out.is_relative_to(ROOT) else str(a.out), "divisao": "por grupo", "grupos_validacao": val_groups,
           "n_treino": len(tr), "n_validacao": len(va), "classes": classes,
           "validacao_por_classe": {c: {"imagens": int(cva[i]), "recolha": None if np.isnan(best_rec[i]) else round(float(best_rec[i]), 3)} for i, c in enumerate(classes)},
           "acc_global": round(best_acc, 4), "acc_equilibrada": round(best, 4), "matriz_confusao(linhas=real)": best_conf.tolist(), "historico": history,
           "nota": "validação do MESMO domínio (camiões); não mede a transferência para o Porto. Classes raras: poucos grupos, números pouco fiáveis. "
                   "O modelo v1 (val 0,934) usou divisão aleatória por imagem: otimista."}
    a.report.parent.mkdir(parents=True, exist_ok=True)
    a.report.write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nmelhor exatidão equilibrada {best:.3f} (global {best_acc:.3f}) -> {a.out}\nrelatório: {a.report}")


if __name__ == "__main__":
    main()
