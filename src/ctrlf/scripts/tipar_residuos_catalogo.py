"""Classifica o TIPO (fluxo: indiferenciado, papel, embalagens, vidro) de todas as deteções de contentor/subterrâneo do catálogo de uma cidade, para as ILHAS de reciclagem.

    python -m ctrlf.scripts.tipar_residuos_catalogo [aveiro] [--clf $UMS_MODELS_DIR/classificador_fluxo4.pt]   ->  data/catalog/<cidade>/residuos_tipos.json

Lê as deteções de data/preannot/ecopontos/<cidade>/annotations/instances_default.json (as mesmas que o pacote de entrega), corre o classificador DINOv2 de 4 classes no recorte (margem 8 %) e guarda
{"<imagem>|x1,y1,x2,y2": {"tipo", "p_tipo", "segundo", "p_segundo", "modelo"}}. Imagens SEMPRE de data/images_anon (sha256 do manifesto). O tipo é uma SUGESTÃO: ~63 % de exatidão (62,6 % equilibrada) em panoramas do Porto não vistos; em outras cidades não está medido.
A papeleira não leva tipo (é `indiferenciado` por regra).
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
ANON = ROOT / "data" / "images_anon"
PAD = 0.08


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("city", nargs="?", default="aveiro")
    ap.add_argument("--clf", type=Path, default=Path(__import__("os").environ.get("UMS_MODELS_DIR", ROOT / "models")) / "classificador_fluxo4.pt", help="omissão: classificador_fluxo4.pt na pasta de pesos (o nome definitivo; substituir por um novo com o mesmo nome)")
    a = ap.parse_args()
    import torch
    from PIL import Image
    from ctrlf.detection.subclass.sign_classifier import TF_EVAL, load_classifier
    man = {}
    for l in (ANON / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if l.strip():
            d0 = json.loads(l); man[d0["file"]] = d0["sha256"]
    d = json.loads((ROOT / "data" / "preannot" / "ecopontos" / a.city / "annotations" / "instances_default.json").read_text(encoding="utf-8"))
    cat = {c["id"]: c["name"] for c in d["categories"]}; img = {i["id"]: i["file_name"] for i in d["images"]}
    por = {}
    for an in d["annotations"]:
        if cat[an["category_id"]] in ("contentor", "subterraneo"):
            por.setdefault(img[an["image_id"]], []).append(an)
    clf = load_classifier(a.clf, "cuda"); clf.net.eval()
    out, n = {}, 0
    for nm, L in sorted(por.items()):
        p = ANON / nm
        assert nm in man and hashlib.sha256(p.read_bytes()).hexdigest() == man[nm], f"{nm}: sem manifesto ou sha256 diferente"
        im = Image.open(p).convert("RGB")
        crops, keys = [], []
        for an in L:
            x, y, w, h = an["bbox"]; m = PAD * max(w, h)
            crops.append(im.crop((max(0, int(x - m)), max(0, int(y - m)), min(im.width, int(x + w + m)), min(im.height, int(y + h + m)))))
            keys.append(f"{Path(nm).stem}|{round(x, 1)},{round(y, 1)},{round(x + w, 1)},{round(y + h, 1)}")
        with torch.no_grad():
            P = torch.softmax(clf.net(torch.stack([TF_EVAL(c) for c in crops]).cuda()).float(), 1).cpu().tolist()
        for k, pr in zip(keys, P):
            o = sorted(range(len(pr)), key=lambda j: -pr[j])
            out[k] = {"tipo": clf.labels[o[0]], "p_tipo": round(pr[o[0]], 3), "segundo": clf.labels[o[1]], "p_segundo": round(pr[o[1]], 3), "modelo": a.clf.name}
        n += len(L)
        if len(out) % 1000 < len(L):
            print(f"{len(out)} caixas", flush=True)
    (ROOT / "data" / "catalog" / a.city / "residuos_tipos.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    from collections import Counter
    print(f"FEITO: {len(out)} caixas em {len(por)} imagens; tipos: {dict(Counter(v['tipo'] for v in out.values()))}", flush=True)


if __name__ == "__main__":
    main()
