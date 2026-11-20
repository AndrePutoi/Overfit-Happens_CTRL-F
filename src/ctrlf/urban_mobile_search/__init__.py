"""urban_mobile_search: deteção e classificação de mobiliário urbano (sinais, resíduos, iluminação) a partir de imagens de rua.

Camada de aplicação sobre os modelos do projeto: registo de detetores/classificadores, pipeline (admissão -> privacidade -> deteção ->
classificação -> posição) e armazenamento de deteções, classificações e decisões do técnico. Ver docs/URBAN_MOBILE_SEARCH.md.
"""
from .models import Classification, Detection, ImageResult, detection_id, iou
from .pipeline import Pipeline
from .registry import ClassifierSpec, DetectorSpec, Registry
from .settings import ATTR_TASKS, CATEGORY_MAP, Settings
from .store import Store

__version__ = "0.1.0"
__all__ = ["Classification", "Detection", "ImageResult", "Pipeline", "Registry", "DetectorSpec", "ClassifierSpec", "Settings", "Store",
           "CATEGORY_MAP", "ATTR_TASKS", "detection_id", "iou", "__version__"]
