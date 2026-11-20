"""PKG-4: prepara recortes GTSRB (dataset real, alemão) para o router hierárquico e o especialista 30/50.

    python -m ctrlf.treino.gtsrb_prepare          # lê data/external/gtsrb/extracted, escreve data/crops/gtsrb/

Fonte: arquivo ERDA/SID oficial (ver reports/ensaio/PKG4_GTSRB_REAL_EVALUATION_2026-11-14.md).  Uso local apenas;
nada disto vai para o Git (data/ é ignorado).

Separação:
  treino/val  = conjunto oficial de TREINO, dividido por TRACK (XXXXX em XXXXX_YYYYY.ppm = um sinal físico),
                20 % dos tracks de cada classe para val, seed fixa.  Nenhum track aparece em dois splits.
                Por track usam-se 10 imagens igualmente espaçadas (as 30 são a mesma placa a distâncias diferentes).
  teste       = conjunto oficial de TESTE completo (GT-final_test.csv), sem subamostragem, só para avaliação final.
Imagens: PPM originais com a margem de 10 % do GTSRB (sem recorte ao ROI, sem flips).  Ligações físicas (hardlinks).
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import random
import shutil
from collections import Counter, defaultdict
from pathlib import Path

from ctrlf.paths import ROOT
RAW = ROOT / "data" / "external" / "gtsrb" / "extracted"
OUT = ROOT / "data" / "crops" / "gtsrb"
SEED, VAL_FRAC, PER_TRACK = 0, 0.2, 10

# ClassId GTSRB -> nome (confirmado visualmente com um exemplo por classe)
GTSRB_NAMES = {
    0: "speed_20", 1: "speed_30", 2: "speed_50", 3: "speed_60", 4: "speed_70", 5: "speed_80", 6: "end_speed_80",
    7: "speed_100", 8: "speed_120", 9: "no_passing", 10: "no_passing_trucks", 11: "right_of_way_intersection",
    12: "priority_road", 13: "yield", 14: "stop", 15: "no_vehicles", 16: "trucks_prohibited", 17: "no_entry",
    18: "general_caution", 19: "curve_left", 20: "curve_right", 21: "double_curve", 22: "bumpy_road",
    23: "slippery_road", 24: "road_narrows_right", 25: "road_work", 26: "traffic_signals", 27: "pedestrians",
    28: "children", 29: "bicycles", 30: "ice_snow", 31: "wild_animals", 32: "end_all_limits",
    33: "turn_right_ahead", 34: "turn_left_ahead", 35: "ahead_only", 36: "straight_or_right",
    37: "straight_or_left", 38: "keep_right", 39: "keep_left", 40: "roundabout", 41: "end_no_passing",
    42: "end_no_passing_trucks",
}
# ClassId -> grupo visual do router.  Ausente = EXCLUÍDO (sem grupo seguro).
GROUP = {**{c: "circular_vermelho" for c in (0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 15, 16)},
         17: "circular_vermelho_cheio", 12: "losango_amarelo", 14: "octogono_vermelho", 13: "triangulo_invertido",
         **{c: "triangulo_perigo" for c in (11, *range(18, 32))},
         **{c: "circular_azul" for c in range(33, 41)}}
EXCLUDED = {6: "fim de limite 80 (branco/cinzento com barras; sem grupo)",
            32: "fim de todas as proibições (sem grupo)",
            41: "fim de proibição de ultrapassar (sem grupo)",
            42: "fim de proibição de ultrapassar pesados (sem grupo)"}
# Especialista do grupo circular_vermelho
SPEC_LEAF = {1: "limite_velocidade_30", 2: "limite_velocidade_50"}
SPEC_OTHER = "outro_circular_vermelho"
# folha esperada da cascata (para a avaliação)
TERMINAL = {17: "sentido_proibido", 12: "via_com_prioridade", 14: "stop", 13: "cedencia_passagem"}


def expected_leaf(cid: int) -> str | None:
    g = GROUP.get(cid)
    if g is None:
        return None
    if g == "circular_vermelho":
        return SPEC_LEAF.get(cid, SPEC_OTHER)
    return TERMINAL.get(cid, "unknown")


def md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


def main() -> None:
    assert set(GROUP) | set(EXCLUDED) == set(range(43)) and not set(GROUP) & set(EXCLUDED)
    if OUT.exists():
        shutil.rmtree(OUT)
    rng = random.Random(SEED)
    split_tracks, counts, hashes = {}, Counter(), {}
    dups = []

    def put(src: Path, split: str, cid: int, name: str):
        h = md5(src)
        if h in hashes and hashes[h][0] != split:
            dups.append((hashes[h], (split, name)))
        hashes.setdefault(h, (split, name))
        g = GROUP[cid]
        dests = [OUT / "router" / split / g]
        if g == "circular_vermelho":
            dests.append(OUT / "esp_circular_vermelho" / split / SPEC_LEAF.get(cid, SPEC_OTHER))
        for d in dests:
            d.mkdir(parents=True, exist_ok=True)
            os.link(src, d / name)
        counts[(split, cid)] += 1

    # Contaminação conhecida: imagens do TESTE oficial idênticas (md5) a imagens do TREINO oficial.
    # O track de treino inteiro (= o mesmo sinal físico) é retirado de treino e val; o teste fica intacto.
    test_rows = list(csv.DictReader(open(RAW / "GT-final_test.csv"), delimiter=";"))
    test_md5 = {md5(RAW / "GTSRB" / "Final_Test" / "Images" / r["Filename"]): r["Filename"] for r in test_rows}
    removed_tracks = []
    for cid in sorted(GROUP):
        cdir = RAW / "GTSRB" / "Final_Training" / "Images" / f"{cid:05d}"
        rows = list(csv.DictReader(open(cdir / f"GT-{cid:05d}.csv"), delimiter=";"))
        by_track = defaultdict(list)
        for r in rows:
            by_track[r["Filename"].split("_")[0]].append(r["Filename"])
        for t in sorted(by_track):
            hits = sorted(test_md5[h] for f in by_track[t] if (h := md5(cdir / f)) in test_md5)
            if hits:
                removed_tracks.append({"class": cid, "track": t, "n_images": len(by_track[t]),
                                       "identical_test_images": hits})
                del by_track[t]
        tracks = sorted(by_track)
        rng.shuffle(tracks)
        n_val = max(1, round(len(tracks) * VAL_FRAC))
        sp = {"val": sorted(tracks[:n_val]), "train": sorted(tracks[n_val:])}
        assert not set(sp["val"]) & set(sp["train"])
        split_tracks[cid] = sp
        for split, ts in sp.items():
            for t in ts:
                fs = sorted(by_track[t])
                idx = sorted({round(i * (len(fs) - 1) / (PER_TRACK - 1)) for i in range(PER_TRACK)}) \
                    if len(fs) > PER_TRACK else range(len(fs))
                for i in idx:
                    put(cdir / fs[i], split, cid, f"{cid:02d}_{t}_{fs[i]}")

    excluded_test = Counter()
    for r in test_rows:
        cid = int(r["ClassId"])
        src = RAW / "GTSRB" / "Final_Test" / "Images" / r["Filename"]
        if cid in GROUP:
            put(src, "test", cid, f"{cid:02d}_test_{r['Filename']}")
        else:
            excluded_test[cid] += 1

    per_split = {s: sum(v for (sp, _), v in counts.items() if sp == s) for s in ("train", "val", "test")}
    groups = sorted(set(GROUP.values()))
    per_group = {s: {g: sum(v for (sp, c), v in counts.items() if sp == s and GROUP[c] == g) for g in groups}
                 for s in ("train", "val", "test")}
    info = {
        "source": "GTSRB Final_Training_Images + Final_Test_Images + Final_Test_GT (ERDA/SID)",
        "seed": SEED, "val_frac_tracks": VAL_FRAC, "images_per_track": PER_TRACK,
        "groups": groups, "mapping": {str(c): {"gtsrb": GTSRB_NAMES[c], "group": GROUP[c],
                                               "expected_leaf": expected_leaf(c)} for c in sorted(GROUP)},
        "excluded": {str(c): {"gtsrb": GTSRB_NAMES[c], "reason": EXCLUDED[c], "test_images": excluded_test[c]}
                     for c in sorted(EXCLUDED)},
        "images_per_split": per_split, "images_per_group": per_group,
        "per_class": {str(c): {s: counts[(s, c)] for s in ("train", "val", "test")} |
                      {"tracks_train": len(split_tracks[c]["train"]), "tracks_val": len(split_tracks[c]["val"])}
                      for c in sorted(GROUP)},
        "track_overlap_train_val": 0,
        "removed_train_tracks_identical_to_test": removed_tracks,
        "md5_duplicates_across_splits": [list(map(list, d)) for d in dups],
        "unique_md5": len(hashes),
    }
    (OUT / "splits.json").write_text(json.dumps(info, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: info[k] for k in ("images_per_split", "images_per_group", "unique_md5")}))
    print("duplicados md5 entre splits:", len(dups))


MODEL_DIR = ROOT / "models" / "hier_sinal_gtsrb"     # NÃO é models/hier_sinal/: não ativa o Detector por omissão


def write_manifest() -> Path:
    groups = sorted(set(GROUP.values()))
    gdef = {"circular_vermelho": {"family": "proibicao_restricao", "specialist": "esp_circular_vermelho"},
            "circular_vermelho_cheio": {"family": "proibicao_restricao", "leaf": "sentido_proibido"},
            "losango_amarelo": {"family": "prioridade_paragem", "leaf": "via_com_prioridade"},
            "octogono_vermelho": {"family": "prioridade_paragem", "leaf": "stop"},
            "triangulo_invertido": {"family": "prioridade_paragem", "leaf": "cedencia_passagem"},
            "triangulo_perigo": {"family": "perigo"},
            "circular_azul": {"family": "obrigacao"}}
    assert set(gdef) == set(groups)
    m = {"version": 1, "synthetic": False,
         "note": "Treinado com GTSRB (sinais alemães, uso local de ensaio). Folhas provisórias; C1 pendente.",
         "source": {"dataset": "GTSRB", "splits": "data/crops/gtsrb/splits.json"},
         "router": {"checkpoint": "router.pt", "labels": groups},
         "groups": gdef,
         "specialists": {"esp_circular_vermelho": {
             "checkpoint": "esp_circular_vermelho.pt",
             "labels": sorted({*SPEC_LEAF.values(), SPEC_OTHER})}}}
    p = MODEL_DIR / "manifest.json"
    p.write_text(json.dumps(m, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return p


if __name__ == "__main__":
    import sys
    if sys.argv[1:] == ["manifest"]:
        print(write_manifest())
    else:
        main()
