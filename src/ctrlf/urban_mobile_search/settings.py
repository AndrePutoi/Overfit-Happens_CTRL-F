"""Configuração. Tudo se pode sobrepor por variáveis de ambiente UMS_* (a aplicação não precisa de editar ficheiros)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from ctrlf.paths import ROOT as PKG_ROOT

# categoria do CVAT / COCO -> (família, classe). Fonte única para importar e exportar COCO.
CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "contentor": ("residuos", "contentor"), "subterraneo": ("residuos", "subterraneo"), "papeleira": ("residuos", "papeleira"),
    "banco": ("mobiliario", "banco"),
    "poste_luz": ("iluminacao", "poste_luz"), "candeeiro": ("iluminacao", "candeeiro"), "poste_eletrico": ("iluminacao", "poste_eletrico"),
    **{f: ("sinal", f) for f in ("regulamentacao", "perigo", "informacao", "complementar", "orientacao_outros")},
}
# atributo do CVAT -> tarefa de classificação
ATTR_TASKS = {"fluxo": "container_flux", "tipo": "sign_type"}
# Etiquetas FIXAS por classe (regra, não modelo): a papeleira não recebe os labels do waste_container, é só indiferenciado.
FIXED_LABELS: dict[tuple[str, str], dict[str, str]] = {("residuos", "papeleira"): {"container_flux": "indiferenciado"}}


@dataclass
class Settings:
    project_root: Path = PKG_ROOT                     # onde estão detection/, privacy/, ingest/, geometry/, common/ (fase 1: o repositório)
    models_dir: Path = PKG_ROOT / "models"
    db_path: Path = PKG_ROOT / "data" / "ums.sqlite"
    images_dir: Path = PKG_ROOT / "data" / "images_anon"
    device: str = "auto"                              # auto | cuda | cpu
    families: tuple[str, ...] = ("sinal", "residuos", "iluminacao")
    conf: dict = field(default_factory=lambda: {"sinal": 0.3, "residuos": 0.3, "iluminacao": 0.3, "mobiliario": 0.5})     # sinal 0,3 (decisão do utilizador, 2026-11-20: tentou-se 0,6 e voltou-se atrás); UMS_CONF_SINAL ajusta
    min_side: dict = field(default_factory=lambda: {"sinal": 24, "residuos": 8, "iluminacao": 8, "mobiliario": 16})     # px: caixas mais pequenas descartam-se
    sign_not_sign_thr: float = 0.5                    # router diz nao_sinal com p >= isto -> descarta
    papeleira_thr: dict = field(default_factory=lambda: {"contentor": 0.8, "subterraneo": 0.97})
    flux_unknown_thr: float = 0.0                     # 0 = usa SEMPRE o label do waste_container mais provável (a confiança fica guardada); >0: abaixo disto, 'desconhecido'
    light_reject: float = 0.5                         # p_rejeitar do CLIP >= isto -> descarta
    light_policy: dict = field(default_factory=dict)  # ex.: {"so_candeeiro": True, "pc_min": 0.25} (política de Lisboa)
    keep_models_loaded: bool = False                  # False: descarrega os modelos de cada família antes da seguinte (GPU de 6 GB)
    bench_variant: str = "small"                      # small | medium: detetor de bancos (RF-DETR COCO, sem fine-tuning). Small por decisão do utilizador (2026-11-20); o catálogo de Aveiro de 20/11 foi feito com o medium
    light_detector: str = "rfdetr"                    # só rfdetr: o Grounding DINO saiu da pipeline (fica só como demonstração de pré-anotação em demo_grounding_dino/); se faltarem os pesos, a luz falha com mensagem clara
    containers_model: str = "2classes"                # 2classes (contentor/subterraneo; o que alimenta o catálogo 1.3) | 3classes (+ papeleira nativa; sem o filtro CLIP)
    locate: bool = False                              # calcula azimute (e posição, quando o IPM se aplica) por deteção
    cam_height_m: float = 1.5

    # ---- onde ficam os pesos (UMS_MODELS_DIR): um ficheiro/pasta por módulo, ver `python -m ctrlf weights`
    @property
    def bench_weights(self) -> Path:
        return Path(__import__("os").environ.get("BENCH_RFDETR_WEIGHTS") or self.models_dir / "bench_detector" / f"rf-detr-{self.bench_variant}.pth")

    @classmethod
    def from_env(cls, **over) -> "Settings":
        e = os.environ
        root = Path(e.get("UMS_PROJECT_ROOT", PKG_ROOT))
        s = cls(project_root=root, models_dir=Path(e.get("UMS_MODELS_DIR", root / "models")), db_path=Path(e.get("UMS_DB", root / "data" / "ums.sqlite")),
                images_dir=Path(e.get("UMS_IMAGES_DIR", root / "data" / "images_anon")), device=e.get("UMS_DEVICE", "auto"))
        if "UMS_LIGHT_DETECTOR" in e:
            if e["UMS_LIGHT_DETECTOR"] not in ("auto", "rfdetr"):
                raise ValueError(f"UMS_LIGHT_DETECTOR={e['UMS_LIGHT_DETECTOR']!r}: o Grounding DINO saiu da pipeline; só existe o RF-DETR de luz")
            s.light_detector = "rfdetr"
        if "UMS_BENCH_VARIANT" in e:
            s.bench_variant = e["UMS_BENCH_VARIANT"]
        if "UMS_CONTAINERS" in e:
            s.containers_model = e["UMS_CONTAINERS"]
        if "UMS_CONF_SINAL" in e:
            s.conf["sinal"] = float(e["UMS_CONF_SINAL"])
        if "UMS_FAMILIES" in e:
            s.families = tuple(x for x in e["UMS_FAMILIES"].split(",") if x)
        for k, v in over.items():
            setattr(s, k, v)
        return s

    def resolve_device(self) -> str:
        if self.device != "auto":
            return self.device
        try:
            import torch
            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"
