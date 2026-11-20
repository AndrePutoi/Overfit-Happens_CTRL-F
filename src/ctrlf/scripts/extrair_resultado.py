"""Extrai o RESULTADO FINAL de uma zona: os elementos únicos (um por objeto, com as várias vistas já fundidas), em GeoJSON.

    python -m ctrlf.scripts.extrair_resultado <zona>     # -> data/zonas/<zona>/resultado/elementos_unicos.geojson

Lê o pacote de entrega mais recente (`Entrega_C/entrega_<zona>_*.zip`, produzido pela etapa `entrega`) e valida que é JSON estrito (sem NaN)
e que todas as posições são finitas. O ficheiro `elementos_unicos.geojson` é o que se usa a jusante; o resto do pacote (deteções, imagens, ilhas,
duplicados, esquemas) fica como material de apoio para quem quiser auditar um elemento.
"""
from __future__ import annotations

import json
import math
import sys
import zipfile
from pathlib import Path

from ctrlf.paths import ROOT


def main(argv: list[str] | None = None) -> int:
    a = sys.argv[1:] if argv is None else argv
    if len(a) != 1:
        print("uso: python -m ctrlf.scripts.extrair_resultado <zona>")
        return 2
    zona = a[0]
    zips = sorted((ROOT / "Entrega_C").glob(f"entrega_{zona}_*.zip"))
    if not zips:
        print(f"não há pacote de entrega para {zona!r} em Entrega_C/ (corre antes a etapa `entrega`)")
        return 1
    with zipfile.ZipFile(zips[-1]) as zf:
        nome = next((n for n in zf.namelist() if n.endswith("elementos_unicos.geojson")), None)
        if nome is None:
            print(f"{zips[-1].name} não tem elementos_unicos.geojson")
            return 1
        bruto = zf.read(nome)

    def estrito(c):
        raise ValueError(f"o resultado tem {c} (não é JSON válido)")

    dados = json.loads(bruto, parse_constant=estrito)
    for f in dados["features"]:
        if not all(isinstance(x, (int, float)) and math.isfinite(x) for x in f["geometry"]["coordinates"]):
            raise ValueError(f"elemento {f['properties']['id']} com coordenadas não finitas")
    out = ROOT / "data" / "zonas" / zona / "resultado" / "elementos_unicos.geojson"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(bruto)
    por_familia: dict[str, int] = {}
    for f in dados["features"]:
        k = f["properties"].get("family", "?")
        por_familia[k] = por_familia.get(k, 0) + 1
    print(f"{len(dados['features'])} elementos únicos {por_familia} -> {out.relative_to(ROOT)} (pacote {zips[-1].name})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
