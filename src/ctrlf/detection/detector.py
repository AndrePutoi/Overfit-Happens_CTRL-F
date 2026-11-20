"""A -> B: a função de deteção que B chama.  Cumpre o contrato em common/contract.py.

    from ctrlf.detection.detector import Detector
    det = Detector()                       # escolhe sozinho: rfdetr afinado se existir, senão zero-shot
    dets = det.detect(rgb_image, conf=0.3) # -> list[Detection]

Backends
  "rfdetr" : modelo afinado em models/detector/ (checkpoint_best_total.pth).  Rápido (~20 ms).
  "gdino"  : Grounding DINO tiny com texto.  SEM treino, funciona hoje, ~0.3 s/imagem.
             É o "modelo pré-treinado a correr sobre a zona piloto" das primeiras horas.

Extras (ligados por omissão, desligar com embed=False / subclassify=False):
  - embedding DINOv2-small (384 floats) de cada recorte -> deduplicação por aparência (B)
  - sub-classificador de sinais / contentores em models/subclassifier_<classe>.pt (ver sign_classifier.py)

Testar:  python -m ctrlf.detection.detector caminho/para/imagem.jpg
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import numpy as np
import torch
from PIL import Image

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
os.environ.setdefault("HF_HOME", str(ROOT / "models" / "hf_cache"))

from ctrlf.common.contract import Detection, load_classes  # noqa: E402
from ctrlf.privacy.gate import ensure_anonymized, get_anonymizer  # noqa: E402

DETECTOR_DIR = ROOT / "models" / "detector"
# Classificação hierárquica de sinais (router -> especialista), ativada pela PRESENÇA deste manifesto.
# CTRLF_HIER_MANIFEST muda o caminho; manifestos sintéticos exigem CTRLF_HIER_ALLOW_SYNTHETIC=1.
HIER_MANIFEST = ROOT / "models" / "hier_sinal" / "manifest.json"
CKPT_NAMES = ("checkpoint_best_total.pth", "checkpoint_best_ema.pth", "checkpoint_best_regular.pth")

# Texto para o Grounding DINO (zero-shot).  Frases separadas por " . " ; cada uma mapeia numa classe.
GDINO_PROMPTS = {
    "traffic sign": "sinal",
    "street light": "candeeiro",
    "utility pole": "poste",
    "recycling bin": "contentor",
    "waste container": "contentor",
}

# Caixa cujo token dominante é de uma classe mas outro token de OUTRA classe também passa `conf`:
#   "argmax" -> mantém a classe do token dominante (o score devolvido é a evidência dessa classe)
#   "drop"   -> descarta a caixa.  Em ambos os casos é contada em Detector.last_gdino_stats.
IGNORE = "__ignorar__"        # pseudo-classe de frases concorrentes: a caixa é descartada (ver Detector.set_prompts)
GDINO_AMBIGUOUS = "argmax"
GDINO_AMBIGUOUS_POLICIES = ("argmax", "drop")


def _gdino_token_classes(input_ids: list[int], tokenizer, prompts: dict[str, str], classes) -> list[str | None]:
    """Classe de cada POSIÇÃO de token do prompt (None em [CLS]/[SEP]/[PAD]/'.'/'?').

    As frases são delimitadas como em transformers (build_label_maps): a i-ésima frase do texto é a
    i-ésima chave de `prompts`.  Falha com ValueError se a tokenização não reproduzir as chaves.
    `classes` só serve para validar pertença (a ordem não interessa).
    """
    for k, c in prompts.items():
        if "." in k or "?" in k:
            raise ValueError(f"prompt {k!r} contém um delimitador ('.'/'?')")
        if c not in set(classes):
            raise ValueError(f"prompt {k!r} -> classe {c!r} fora de detector_classes")
    delim = {tokenizer.cls_token_id, tokenizer.sep_token_id, tokenizer.pad_token_id,
             tokenizer.convert_tokens_to_ids("."), tokenizer.convert_tokens_to_ids("?")}
    spans, cur = [], []
    for pos, t in enumerate(input_ids):
        if t in delim:
            if cur:
                spans.append(cur)
                cur = []
        else:
            cur.append(pos)
    if cur:
        spans.append(cur)
    keys = list(prompts)
    if len(spans) != len(keys):
        raise ValueError(f"tokenização com {len(spans)} frases, GDINO_PROMPTS tem {len(keys)}")
    out: list[str | None] = [None] * len(input_ids)
    for k, span in zip(keys, spans):
        dec = tokenizer.decode([input_ids[p] for p in span]).strip()
        if dec != k.strip().lower():
            raise ValueError(f"frase tokenizada {dec!r} != prompt {k!r}")
        for p in span:
            out[p] = prompts[k]
    return out


def _gdino_assign(probs, token_cls: list[str | None], conf: float, policy: str = GDINO_AMBIGUOUS,
                  input_ids: list[int] | None = None) -> tuple[str | None, bool]:
    """Uma linha de probabilidades por token (sigmoide de out.logits) -> (classe | None, ambígua).

    classe = classe do token de probabilidade máxima (o mesmo que dá o score da caixa).
    None só com policy="drop" numa caixa ambígua.  Token dominante sem frase -> RuntimeError.
    """
    if policy not in GDINO_AMBIGUOUS_POLICIES:
        raise ValueError(f"política {policy!r} não é uma de {GDINO_AMBIGUOUS_POLICIES}")
    p = probs.tolist() if hasattr(probs, "tolist") else list(probs)
    top = max(range(len(p)), key=p.__getitem__)          # empate -> menor índice
    cls = token_cls[top] if top < len(token_cls) else None
    if cls is None:
        tid = input_ids[top] if input_ids is not None and top < len(input_ids) else "fora do texto"
        raise RuntimeError(f"Grounding DINO: token dominante na posição {top} (id {tid}, p={p[top]:.4f}) "
                           f"não pertence a nenhuma frase de GDINO_PROMPTS; mapa={token_cls}")
    amb = any(c is not None and c != cls and p[i] > conf for i, c in enumerate(token_cls))
    if amb and policy == "drop":
        return None, True
    return cls, amb


def _to_pil(image) -> Image.Image:
    if isinstance(image, Image.Image):
        return image.convert("RGB")
    return Image.fromarray(np.asarray(image)).convert("RGB")      # espera RGB


class Detector:
    def __init__(self, backend: str = "auto", weights: str | None = None, device: str | None = None,
                 embed: bool = True, subclassify: bool = True):
        self.device = device or ("cuda" if torch.cuda.is_available() else "cpu")
        self.classes = load_classes()["detector_classes"]
        # Privacidade: nenhuma imagem chega ao detetor sem passar por rostos + matrículas (privacy/gate.py).
        # Falha fechada: se faltar um modelo de anonimização, o Detector não arranca.
        get_anonymizer()
        self.last_privacy_counts: dict = {}
        self.last_vehicles: list = []
        if backend == "auto":
            ck = next((DETECTOR_DIR / n for n in CKPT_NAMES if (DETECTOR_DIR / n).exists()), None)
            backend, weights = ("rfdetr", weights or str(ck)) if ck else ("gdino", None)
        self.backend = backend
        if backend == "rfdetr":
            from rfdetr import RFDETR
            self.model = RFDETR.from_checkpoint(weights, trust_checkpoint=True)
            names = [str(n) for n in self.model.class_names]
            # Se os nomes do checkpoint são os nossos, usa-os; senão assume a ordem de detector_classes.
            self.id2name = {i: n for i, n in enumerate(names)} if set(names) <= set(self.classes) \
                else {i: n for i, n in enumerate(self.classes)}
        elif backend == "gdino":
            from transformers import AutoModelForZeroShotObjectDetection, AutoProcessor
            n = "IDEA-Research/grounding-dino-tiny"
            self.proc = AutoProcessor.from_pretrained(n)
            self.model = AutoModelForZeroShotObjectDetection.from_pretrained(n).to(self.device).eval()
            self.gdino_ambiguous = GDINO_AMBIGUOUS
            self.last_gdino_stats: dict = {}
            self.set_prompts(GDINO_PROMPTS)
        else:
            raise ValueError(backend)

        self.embedder = self._load_dino() if embed else None
        self.sub = self._load_subclassifiers() if subclassify else {}
        # PKG-5 (opt-in; por omissão desligado = comportamento anterior). Ver detection/subclass/urban_branches.py.
        self.contentor_dedup_iou: float | None = None   # ex.: 0.7 -> remove duplicados de `contentor`
        self.branch_attributes = False                  # True -> preenche last_branch_report
        self.last_dedup_report: dict | None = None
        self.last_branch_report: list | None = None

    def set_prompts(self, prompts: dict[str, str]) -> None:
        """Troca as frases do Grounding DINO (frase em minúsculas -> classe), com a mesma validação do arranque.

        A pseudo-classe IGNORE serve de frase CONCORRENTE (ex.: "car" -> IGNORE): uma caixa cujo token dominante
        é dessa frase é descartada e contada em last_gdino_stats["ignored"].
        """
        if self.backend != "gdino":
            raise ValueError("set_prompts só existe no backend gdino")
        text = " . ".join(prompts) + " ."
        ids = self.proc.tokenizer(text)["input_ids"]
        max_len = getattr(self.model.config, "max_text_len", None)
        if max_len is not None and len(ids) > max_len:
            raise ValueError(f"prompt com {len(ids)} tokens > max_text_len {max_len}")
        token_cls = _gdino_token_classes(ids, self.proc.tokenizer, prompts, list(self.classes) + [IGNORE])
        self.text, self._gdino_ids, self._gdino_token_cls, self.prompts = text, ids, token_cls, dict(prompts)

    # ------------------------------------------------------------ DINOv2-S
    def _load_dino(self):
        from transformers import AutoImageProcessor, AutoModel
        proc = AutoImageProcessor.from_pretrained("facebook/dinov2-small")
        model = AutoModel.from_pretrained("facebook/dinov2-small").to(self.device).half().eval()
        return proc, model

    @torch.no_grad()
    def embed_crops(self, crops: list[Image.Image]) -> np.ndarray:
        proc, model = self.embedder
        x = proc(images=crops, return_tensors="pt")["pixel_values"].to(self.device).half()
        e = model(pixel_values=x).pooler_output.float()
        return torch.nn.functional.normalize(e, dim=1).cpu().numpy()

    def _load_subclassifiers(self):
        out = {}
        hm = Path(os.environ.get("CTRLF_HIER_MANIFEST") or HIER_MANIFEST)
        if os.environ.get("CTRLF_HIER_MANIFEST") or hm.exists():     # pedido explícito ou artefacto presente
            from ctrlf.detection.subclass.hier_classifier import HierClassifier       # erros de carregamento NÃO são mascarados
            out["sinal"] = HierClassifier.from_manifest(
                hm, self.device, allow_synthetic=os.environ.get("CTRLF_HIER_ALLOW_SYNTHETIC") == "1")
        for cls in load_classes().get("subclassifiers", {}):
            if cls in out:
                continue
            p = ROOT / "models" / f"subclassifier_{cls}.pt"
            if p.exists():
                from ctrlf.detection.subclass.sign_classifier import load_classifier
                out[cls] = load_classifier(p, self.device)
        return out

    # -------------------------------------------------------------- detetar
    def _raw(self, img: Image.Image, conf: float):
        """-> lista de (cls, score, (x1,y1,x2,y2))"""
        if self.backend == "rfdetr":
            d = self.model.predict(img, threshold=conf)
            return [(self.id2name.get(int(c), self.classes[int(c) % len(self.classes)]), float(s), tuple(map(float, b)))
                    for b, s, c in zip(d.xyxy, d.confidence, d.class_id)]
        inp = self.proc(images=img, text=self.text, return_tensors="pt").to(self.device)
        ids = inp.input_ids[0].tolist()
        if ids != self._gdino_ids:
            raise RuntimeError(f"input_ids do processador ({len(ids)}) != tokenização do arranque "
                               f"({len(self._gdino_ids)})")
        with torch.no_grad():
            out = self.model(**inp)
        res = self.proc.post_process_grounded_object_detection(
            out, inp.input_ids, threshold=conf, text_threshold=conf, target_sizes=[img.size[::-1]])[0]
        # Classe pela posição do token dominante em out.logits (não pelo texto de `text_labels`).
        if out.logits.dim() != 3 or out.logits.shape[0] != 1 or out.logits.shape[-1] < len(ids):
            raise RuntimeError(f"logits com forma {tuple(out.logits.shape)} incompatível com {len(ids)} tokens")
        probs = out.logits[0].sigmoid()
        scores = probs.max(-1).values
        keep = scores > conf
        if len(res["boxes"]) != int(keep.sum()) or not torch.equal(scores[keep], res["scores"]):
            raise RuntimeError("reconstrução a partir de out.logits diverge do pós-processador")
        stats = {"raw": len(res["boxes"]), "kept": 0, "ambiguous": 0, "ambiguous_dropped": 0,
                 "unmapped": 0, "policy": self.gdino_ambiguous}
        self.last_gdino_stats = stats
        dets = []
        for b, s, row in zip(res["boxes"].tolist(), res["scores"].tolist(), probs[keep].cpu()):
            try:
                cls, amb = _gdino_assign(row, self._gdino_token_cls, conf, self.gdino_ambiguous, ids)
            except RuntimeError:
                stats["unmapped"] += 1
                raise
            stats["ambiguous"] += amb
            if cls is None:
                stats["ambiguous_dropped"] += 1
                continue
            if cls == IGNORE:
                stats["ignored"] = stats.get("ignored", 0) + 1
                continue
            dets.append((cls, float(s), tuple(b)))
        stats["kept"] = len(dets)
        return dets

    def detect(self, image, conf: float = 0.3) -> list[Detection]:
        image = ensure_anonymized(image)                 # SEMPRE antes do Grounding DINO / RF-DETR
        self.last_privacy_counts = dict(image.privacy_counts)
        self.last_vehicles = list(getattr(image, "privacy_vehicles", []))      # caixas de veículos (xyxy) do desfoque
        img = _to_pil(image)
        raw = self._raw(img, conf)
        self.last_dedup_report = self.last_branch_report = None
        if self.contentor_dedup_iou is not None:
            from ctrlf.detection.subclass.urban_branches import dedup_contentor
            raw, self.last_dedup_report = dedup_contentor(raw, self.contentor_dedup_iou)
        dets = [Detection(cls=c, score=s, bbox=b) for c, s, b in raw]
        if not dets:
            if self.branch_attributes:
                self.last_branch_report = []
            return dets
        W, H = img.size
        crops = []
        for d in dets:
            x1, y1, x2, y2 = d.bbox
            crops.append(img.crop((max(0, int(x1)), max(0, int(y1)), min(W, int(x2) + 1), min(H, int(y2) + 1))))
        if self.embedder is not None:
            for d, e in zip(dets, self.embed_crops(crops)):
                d.embedding = e.tolist()
        for cls, clf in self.sub.items():
            idx = [i for i, d in enumerate(dets) if d.cls == cls]
            if idx:
                for i, (lab, p) in zip(idx, clf.predict([crops[i] for i in idx])):
                    dets[i].subclass, dets[i].subscore = lab, p
        if self.branch_attributes:
            from ctrlf.detection.subclass.urban_branches import branch_report
            self.last_branch_report = branch_report(dets, self.sub)
        return dets


if __name__ == "__main__":
    import json
    if len(sys.argv) < 2:
        sys.exit("uso: python -m ctrlf.detection.detector imagem.jpg [conf]")
    det = Detector()
    print("backend:", det.backend)
    for d in det.detect(Image.open(sys.argv[1]), float(sys.argv[2]) if len(sys.argv) > 2 else 0.3):
        j = d.to_dict(); j["embedding"] = f"[{len(d.embedding)} floats]" if d.embedding else None
        print(json.dumps(j, ensure_ascii=False))
