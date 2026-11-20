"""Ensaio SINTÉTICO da hierarquia de sinais: gera recortes desenhados, treina router + 1 especialista, grava manifesto.

    python -m ctrlf.treino.hier_synthetic make-data      # data/crops/hier_sintetico/  (ignorado pelo Git)
    python -m ctrlf.treino.hier_synthetic train          # models/hier_sinal_sintetico/{router,esp_*}.pt + manifest.json

Porquê sintético: não há recortes reais rotulados nesta máquina e a licença do GTSRB ainda não foi
confirmada pela equipa (plano v2, §7.1/§7.4).  Isto prova que o mecanismo treina, grava, recarrega e
encaminha.  NÃO prova que classifica sinais reais; nenhuma accuracy daqui é um resultado de classificação.

O manifesto é gravado em models/hier_sinal_sintetico/ e marcado "synthetic": true, por isso NÃO é ativado
pelo Detector por omissão (que só procura models/hier_sinal/manifest.json e recusa manifestos sintéticos).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import random
import shutil
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "crops" / "hier_sintetico"
OUT = ROOT / "models" / "hier_sinal_sintetico"

# folha verdadeira (só para os dados sintéticos) -> grupo visual do router
TRUTH = {
    "limite_velocidade_30": "circular_vermelho",
    "limite_velocidade_50": "circular_vermelho",
    "stop": "octogono_vermelho",
    "cedencia_passagem": "triangulo_invertido",
    "perigo_generico": "triangulo_perigo",        # sem especialista -> saída esperada "unknown"
    "obrigacao_generico": "circular_azul",        # sem especialista -> saída esperada "unknown"
}
SPECIALIST = "esp_circular_vermelho"
MANIFEST = {
    "version": 1,
    "synthetic": True,
    "note": "Treinado com recortes SINTÉTICOS desenhados (detection/training/hier_synthetic.py). Não usar como resultado.",
    "router": {"checkpoint": "router.pt",
               "labels": ["circular_azul", "circular_vermelho", "octogono_vermelho", "triangulo_invertido",
                          "triangulo_perigo"]},
    "groups": {
        "circular_vermelho": {"family": "proibicao_restricao", "specialist": SPECIALIST},
        "octogono_vermelho": {"family": "prioridade_paragem", "leaf": "stop"},
        "triangulo_invertido": {"family": "prioridade_paragem", "leaf": "cedencia_passagem"},
        "triangulo_perigo": {"family": "perigo"},
        "circular_azul": {"family": "obrigacao"},
    },
    "specialists": {SPECIALIST: {"checkpoint": f"{SPECIALIST}.pt",
                                 "labels": ["limite_velocidade_30", "limite_velocidade_50"]}},
}
SPLITS = {"train": 80, "val": 20, "test": 40}          # por folha verdadeira
SPLIT_SEED = {"train": 1_000_000, "val": 2_000_000, "test": 3_000_000}
RED, WHITE, BLACK, BLUE, YELLOW = (200, 20, 30), (245, 245, 245), (15, 15, 15), (20, 70, 170), (240, 200, 20)
S = 256                                                  # desenha a 2x e reduz para 128


def _font(size):
    return ImageFont.load_default(size=size)


def _poly(n, r, rot=0.0, c=(S / 2, S / 2)):
    return [(c[0] + r * math.cos(rot + 2 * math.pi * k / n), c[1] + r * math.sin(rot + 2 * math.pi * k / n))
            for k in range(n)]


def _text(d, txt, size, fill):
    f = _font(size)
    b = d.textbbox((0, 0), txt, font=f)
    d.text(((S - (b[2] - b[0])) / 2 - b[0], (S - (b[3] - b[1])) / 2 - b[1]), txt, font=f, fill=fill)


def draw_sign(leaf: str, rng: random.Random) -> Image.Image:
    sign = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(sign)
    r = S * 0.46
    if leaf.startswith("limite_velocidade_"):
        d.ellipse([S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r], fill=RED)
        ri = r * 0.78
        d.ellipse([S / 2 - ri, S / 2 - ri, S / 2 + ri, S / 2 + ri], fill=WHITE)
        _text(d, leaf.rsplit("_", 1)[1], int(S * 0.36), BLACK)
    elif leaf == "stop":
        d.polygon(_poly(8, r, math.pi / 8), fill=WHITE)
        d.polygon(_poly(8, r * 0.92, math.pi / 8), fill=RED)
        _text(d, "STOP", int(S * 0.22), WHITE)
    elif leaf == "cedencia_passagem":
        d.polygon(_poly(3, r, math.pi / 2), fill=RED)
        d.polygon(_poly(3, r * 0.62, math.pi / 2), fill=WHITE)
    elif leaf == "perigo_generico":
        d.polygon(_poly(3, r, -math.pi / 2), fill=RED)
        d.polygon(_poly(3, r * 0.62, -math.pi / 2), fill=WHITE)
        _text(d, rng.choice(["!", "?", "~"]), int(S * 0.2), BLACK)
    elif leaf == "obrigacao_generico":
        d.ellipse([S / 2 - r, S / 2 - r, S / 2 + r, S / 2 + r], fill=BLUE)
        a = rng.choice([0, 90, 180, 270])
        arrow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
        ad = ImageDraw.Draw(arrow)
        ad.rectangle([S * 0.45, S * 0.38, S * 0.55, S * 0.72], fill=WHITE)
        ad.polygon([(S * 0.32, S * 0.42), (S * 0.68, S * 0.42), (S * 0.5, S * 0.2)], fill=WHITE)
        sign.alpha_composite(arrow.rotate(a))
    else:
        raise ValueError(leaf)
    return sign


def render(leaf: str, seed: int) -> Image.Image:
    rng = random.Random(seed)
    bg = Image.new("RGB", (S, S), tuple(rng.randint(40, 220) for _ in range(3)))
    bd = ImageDraw.Draw(bg)
    for _ in range(rng.randint(2, 6)):                      # fundo com retângulos aleatórios (não-sinal)
        x, y = rng.randint(0, S), rng.randint(0, S)
        bd.rectangle([x, y, x + rng.randint(20, 120), y + rng.randint(20, 120)],
                     fill=tuple(rng.randint(0, 255) for _ in range(3)))
    sign = draw_sign(leaf, rng).rotate(rng.uniform(-10, 10), resample=Image.BICUBIC)
    sc = rng.uniform(0.6, 0.95)
    sz = int(S * sc)
    sign = sign.resize((sz, sz), Image.BICUBIC)
    ox, oy = rng.randint(0, S - sz), rng.randint(0, S - sz)
    bg.paste(sign, (ox, oy), sign)
    if rng.random() < 0.5:
        bg = bg.filter(ImageFilter.GaussianBlur(rng.uniform(0.3, 1.5)))
    f = rng.uniform(0.6, 1.3)
    bg = bg.point(lambda v: max(0, min(255, int(v * f))))
    return bg.resize((128, 128), Image.BILINEAR)


def make_data() -> dict:
    if DATA.exists():
        shutil.rmtree(DATA)
    hashes: dict[str, str] = {}
    counts = {}
    for split, n in SPLITS.items():
        for li, (leaf, group) in enumerate(TRUTH.items()):
            for i in range(n):
                img = render(leaf, SPLIT_SEED[split] + li * 10_000 + i)
                h = hashlib.md5(img.tobytes()).hexdigest()
                if h in hashes:
                    raise RuntimeError(f"imagem repetida {split}/{leaf}/{i} == {hashes[h]}")
                hashes[h] = f"{split}/{leaf}/{i}"
                name = f"{leaf}_{i:03d}.png"
                targets = [DATA / "router" / split / group, DATA / "cascade" / split / leaf]
                if group == "circular_vermelho":
                    targets.append(DATA / SPECIALIST / split / leaf)
                for t in targets:
                    t.mkdir(parents=True, exist_ok=True)
                    img.save(t / name)
                counts[f"{split}/{leaf}"] = counts.get(f"{split}/{leaf}", 0) + 1
    info = {"synthetic": True, "splits": SPLITS, "seeds": SPLIT_SEED, "counts": counts,
            "unique_images": len(hashes), "cross_split_duplicates": 0}
    (DATA / "dataset_info.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
    print(json.dumps(info))
    return info


def train(epochs: int, freeze: int) -> None:
    from ctrlf.detection.subclass.sign_classifier import train as train_clf
    OUT.mkdir(parents=True, exist_ok=True)
    train_clf("router", epochs, 32, 2e-5, freeze, DATA / "router", OUT / "router.pt", synthetic=True)
    train_clf(SPECIALIST, epochs, 32, 2e-5, freeze, DATA / SPECIALIST, OUT / f"{SPECIALIST}.pt", synthetic=True)
    (OUT / "manifest.json").write_text(json.dumps(MANIFEST, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("manifesto ->", OUT / "manifest.json")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["make-data", "train"])
    ap.add_argument("--epochs", type=int, default=4)
    ap.add_argument("--freeze-epochs", type=int, default=2)
    a = ap.parse_args()
    if a.cmd == "make-data":
        make_data()
    else:
        import os
        os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        train(a.epochs, a.freeze_epochs)
