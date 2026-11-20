"""Orquestração por ZONA: de uma caixa geográfica ao pacote de entrega, etapa a etapa, com estado e retoma.

    python -m ctrlf zona run lisboa_teste --bbox -9.1385 38.7075 -9.1340 38.7105 --since 2023-01-01 --max 16 --max-panoramas 3
    python -m ctrlf zona status lisboa_teste        # o que está feito, o que falta, tempos, contagens
    python -m ctrlf zona plan lisboa_teste          # lista as etapas e os comandos, sem correr nada

Ver `etapas.py` (a cadeia), `runner.py` (estado, retoma, portões) e docs/ORQUESTRACAO.md.
"""
from .etapas import ETAPAS, Zona, nomes_etapas
from .runner import Falha, correr, estado_de, resumo

__all__ = ["ETAPAS", "Zona", "nomes_etapas", "Falha", "correr", "estado_de", "resumo"]
