"""Garante que o limiar de confiança dos SINAIS é 0,3 em todo o lado (decisão do utilizador, 2026-11-20: a tentativa de 0,6 foi revertida).
Falha se alguém mudar um destes valores sem decidir de novo. Sem GPU nem pesos."""
import os
import re
import sys
from pathlib import Path

from ctrlf.paths import ROOT
os.environ.pop("UMS_CONF_SINAL", None)
res = {}

from ctrlf.urban_mobile_search import Settings  # noqa: E402

res["T1 Settings (usado pelo Pipeline, pelo detetar_zona e pelo orquestrador): sinal = 0.3"] = Settings.from_env().conf["sinal"] == 0.3
res["T2 as outras famílias não mudaram: luz 0.3, resíduos 0.3, bancos 0.5"] = all(Settings.from_env().conf[k] == v for k, v in (("iluminacao", 0.3), ("residuos", 0.3), ("mobiliario", 0.5)))
os.environ["UMS_CONF_SINAL"] = "0.45"
res["T3 UMS_CONF_SINAL ainda permite ajustar à mão"] = Settings.from_env().conf["sinal"] == 0.45
os.environ.pop("UMS_CONF_SINAL")

yml = (ROOT / "configs" / "pipeline.yaml").read_text(encoding="utf-8")
res["T5 configs/pipeline.yaml: conf 0.3"] = bool(re.search(r"^\s*conf:\s*0\.3\b", yml, re.M))
eg = (ROOT / "src" / "ctrlf" / "pipeline" / "export_geojson.py").read_text(encoding="utf-8")
res["T6 export_geojson: --min-score por omissão 0.0 (o catálogo não corta sinais por score)"] = bool(re.search(r'add_argument\("--min-score",\s*type=float,\s*default=0\.0\)', eg))
ex = (ROOT / "src" / "ctrlf" / "scripts" / "exportar_entrega.py").read_text(encoding="utf-8")
res["T7 exportar_entrega: --remover-sinais-abaixo desligado por omissão (None)"] = bool(re.search(r'"--remover-sinais-abaixo",\s*type=float,\s*default=None', ex))
dz = (ROOT / "src" / "ctrlf" / "scripts" / "detetar_zona.py").read_text(encoding="utf-8")
res["T8 detetar_zona não tem limiar próprio (herda do Settings)"] = "conf" not in re.sub(r"#.*|\"\"\"[\s\S]*?\"\"\"", "", dz).replace("conf_", "").split("def processar_blocos")[1].split("def escrever_coco")[0].replace("s.conf", "X") or "s.conf" not in dz

for k, v in res.items():
    print(f"{'PASS' if v else 'FAIL'}  {k}")
ok = all(res.values())
print("overall:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
