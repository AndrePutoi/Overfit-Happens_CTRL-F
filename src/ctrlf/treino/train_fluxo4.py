"""Classificador do TIPO de contentor com 4 classes (indiferenciado, papel, embalagens, vidro): DINOv2-small, o mesmo desenho do classificador dos sinais.

    python -m ctrlf.treino.train_fluxo4 transferencia     # só waste_container -> exatidão nos recortes do Porto (mede a transferência)
    python -m ctrlf.treino.train_fluxo4 loo               # waste_container + recortes do Porto, deixando uma imagem do Porto de fora de cada vez
    python -m ctrlf.treino.train_fluxo4 final             # waste_container + TODOS os recortes do Porto -> models/classificador_fluxo4.pt

Dados: waste_container SÓ com os 4 labels pedidos (container_default -> indiferenciado, blue -> papel, yellow -> embalagens, green -> verde/vidro; battery, biodegradable e oil ficam de fora)
e os recortes do Porto com tipo (data/crops/fluxo4/porto, de scripts/preparar_lixo_v3.py). O waste_container divide-se POR GRUPO (1.º campo do nome); os recortes do Porto por IMAGEM/panorama.
Os recortes do Porto são poucos: entram sobreamostrados (`--porto-frac` da amostra de cada época) com os mesmos aumentos. Escolhe-se a época pela exatidão equilibrada no waste_container
(no `final`) ou pela última (no `loo`, onde não há validação de onde escolher). Honestidade: com ~25 recortes do Porto a exatidão no Porto vale muito pouco.
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
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
sys.path.insert(0, str(ROOT))
from ctrlf.detection.subclass.sign_classifier import TF_EVAL, Net  # noqa: E402
from ctrlf.treino.train_residuos_grouped import TF_TRAIN_V2, split_by_group  # noqa: E402

LABELS = ["embalagens", "indiferenciado", "papel", "vidro"]
WC = ROOT / "data" / "external" / "waste_container" / "dataset_waste_container"
WC_MAP = {"container_default": "indiferenciado", "container_blue": "papel", "container_yellow": "embalagens", "container_green": "vidro"}
PORTO = ROOT / "data" / "crops" / "fluxo4" / "porto"


class Crops(Dataset):
    def __init__(self, items, tf):
        self.items, self.tf = items, tf

    def __len__(self):
        return len(self.items)

    def __getitem__(self, i):
        p, y, _, _ = self.items[i]
        return self.tf(Image.open(p).convert("RGB")), y


def coletar_wc(cap: int, seed: int):
    rng = random.Random(seed); out = []
    for c, t in WC_MAP.items():
        fs = sorted((WC / c).glob("*.jpg"))
        if cap:
            rng.shuffle(fs); fs = fs[:cap]
        out += [(f, LABELS.index(t), f.name.split("_")[0], "wc") for f in fs]
    return out


def coletar_porto(pasta: Path | None = None):
    pasta = pasta or PORTO
    return [(pasta / m["file"], LABELS.index(m["tipo"]), m["imagem"], "porto") for m in json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))]


def avaliar(net, items, dev):
    net.eval(); P = []
    with torch.no_grad():
        for i in range(0, len(items), 64):
            x = torch.stack([TF_EVAL(Image.open(p).convert("RGB")) for p, *_ in items[i:i + 64]]).to(dev)
            P += torch.softmax(net(x).float(), 1).cpu().tolist()
    return np.array(P)


def metricas(P, items):
    y = np.array([it[1] for it in items]); pred = P.argmax(1)
    conf = np.zeros((4, 4), int)
    for t, p in zip(y, pred):
        conf[t, p] += 1
    sup = conf.sum(1); rec = np.where(sup > 0, conf.diagonal() / np.maximum(sup, 1), np.nan)
    return {"n": int(len(y)), "acc": round(float((pred == y).mean()), 3) if len(y) else None, "acc_equilibrada": round(float(np.nanmean(rec)), 3) if len(y) else None,
            "recolha": {LABELS[i]: (None if np.isnan(rec[i]) else round(float(rec[i]), 3)) for i in range(4)}, "confusao(linhas=real)": conf.tolist()}


def treinar(treino, validacao_wc, dev, epochs, freeze, porto_frac, batch=32, lr=2e-5, seed=0, escolher_melhor=True):
    torch.manual_seed(seed); random.seed(seed)
    n_wc = sum(1 for it in treino if it[3] == "wc"); n_po = sum(1 for it in treino if it[3] == "porto")
    cnt = Counter(it[1] for it in treino if it[3] == "wc")
    w_cls = torch.tensor([len(treino) / (4 * max(cnt[y], 1)) for y in range(4)], dtype=torch.float32, device=dev)
    # amostragem: cada época tira n_wc exemplos; os do Porto pesam `porto_frac` do total, o resto reparte-se pelo waste_container (classes equilibradas)
    pesos = []
    for it in treino:
        if it[3] == "porto":
            pesos.append(porto_frac / max(n_po, 1))
        else:
            pesos.append((1 - porto_frac) / max(n_wc, 1) if n_po else 1 / n_wc)
    sampler = WeightedRandomSampler(pesos, num_samples=max(n_wc, 200), replacement=True)
    nw = 2 if dev == "cuda" else 0
    tl = DataLoader(Crops(treino, TF_TRAIN_V2), batch, sampler=sampler, num_workers=nw, drop_last=True)
    net = Net(4).to(dev); scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    best, best_state, hist = -1.0, None, []
    for ep in range(epochs):
        for p in net.backbone.parameters():
            p.requires_grad = ep >= freeze
        params = [{"params": net.head.parameters(), "lr": lr * 10}] + ([{"params": net.backbone.parameters(), "lr": lr}] if ep >= freeze else [])
        opt = torch.optim.AdamW(params, weight_decay=0.05); net.train()
        for x, y in tl:
            x, y = x.to(dev), y.to(dev)
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                loss = nn.functional.cross_entropy(net(x), y, weight=w_cls, label_smoothing=0.05)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
        m = metricas(avaliar(net, validacao_wc, dev), validacao_wc) if validacao_wc else {"acc": None, "acc_equilibrada": 0.0}
        hist.append({"epoca": ep + 1, "val_wc_acc": m["acc"], "val_wc_equilibrada": m["acc_equilibrada"]})
        print(f"  época {ep + 1}/{epochs}  val waste_container: acc {m['acc']}  equilibrada {m['acc_equilibrada']}", flush=True)
        if (not escolher_melhor) or m["acc_equilibrada"] >= best:
            best = m["acc_equilibrada"]; best_state = {k: v.detach().cpu().clone() for k, v in net.state_dict().items()}
    net.load_state_dict(best_state)
    return net, hist, best


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["transferencia", "loo", "final"])
    ap.add_argument("--epochs", type=int, default=7)
    ap.add_argument("--freeze-epochs", type=int, default=1)
    ap.add_argument("--cap", type=int, default=0, help="máx. imagens por classe do waste_container (0 = todas)")
    ap.add_argument("--porto-frac", type=float, default=0.15)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "classificador_fluxo4.pt")
    ap.add_argument("--porto-dir", type=Path, default=None, help="pasta dos recortes do Porto com manifesto.json (omissão: data/crops/fluxo4/porto; para as anotações FINAIS: data/crops/fluxo4/porto_final)")
    ap.add_argument("--tag", default="", help="sufixo dos relatórios (ex.: v2) para não escrever por cima dos anteriores")
    ap.add_argument("--folds", type=int, default=0, help="loo: nº de dobras por imagem (0 = uma imagem de fora de cada vez)")
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    wc = coletar_wc(a.cap, a.seed); porto = coletar_porto(a.porto_dir)
    tr_wc, va_wc, grupos_val = split_by_group([(p, y, g) for p, y, g, _ in wc], 4, 0.2, a.seed)
    tr_wc = [(p, y, g, "wc") for p, y, g in tr_wc]; va_wc = [(p, y, g, "wc") for p, y, g in va_wc]
    print(f"waste_container: {len(tr_wc)} treino / {len(va_wc)} validação ({dict(Counter(LABELS[y] for _, y, *_ in tr_wc))}); recortes do Porto: {len(porto)} {dict(Counter(LABELS[y] for _, y, *_ in porto))} em {len({g for *_, g, _ in porto})} imagens", flush=True)
    res = {"modo": a.modo, "labels": LABELS, "epocas": a.epochs, "porto_frac": a.porto_frac, "n_wc_treino": len(tr_wc), "n_wc_val": len(va_wc), "n_porto": len(porto)}
    (ROOT / "reports").mkdir(exist_ok=True)

    if a.modo == "transferencia":
        net, hist, best = treinar(tr_wc, va_wc, dev, a.epochs, a.freeze_epochs, 0.0, seed=a.seed)
        res["val_waste_container"] = metricas(avaliar(net, va_wc, dev), va_wc); res["porto_25_recortes(transferencia)"] = metricas(avaliar(net, porto, dev), porto); res["historico"] = hist
        # referência: o classificador antigo de 7 labels (v2) nos mesmos recortes, mapeado para os 4 (battery/oil/biodegradable contam como erro)
        from ctrlf.detection.subclass.sign_classifier import load_classifier
        old = load_classifier(ROOT / "models" / "subclassifier_residuos_v2.pt", dev)
        P7 = avaliar(old.net, porto, dev)
        mapa = {i: (LABELS.index(WC_MAP[l]) if l in WC_MAP else -1) for i, l in enumerate(old.labels)}
        pred = [mapa[int(p)] for p in P7.argmax(1)]; y = [it[1] for it in porto]
        res["porto_25_recortes(classificador_antigo_de_7_labels)"] = {"acc": round(float(np.mean([a_ == b_ for a_, b_ in zip(pred, y)])), 3), "previu_label_fora_dos_4": int(sum(p == -1 for p in pred))}
        (ROOT / "reports" / f"fluxo4_transferencia{a.tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    elif a.modo == "loo":
        imgs = sorted({g for *_, g, _ in porto})
        if a.folds:                                                    # dobras de imagens (por nº de recortes, em rodízio) em vez de uma imagem de cada vez
            por_img = sorted(imgs, key=lambda g: -sum(1 for it in porto if it[2] == g))
            blocos = [[] for _ in range(a.folds)]
            for i, g in enumerate(por_img):
                blocos[i % a.folds].append(g)
        else:
            blocos = [[g] for g in imgs]
        todas_P, todas_it, folds = [], [], []
        for k, bloco in enumerate(blocos, 1):
            im = "+".join(bloco)
            print(f"dobra {k}/{len(blocos)}: {len(bloco)} imagem(ns)", flush=True)
            fora = [it for it in porto if it[2] in bloco]; dentro = [it for it in porto if it[2] not in bloco]
            net, hist, _ = treinar(tr_wc + dentro, va_wc, dev, a.epochs, a.freeze_epochs, a.porto_frac, seed=a.seed, escolher_melhor=False)
            P = avaliar(net, fora, dev); todas_P.append(P); todas_it += fora
            folds.append({"imagem": im, **metricas(P, fora)}); print("   ", folds[-1]["acc"], flush=True)
            del net; torch.cuda.empty_cache()
        res["dobras"] = folds; res["porto_25_recortes(deixar_uma_imagem_de_fora)"] = metricas(np.vstack(todas_P), todas_it)
        (ROOT / "reports" / f"fluxo4_loo{a.tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    else:
        net, hist, best = treinar(tr_wc + porto, va_wc, dev, a.epochs, a.freeze_epochs, a.porto_frac, seed=a.seed)
        res["val_waste_container"] = metricas(avaliar(net, va_wc, dev), va_wc); res["porto_25_recortes(no_treino: NÃO é validação)"] = metricas(avaliar(net, porto, dev), porto); res["historico"] = hist
        a.out.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state": net.state_dict(), "labels": LABELS, "meta": {"name": "fluxo4", "treino": "waste_container (4 labels, por grupo) + 25 recortes do Porto sobreamostrados", "val_acc_equilibrada": best,
                                                                           "n_wc_treino": len(tr_wc), "n_porto": len(porto), "porto_frac": a.porto_frac}}, a.out)
        (ROOT / "reports" / f"fluxo4_final{a.tag}.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"-> {a.out}")
    print(json.dumps({k: v for k, v in res.items() if k.startswith(("porto", "val_"))}, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
