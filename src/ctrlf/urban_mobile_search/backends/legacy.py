"""Adaptadores para os modelos e módulos que já existem no projeto (fase 1: `UMS_PROJECT_ROOT` aponta para o repositório).

TODOS os imports pesados (torch, rfdetr, transformers, detection.*, privacy.*) são PREGUIÇOSOS: importar este ficheiro não carrega nada.
Os pesos NUNCA vão dentro do pacote (os do GTSRB/MTSD têm direitos por estabelecer; ver docs/licencas/): ficam em `UMS_MODELS_DIR`.
NÃO executados em CI: precisam de GPU e pesos. Verificados por leitura contra as chamadas dos scripts de pré-anotação.
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

from ..registry import ClassifierSpec, DetectorSpec, Registry
from ..settings import Settings
from .base import ClassOut, RawDet


def ensure_path(settings: Settings) -> None:
    """Põe o repositório no sys.path e fixa a cache dos modelos do Hugging Face ANTES de qualquer import pesado.
    O `huggingface_hub` lê o HF_HOME uma única vez, ao ser importado (o `rfdetr` importa-o logo): se isto vier depois, o CLIP/DINOv2/Grounding DINO
    procuram os pesos em ~/.cache e falham ("couldn't connect to huggingface.co") mesmo com os pesos em models/hf_cache."""
    import os
    os.environ.setdefault("HF_HOME", str(settings.models_dir / "hf_cache"))
    root = str(settings.project_root)
    if root not in sys.path:
        sys.path.insert(0, root)


def _fp(path: Path) -> str:
    """Versão de um ficheiro de pesos: nome@mtime-tamanho (barata e muda quando os pesos mudam)."""
    st = path.stat()
    return f"{path.parent.name}/{path.name}@{int(st.st_mtime)}-{st.st_size}"


def _need(path: Path, what: str) -> Path:
    if not path.exists():
        raise FileNotFoundError(f"{what}: faltam os pesos em {path} (definir UMS_MODELS_DIR)")
    return path


def _free_cuda() -> None:
    try:
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


# ------------------------------------------------------------------ detetores
class RFDetrDetector:
    """RF-DETR treinado (sinais: 5 famílias do MTSD; resíduos: contentor/subterraneo)."""

    def __init__(self, settings: Settings, weights: Path, expected: set[str]):
        ensure_path(settings)
        import rfdetr
        from ctrlf.common.rfdetr_patch import apply as patch_rfdetr
        patch_rfdetr()
        self.model = rfdetr.RFDETR.from_checkpoint(str(weights), trust_checkpoint=True)
        self.names = [str(n) for n in self.model.class_names]
        if set(self.names) != expected:
            raise ValueError(f"classes inesperadas no checkpoint {weights.name}: {self.names} (esperava {sorted(expected)})")

    def detect(self, image, conf: float) -> list[RawDet]:
        d = self.model.predict(Image.fromarray(np.asarray(image)), threshold=conf)
        return [RawDet(self.names[int(c)], float(s), tuple(float(v) for v in b)) for b, s, c in zip(d.xyxy, d.confidence, d.class_id)]

    def close(self) -> None:
        self.model = None
        _free_cuda()


# ------------------------------------------------------------------ classificadores
class SignTypeClassifier:
    """Router + especialistas do MTSD (detection/subclass/hier_classifier.py). Tipo só se router e família do detetor concordam."""

    def __init__(self, settings: Settings, manifest: Path, device: str):
        ensure_path(settings)
        from ctrlf.detection.subclass.hier_classifier import HierClassifier
        self.hc = HierClassifier.from_manifest(manifest, device)
        self.thr = settings.sign_not_sign_thr

    def classify(self, crops: list, dets: list) -> list[ClassOut]:
        out = []
        for r, d in zip(self.hc.predict_detailed(crops), dets):
            nao = r["group"] == "nao_sinal" and r["p_router"] >= self.thr
            tipo = r.get("label") if r["group"] == d.cls else "desconhecido"       # router e detetor discordam -> sem tipo
            out.append(ClassOut(label=tipo or "desconhecido", score=float(r.get("score", 0.0)), reject=nao,
                                extra={"group": r["group"], "p_router": round(r["p_router"], 3)}))
        return out

    def close(self) -> None:
        self.hc = None
        _free_cuda()


class PapeleiraClassifier:
    """Filtro CLIP de papeleiras (detection/postfilter/papeleiras.py). Muda a classe para `papeleira` acima do limiar de cada classe."""

    def __init__(self, settings: Settings, device: str):
        ensure_path(settings)
        from ctrlf.detection.postfilter.papeleiras import PapeleiraFilter
        self.f = PapeleiraFilter(device=device)
        self.thr = settings.papeleira_thr

    def classify(self, crops: list, dets: list) -> list[ClassOut]:
        out = []
        for (p_pap, _), d in zip(self.f.scores(crops), dets):
            is_pap = p_pap >= self.thr.get(d.cls, 0.8)
            out.append(ClassOut(label="papeleira" if is_pap else "ecoponto", score=float(p_pap), set_cls="papeleira" if is_pap else None, extra={"p_papeleira": round(p_pap, 3)}))
        return out

    def close(self) -> None:
        self.f = None
        _free_cuda()


class FluxClassifier:
    """DINOv2-small afinado no waste_container -> fluxo (tipo de contentor), com os 7 labels do dataset. Usa SEMPRE o mais provável (limiar 0 por omissão;
    com `flux_unknown_thr` > 0, abaixo dele sai `desconhecido`). A confiança fica em `score`. SUGESTÃO: não transfere bem para o Porto."""
    FLUXO = {"indiferenciado": "indiferenciado", "papel": "papel", "embalagens": "embalagens", "vidro": "vidro",       # classificador de 4 classes (models/classificador_fluxo4.pt)
             "container_default": "indiferenciado", "container_blue": "papel", "container_green": "vidro", "container_yellow": "embalagens",
             "container_biodegradable": "organicos", "container_oil": "oleo", "container_battery": "pilhas"}

    def __init__(self, settings: Settings, ckpt: Path, device: str):
        ensure_path(settings)
        from ctrlf.detection.subclass.sign_classifier import TF_EVAL, load_classifier
        self.clf, self.tf, self.dev = load_classifier(ckpt, device), TF_EVAL, device
        self.thr = settings.flux_unknown_thr

    def classify(self, crops: list, dets: list) -> list[ClassOut]:
        import torch
        out = []
        with torch.no_grad():
            for i in range(0, len(crops), 32):
                x = torch.stack([self.tf(c.convert("RGB")) for c in crops[i:i + 32]]).to(self.dev)
                for p in torch.softmax(self.clf.net(x).float(), 1).cpu().tolist():
                    order = sorted(range(len(p)), key=lambda j: -p[j])
                    top, second = self.clf.labels[order[0]], self.clf.labels[order[1]]
                    lab = self.FLUXO[top] if p[order[0]] >= self.thr else "desconhecido"
                    out.append(ClassOut(label=lab, score=float(p[order[0]]), extra={"modelo": self.FLUXO[top], "segunda": self.FLUXO[second], "segunda_p": round(p[order[1]], 3)}))
        return out

    def close(self) -> None:
        self.clf = None
        _free_cuda()


class LightStyleClassifier:
    """CLIP com os 2 prompts da equipa -> poste_luz | candeeiro (+ rejeição). `light_policy` = política por cidade (ex.: só candeeiros)."""

    def __init__(self, settings: Settings, device: str):
        ensure_path(settings)
        from ctrlf.detection.luz_clip import LuzClip
        self.clip = LuzClip(device)
        self.reject = settings.light_reject
        self.policy = settings.light_policy

    def classify(self, crops: list, dets: list) -> list[ClassOut]:
        out = []
        for ps, pd, pj in self.clip.probs(crops):
            pol = self.policy
            rej = pj >= pol.get("reject", self.reject)
            if pol.get("so_candeeiro"):
                rej = rej or pd < pol.get("pc_min", 0.25)
                label = "candeeiro"
            else:
                label = "candeeiro" if pd > ps else "poste_luz"
            out.append(ClassOut(label=label, score=float(max(ps, pd)), reject=rej, set_cls=label,
                                extra={"p_poste_luz": round(ps, 3), "p_candeeiro": round(pd, 3), "p_rejeitar": round(pj, 3)}))
        return out

    def close(self) -> None:
        self.clip = None
        _free_cuda()


# ------------------------------------------------------------------ registo por omissão
def default_registry(settings: Settings) -> Registry:
    """Os detetores e classificadores do projeto . Nada se carrega aqui: só quando a pipeline os pede."""
    from .bench import BenchBackend
    m = settings.models_dir
    dev = settings.resolve_device()
    reg = Registry()
    sign_w = m / "detector_sinais" / "checkpoint_best_total.pth"
    cont_w = next((p for p in (m / "detector_ecopontos_final" / "checkpoint_best_total.pth", m / "detector_ecopontos" / "checkpoint_best_total.pth") if p.exists()),
                  m / "detector_ecopontos_final" / "checkpoint_best_total.pth")      # o FINAL (Porto, anotações finais, 2 classes) tem prioridade; o antigo só se faltar
    hier = m / "hier_sinal_mtsd" / "manifest.json"
    luz_w = m / "detector_luz" / "checkpoint_best_total.pth"
    cont3_w = m / "detector_ecopontos3" / "checkpoint_best_total.pth"
    flux_w = next((p for p in (m / "classificador_fluxo4.pt", m / "subclassifier_residuos_v2.pt", m / "subclassifier_residuos.pt") if p.exists()), m / "classificador_fluxo4.pt")
    cont3 = settings.containers_model == "3classes"
    bench_w = settings.bench_weights
    hf = m / "hf_cache" / "hub"
    clip_w = hf / "models--openai--clip-vit-base-patch32"

    def ver(p: Path, fallback: str) -> str:
        return _fp(p) if p.exists() and p.is_file() else fallback

    reg.register_detector(DetectorSpec("signs_rfdetr", "sinal", lambda s: RFDetrDetector(s, _need(sign_w, "detetor de sinais"),
                                                                                         {"regulamentacao", "perigo", "informacao", "complementar", "orientacao_outros"}),
                                       ver(sign_w, "signs_rfdetr@sem-pesos"), weights=sign_w, note="RF-DETR treinado no MTSD (CC BY-NC-SA: direitos por verificar)"))
    if cont3:
        reg.register_detector(DetectorSpec("containers3_rfdetr", "residuos", lambda s: RFDetrDetector(s, _need(cont3_w, "detetor de contentores (3 classes)"), {"contentor", "subterraneo", "papeleira"}),
                                           ver(cont3_w, "containers3_rfdetr@sem-pesos"), weights=cont3_w, note="RF-DETR Small a partir dos pesos COCO, treinado com imagens do Porto (papeleira nativa; sem o filtro CLIP de papeleiras)"))
    else:
        reg.register_detector(DetectorSpec("containers_rfdetr", "residuos", lambda s: RFDetrDetector(s, _need(cont_w, "detetor de contentores"), {"contentor", "subterraneo"}),
                                           ver(cont_w, "containers_rfdetr@sem-pesos"), weights=cont_w, note="RF-DETR Small a partir dos pesos COCO, só Porto, anotações finais, 2 classes, sem papeleira (detector_ecopontos_final); se faltar usa detector_ecopontos"))
    reg.register_detector(DetectorSpec("lights_rfdetr", "iluminacao", lambda s: RFDetrDetector(s, _need(luz_w, "detetor de luz"), {"candeeiro", "poste_luz"}),
                                       ver(luz_w, "lights_rfdetr@sem-pesos"), weights=luz_w, note="RF-DETR Small a partir dos pesos COCO, treinado com Lisboa + Porto (v2); dá a classe candeeiro/poste_luz"))
    reg.register_detector(DetectorSpec("bench_rfdetr", "mobiliario", lambda s: BenchBackend(s, _need(bench_w, "detetor de bancos")), ver(bench_w, "bench_rfdetr@sem-pesos"), weights=bench_w,
                                       note="RF-DETR Small COCO por omissão (rf-detr-small.pth, 386 MB, sha256 d81979a9...); UMS_BENCH_VARIANT=medium usa o rf-detr-medium.pth (sha256 749ff607...); ou definir BENCH_RFDETR_WEIGHTS"))

    reg.register_classifier(ClassifierSpec("sign_type", "sign_type", "sinal", lambda s: SignTypeClassifier(s, _need(hier, "classificador de sinais"), dev),
                                           ver(hier, "hier_sinal_mtsd@sem-pesos"), crop_pad=0.15, min_side=24, weights=hier.parent, note="router + especialistas (MTSD)"))
    if not cont3:                                      # com o detetor de 3 classes a papeleira já vem do detetor: o filtro CLIP fica desligado
        reg.register_classifier(ClassifierSpec("papeleira_filter", "papeleira", "residuos", lambda s: PapeleiraClassifier(s, dev), "clip-b32-papeleiras-v1",
                                               only_cls=("contentor", "subterraneo"), crop_pad=0.15, weights=clip_w, note="CLIP ViT-B/32 (cache do Hugging Face)"))
    reg.register_classifier(ClassifierSpec("container_flux", "container_flux", "residuos", lambda s: FluxClassifier(s, _need(flux_w, "classificador de fluxo"), dev),
                                           ver(flux_w, "container_flux@sem-pesos"), only_cls=("contentor", "subterraneo"), crop_pad=0.08, min_side=12, weights=flux_w,
                                           note="DINOv2-small do tipo do caixote: classificador_fluxo4.pt (4 classes, waste_container + recortes do Porto; ~40 % em recortes novos) ou, sem ele, o antigo de 7 labels"))
    # módulos de apoio que não passam pelo registo (privacidade, profundidade): também precisam de pesos em UMS_MODELS_DIR
    reg.support += [("privacidade: YuNet (rostos)", m / "face_detection_yunet_2023mar.onnx", "OpenCV Zoo"),
                    ("privacidade: rostos (RF-DETR)", m / "detector_rostos" / "checkpoint_best_total.pth", "RF-DETR Small treinado no Open Images (CC BY): atribuição em licencas/oi_atribuicoes.csv"),
                    ("privacidade: matrículas (RF-DETR)", m / "detector_matriculas" / "checkpoint_best_total.pth", "RF-DETR Small treinado no Open Images (CC BY); NÃO validado em Aveiro (discorda do YOLO)"),
                    ("privacidade: pessoas e veículos (RF-DETR COCO)", m / "bench_detector" / "rf-detr-small.pth", "Apache-2.0; o mesmo ficheiro do detetor de bancos"),
                    ("profundidade: Depth Anything V2 Small", hf / "models--depth-anything--Depth-Anything-V2-Metric-Outdoor-Small-hf", "usado pelo agrupamento (pipeline/), não pelo pacote"),
                    ("DINOv2-small", hf / "models--facebook--dinov2-small", "Apache-2.0; o tipo do caixote e os embeddings da deduplicação"),
                    ("deduplicação: pontuação p(mesmo objeto)", m / "dedup" / "pontuacao_p.joblib", "regressão logística (scikit-learn), treinada nas rondas 1 a 3; limiares.json ao lado"),
                    ("deduplicação: emparelhador EfficientLoFTR", hf / "models--zju-community--efficientloftr", "Apache-2.0; scripts/deduplicar.py")]
    return reg
