"""Pré-anotação com o Grounding DINO Tiny (zero-shot, texto -> caixas), SEM treino: demonstração com várias soluções de prompt para CONTENTORES.

    python preanotar_grounding_dino.py --imagens imagens --out preanotado --overlay overlay           # as 3 soluções nas imagens de exemplo
    python preanotar_grounding_dino.py --imagens X --solucoes descritivo --box-thr 0.3 --out Y         # uma só, com outro limiar

Para que serve: arrancar uma ANOTAÇÃO (CVAT) sem ter nenhum detetor treinado: escreve um COCO com as caixas propostas, que um humano corrige. NÃO é o detetor da pipeline
(esse é o RF-DETR treinado: ver relacao_contentores.md para a comparação medida). Modelo: IDEA-Research/grounding-dino-tiny (Apache-2.0), descarregado do Hugging Face na 1.ª utilização
(~690 MB) ou lido de $HF_HOME. Precisa de: torch, transformers, pillow. GPU opcional (CPU funciona, mais lento).

Soluções (cada uma é um conjunto de frases; a CLASSE da caixa vem da frase que a produziu):
  simples        1 frase por classe, curtas:            «trash bin.» «recycling container.»                           -> contentor
  descritivo     frases longas com cor/forma:           «a large recycling container.» «a green glass recycling bin.» ... -> contentor ; «an underground waste container.» -> subterraneo
  por_classe     como `descritivo` mas corre UMA classe de cada vez (evita que as frases se disputem as mesmas caixas)
Limiares: --box-thr (confiança da caixa) e --text-thr (ligação ao texto), por omissão 0,30 e 0,25. Mais baixo = mais caixas e mais falsos positivos.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

SOLUCOES = {
    "simples": {"contentor": ["trash bin", "recycling container"]},
    "descritivo": {"contentor": ["a large recycling container", "a green glass recycling bin", "a yellow plastic recycling bin", "a blue paper recycling bin", "a grey waste bin on the street"],
                   "subterraneo": ["an underground waste container"]},
    "por_classe": {"contentor": ["a large recycling container", "a green glass recycling bin", "a yellow plastic recycling bin", "a blue paper recycling bin", "a grey waste bin on the street"],
                   "subterraneo": ["an underground waste container"]},
}
CLASSES = ["contentor", "subterraneo"]


def carregar(device: str):
    import torch
    from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
    n = "IDEA-Research/grounding-dino-tiny"
    proc = AutoProcessor.from_pretrained(n)
    model = AutoModelForZeroShotObjectDetection.from_pretrained(n).to(device).eval()
    return torch, proc, model


def detetar(torch, proc, model, img, frases: list[str], box_thr: float, text_thr: float, device: str) -> list[tuple[str, float, list[float]]]:
    """-> [(frase, score, [x1,y1,x2,y2])]. Frases separadas por '.', todas em minúsculas (exigência do modelo)."""
    texto = " ".join(f.strip().lower().rstrip(".") + "." for f in frases)
    inp = proc(images=img, text=texto, return_tensors="pt").to(device)
    with torch.no_grad():
        out = model(**inp)
    r = proc.post_process_grounded_object_detection(out, inp.input_ids, threshold=box_thr, text_threshold=text_thr, target_sizes=[img.size[::-1]])[0]
    rotulos = r.get("text_labels", r.get("labels", []))
    return [(str(l), float(s), [float(v) for v in b]) for l, s, b in zip(rotulos, r["scores"], r["boxes"])]


def classe_da_frase(frase: str, mapa: dict[str, list[str]]) -> str | None:
    f = frase.strip().lower().rstrip(".")
    for classe, frases in mapa.items():
        if any(f == x or f in x or x in f for x in frases):
            return classe
    return None


def correr_solucao(nome: str, ficheiros: list[Path], box_thr: float, text_thr: float, device: str, modelo) -> dict:
    torch, proc, model = modelo
    from PIL import Image
    mapa = SOLUCOES[nome]
    imgs, anns = [], []
    for i, f in enumerate(ficheiros, 1):
        im = Image.open(f).convert("RGB")
        imgs.append({"id": i, "file_name": f.name, "width": im.width, "height": im.height})
        grupos = [(c, fr) for c, fr in mapa.items()] if nome == "por_classe" else [(None, [x for fr in mapa.values() for x in fr])]
        vistos = []
        for _, frases in grupos:
            for frase, score, (x1, y1, x2, y2) in detetar(torch, proc, model, im, frases, box_thr, text_thr, device):
                classe = classe_da_frase(frase, mapa)
                if classe is None or x2 <= x1 or y2 <= y1:
                    continue
                anns.append({"id": len(anns) + 1, "image_id": i, "category_id": CLASSES.index(classe) + 1, "bbox": [round(x1, 1), round(y1, 1), round(x2 - x1, 1), round(y2 - y1, 1)],
                             "area": round((x2 - x1) * (y2 - y1), 1), "iscrowd": 0, "score": round(score, 3), "attributes": {"frase": frase}})
    return {"categories": [{"id": i + 1, "name": c} for i, c in enumerate(CLASSES)], "images": imgs, "annotations": anns}


def desenhar(coco: dict, pasta_img: Path, destino: Path) -> None:
    from PIL import Image, ImageDraw
    destino.mkdir(parents=True, exist_ok=True)
    cor = {1: (46, 160, 44), 2: (227, 119, 194)}
    por = {}
    for a in coco["annotations"]:
        por.setdefault(a["image_id"], []).append(a)
    for im in coco["images"]:
        img = Image.open(pasta_img / im["file_name"]).convert("RGB")
        d = ImageDraw.Draw(img)
        for a in por.get(im["id"], []):
            x, y, w, h = a["bbox"]
            d.rectangle([x, y, x + w, y + h], outline=cor[a["category_id"]], width=4)
            d.text((x + 3, y + 3), f"{coco['categories'][a['category_id'] - 1]['name']} {a['score']:.2f}", fill=(255, 255, 255))
        img.save(destino / im["file_name"], quality=88)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--imagens", type=Path, required=True)
    ap.add_argument("--solucoes", nargs="+", default=list(SOLUCOES), choices=list(SOLUCOES))
    ap.add_argument("--box-thr", type=float, default=0.30)
    ap.add_argument("--text-thr", type=float, default=0.25)
    ap.add_argument("--out", type=Path, required=True, help="escreve <out>/<solução>/instances_default.json (COCO 1.0, importável no CVAT)")
    ap.add_argument("--overlay", type=Path, help="escreve <overlay>/<solução>/<imagem>.jpg com as caixas desenhadas")
    ap.add_argument("--device", default=None)
    a = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    if "HF_HOME" not in os.environ and (root / "models" / "hf_cache").exists():
        os.environ["HF_HOME"] = str(root / "models" / "hf_cache")
    import torch
    device = a.device or ("cuda" if torch.cuda.is_available() else "cpu")
    ficheiros = sorted(p for p in a.imagens.iterdir() if p.suffix.lower() in (".jpg", ".jpeg", ".png"))
    modelo = carregar(device)
    for nome in a.solucoes:
        coco = correr_solucao(nome, ficheiros, a.box_thr, a.text_thr, device, modelo)
        (a.out / nome).mkdir(parents=True, exist_ok=True)
        (a.out / nome / "instances_default.json").write_text(json.dumps(coco, ensure_ascii=False), encoding="utf-8")
        if a.overlay:
            desenhar(coco, a.imagens, a.overlay / nome)
        print(f"{nome:11s}: {len(coco['annotations']):3d} caixas em {len(ficheiros)} imagens ({device}, box-thr {a.box_thr}, text-thr {a.text_thr})")


if __name__ == "__main__":
    main()
