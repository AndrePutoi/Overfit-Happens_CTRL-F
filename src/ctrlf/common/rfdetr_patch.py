"""Desvio para treinar o RF-DETR sem `python3.12-dev` instalado.

O RF-DETR resolve a atribuição húngara com um kernel Triton que compila C em tempo
de execução e precisa de `Python.h`.  Se esse ficheiro não existir, o treino rebenta
com `fatal error: Python.h`.  Este módulo faz o solver correr em CPU (SciPy):
resultado idêntico, treino um pouco mais lento.

Usar ANTES de chamar `model.train(...)`:

    from ctrlf.common.rfdetr_patch import apply
    apply()

A solução limpa (e mais rápida) é:  sudo apt install python3.12-dev
"""
from __future__ import annotations

import sysconfig
from pathlib import Path


def has_python_headers() -> bool:
    return (Path(sysconfig.get_paths()["include"]) / "Python.h").exists()


def apply(force: bool = False) -> bool:
    """Devolve True se aplicou o desvio."""
    if has_python_headers() and not force:
        return False
    import rfdetr.models._assignment as A

    original = A._solve_to_indices

    def cpu_solve(stacked, num_matches):
        return original(stacked.cpu(), num_matches)   # em CPU o torch_linear_assignment usa SciPy

    A._solve_to_indices = cpu_solve
    print("[rfdetr_patch] Python.h em falta -> atribuição húngara em CPU (SciPy).")
    return True
