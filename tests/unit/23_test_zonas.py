"""Registo e criação de zonas (ingest/zonas.py): validação de nomes, caixa em torno de um ponto, geocodificação OSM simulada (sem rede), zona.json e integração com a admissão/OSM. Sem GPU."""
import json
import sys
import tempfile
from pathlib import Path

from ctrlf.paths import ROOT
sys.path.insert(0, str(ROOT))
from ctrlf.ingest import zonas as Z  # noqa: E402

res = {}
with tempfile.TemporaryDirectory() as td:
    Z.ZONAS_DIR = Path(td)

    def falso(url, params, headers):
        res["_ua"] = headers.get("User-Agent")
        res["_q"] = params["q"]
        return [{"lat": "38.7092", "lon": "-9.1365", "display_name": "Baixa, Lisboa, Portugal", "osm_type": "relation", "osm_id": 123}] if "lisboa" in params["q"].lower() else []

    z = Z.criar("lisboa_x", lugar="Baixa, Lisboa", raio_m=250, http_get=falso)
    o, s, e, n = z["bbox"]
    res["T1 caixa em torno do ponto: ordem [O,S,E,N], centro dentro, ~500 m de lado"] = (o < -9.1365 < e and s < 38.7092 < n and 0.0035 < (n - s) < 0.0055 and 0.004 < (e - o) < 0.0075)
    res["T2 só o texto do sítio vai à rede, com um User-Agent genérico (sem dados pessoais)"] = res["_q"] == "Baixa, Lisboa" and res["_ua"] == Z.USER_AGENT and "@" not in Z.USER_AGENT
    mz = Z.pasta("lisboa_x") / "mapa_zona.html"
    res["T3b ao definir a zona cria-se o mapa de pré-visualização com a caixa (Leaflet, OSM)"] = mz.exists() and str(z["bbox"][1]) in mz.read_text(encoding="utf-8") and "leaflet" in mz.read_text(encoding="utf-8").lower() and "L.rectangle" in mz.read_text(encoding="utf-8")
    f = Z.pasta("lisboa_x") / "zona.json"
    res["T3 zona.json gravado com a fonte (OSM, ODbL), limites e raio"] = f.exists() and json.loads(f.read_text(encoding="utf-8"))["fonte_da_caixa"]["tipo"] == "osm_nominatim" and json.loads(f.read_text(encoding="utf-8"))["max"] == 20
    res["T4 carregar/todas/caixa_swne"] = Z.carregar("lisboa_x")["nome"] == "lisboa_x" and "lisboa_x" in Z.todas() and Z.caixa_swne(z)[0] == s
    for nome_mau in ("Lisboa X", "../x", "a", "x" * 50, "Lisboa"):
        try:
            Z.validar_nome(nome_mau); res[f"T5 nome inválido aceite: {nome_mau!r}"] = False
        except ValueError:
            pass
    res["T5 nomes inválidos (maiúsculas, espaços, ../, curtos, longos) recusados"] = not any(k.startswith("T5 nome inválido") for k in res)
    for nome_mau, kw in (("sem_nada", {}), ("ambos", {"lugar": "x", "centro": (1.0, 2.0)}), ("raio_mau", {"centro": (38.7, -9.1), "raio_m": 5000}), ("nao_existe", {"lugar": "xyzzy"})):
        try:
            Z.criar(nome_mau, http_get=falso, **kw); res[f"T6 pedido inválido aceite: {nome_mau}"] = False
        except ValueError:
            pass
    res["T6 pedidos inválidos recusados (sem local, ambos, raio fora de 50–1500 m, sítio inexistente)"] = not any(k.startswith("T6 pedido inválido") for k in res)
    try:
        Z.guardar({"nome": "caixa_mal", "bbox": [-9.1, 38.7, -9.2, 38.8]})
        res["T7 caixa invertida recusada"] = False
    except ValueError:
        res["T7 caixa invertida recusada"] = True

for k, v in res.items():
    if not k.startswith("_"):
        print(f"{'PASS' if v else 'FAIL'}  {k}")
ok = all(v for k, v in res.items() if not k.startswith("_"))
print("overall:", "PASS" if ok else "FAIL")
sys.exit(0 if ok else 1)
