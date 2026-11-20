"""Classificador do TIPO do contentor (embalagens, indiferenciado, papel, vidro) treinado SÓ com as anotações do Porto feitas pelo utilizador (sem waste_container).

    python -m ctrlf.treino.train_fluxo4_porto cv    --porto-dir data/crops/fluxo4/porto_final              # dobras por PANORAMA: exatidão honesta e época a usar
    python -m ctrlf.treino.train_fluxo4_porto final --porto-dir data/crops/fluxo4/porto_final --epochs 8   # treina com TODOS os recortes -> classificador_fluxo4.pt

Porquê só o Porto: decisão do utilizador (2026-11-20) — o waste_container tem origem e termos por verificar, e o seu domínio (fotografias de caixotes de perto) não é o das vistas de rua.
Preço: são poucos recortes (627 em 199 imagens na versão final, muito desequilibrados: 387 indiferenciado, 102 embalagens, 79 papel, 59 vidro). Por isso: amostragem
equilibrada por época (e perda SEM pesos de classe: compensar duas vezes anulava o tipo mais frequente), aumentos fortes (os mesmos do classificador de sinais), congelar o backbone na 1.ª época. A exatidão que o `cv` mede é a que se pode esperar em imagens novas do Porto.
O ficheiro guardado tem o MESMO formato do anterior ({state, labels, meta}, mesma ordem de labels): substitui models/classificador_fluxo4.pt sem mexer no código.
Dados: --porto-dir com manifesto.json (file, imagem, grupo, bbox, tipo, classe) e os recortes por tipo (scripts/preparar_lixo_porto_final.py --recortes). Modelo base: facebook/dinov2-small (Hugging Face).
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
from torch import nn
from torch.utils.data import DataLoader, WeightedRandomSampler

from ctrlf.paths import ROOT
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
sys.path.insert(0, str(ROOT))
from ctrlf.detection.subclass.sign_classifier import Net  # noqa: E402
from ctrlf.treino.train_fluxo4 import LABELS, Crops, avaliar, metricas  # noqa: E402
from ctrlf.treino.train_residuos_grouped import TF_TRAIN_V2  # noqa: E402


def carregar(pasta: Path):
    return [(pasta / m["file"], LABELS.index(m["tipo"]), m["grupo"], "porto") for m in json.loads((pasta / "manifesto.json").read_text(encoding="utf-8"))]


def dobras(items, k: int, seed: int):
    """k dobras por panorama (grupo), estratificadas à mão: os grupos com mais recortes das classes raras repartem-se primeiro."""
    rng = random.Random(seed)
    por_grupo = defaultdict(list)
    for it in items:
        por_grupo[it[2]].append(it)
    raridade = {g: sum(1 for it in v if it[1] != LABELS.index("indiferenciado")) for g, v in por_grupo.items()}
    grupos = sorted(por_grupo, key=lambda g: (-raridade[g], rng.random()))
    blocos = [[] for _ in range(k)]
    for i, g in enumerate(grupos):
        blocos[i % k].append(g)
    return [(set(b), [it for g in b for it in por_grupo[g]]) for b in blocos]


def treinar(treino, dev, epochs, freeze, batch=32, lr=2e-5, seed=0, validacao=None):
    torch.manual_seed(seed); random.seed(seed)
    cnt = Counter(it[1] for it in treino)
    # O desequilíbrio compensa-se UMA vez, na amostragem (cada época vê as 4 classes por igual). Compensar também na perda (pesos de classe) contava a dupla e o modelo deixava de
    # prever o tipo mais frequente: 1.ª versão, 0 em 387 `indiferenciado` e exatidão de 16 % (abaixo do acaso). Por isso a perda é SEM pesos.
    pesos = [1.0 / max(cnt[it[1]], 1) for it in treino]                       # amostragem equilibrada por classe em cada época
    sampler = WeightedRandomSampler(pesos, num_samples=max(len(treino), 256), replacement=True)
    tl = DataLoader(Crops(treino, TF_TRAIN_V2), batch, sampler=sampler, num_workers=2 if dev == "cuda" else 0, drop_last=True)
    net = Net(4).to(dev); scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    hist = []
    for ep in range(epochs):
        for p in net.backbone.parameters():
            p.requires_grad = ep >= freeze
        params = [{"params": net.head.parameters(), "lr": lr * 10}] + ([{"params": net.backbone.parameters(), "lr": lr}] if ep >= freeze else [])
        opt = torch.optim.AdamW(params, weight_decay=0.05); net.train()
        for x, y in tl:
            x, y = x.to(dev), y.to(dev)
            with torch.autocast(dev, dtype=torch.float16, enabled=dev == "cuda"):
                loss = nn.functional.cross_entropy(net(x), y, label_smoothing=0.05)
            opt.zero_grad(); scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
        if validacao:
            m = metricas(avaliar(net, validacao, dev), validacao)
            hist.append({"epoca": ep + 1, "acc": m["acc"], "acc_equilibrada": m["acc_equilibrada"]})
            print(f"  época {ep + 1}/{epochs}  validação (panoramas não vistos): acc {m['acc']}  equilibrada {m['acc_equilibrada']}", flush=True)
    return net, hist


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("modo", choices=["cv", "final"])
    ap.add_argument("--porto-dir", type=Path, default=ROOT / "data" / "crops" / "fluxo4" / "porto_final")
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--freeze-epochs", type=int, default=1)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--batch", type=int, default=32, help="baixar (p. ex. 16) se partilhar a GPU com outro treino")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "classificador_fluxo4.pt")
    ap.add_argument("--relatorio", type=Path, default=None, help="onde escrever o JSON do resultado (omissão: reports/fluxo4_porto_<modo>.json)")
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    items = carregar(a.porto_dir)
    print(f"{len(items)} recortes do Porto em {len({it[2] for it in items})} panoramas: {dict(Counter(LABELS[it[1]] for it in items))} | dispositivo {dev}", flush=True)
    res = {"modo": a.modo, "labels": LABELS, "epocas": a.epochs, "n_recortes": len(items), "treino": "SÓ anotações do Porto (sem waste_container)"}
    rel = a.relatorio or ROOT / "reports" / f"fluxo4_porto_{a.modo}.json"
    rel.parent.mkdir(parents=True, exist_ok=True)
    if a.modo == "cv":
        todas_P, todos, hist_dobras = [], [], []
        for k, (gr, fora) in enumerate(dobras(items, a.folds, a.seed), 1):
            dentro = [it for it in items if it[2] not in gr]
            print(f"dobra {k}/{a.folds}: treino {len(dentro)} / validação {len(fora)} ({len(gr)} panoramas)", flush=True)
            net, hist = treinar(dentro, dev, a.epochs, a.freeze_epochs, batch=a.batch, seed=a.seed, validacao=fora)
            P = avaliar(net, fora, dev); todas_P.append(P); todos += fora; hist_dobras.append(hist)
            del net; torch.cuda.empty_cache()
        res["validacao_cruzada"] = metricas(np.vstack(todas_P), todos)
        res["acc_equilibrada_media_por_epoca"] = [round(float(np.mean([h[e]["acc_equilibrada"] for h in hist_dobras])), 3) for e in range(a.epochs)]
        res["nota"] = "dobras por PANORAMA (as 4 vistas e o mesmo local nunca ficam em lados diferentes); é a exatidão esperada em imagens novas do Porto, não de outras cidades"
    else:
        net, _ = treinar(items, dev, a.epochs, a.freeze_epochs, batch=a.batch, seed=a.seed)
        res["recortes_no_treino(NÃO é validação)"] = metricas(avaliar(net, items, dev), items)
        a.out.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state": net.state_dict(), "labels": LABELS, "meta": {"name": "fluxo4", "treino": f"SÓ recortes do Porto anotados pelo utilizador ({len(items)}), sem waste_container", "n_porto": len(items), "epocas": a.epochs}}, a.out)
        print(f"-> {a.out}")
    rel.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in res.items() if k in ("validacao_cruzada", "acc_equilibrada_media_por_epoca")}, ensure_ascii=False)[:1500])


if __name__ == "__main__":
    main()
