"""Raiz do repositório: de onde se leem `configs/`, `data/` e `models/`.

Em instalação editável (`pip install -e .`) é a pasta que contém `src/`. Para correr noutro sítio, definir a variável CTRLF_ROOT.
"""
import os
from pathlib import Path

ROOT = Path(os.environ.get("CTRLF_ROOT") or Path(__file__).resolve().parents[2])
