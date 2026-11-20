"""Exporta os PESOS da pipeline para UMA pasta organizada (a que o pacote lê com UMS_MODELS_DIR), com manifesto e verificação.

    python -m ctrlf.scripts.exportar_pesos --out pesos_ctrlf            # copia só o necessário (produção + candidatos + apoio) e escreve PESOS_MANIFEST.json
    python -m ctrlf.scripts.exportar_pesos --verificar pesos_ctrlf      # confere sha256 de tudo e que o pacote vê os pesos (urban_mobile_search weights)

Layout = o que `urban_mobile_search` espera: detector_<x>/checkpoint_best_total.pth, hier_sinal_mtsd/, classificador_fluxo4.pt, bench_detector/, dedup/, privacidade (yunet, faces, plates), hf_cache/hub/models--*.
Só entram os checkpoints `best` (130 MB cada), não os de retoma (1 GB+). As versões ficam no manifesto; os nomes na pasta não levam sufixo de versão.
NÃO cria nenhum zip: o zip dos pesos só se faz com a autorização do utilizador (há licenças por esclarecer, ver LEIA-ME_PESOS.md).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from ctrlf.paths import ROOT
M = ROOT / "models"

# (origem relativa a models/, destino relativo, papel, estado, licença, proveniência, métrica, usado por)
FICHEIROS = [
    ("detector_sinais/checkpoint_best_total.pth", "detector_sinais/checkpoint_best_total.pth", "Detetor de sinais: RF-DETR Small, 5 famílias do MTSD, 768 px", "producao",
     "RF-DETR Apache-2.0; treinado no MTSD (CC BY-NC-SA): os pesos herdam o uso NÃO comercial até haver clarificação", "afinado a partir de rf-detr-small.pth (COCO) no MTSD; 10 épocas; lote 2 x 8",
     "mAP50-95 EMA 0,480 (época 8, validação MTSD); sem exatidão medida em Aveiro", "familia sinal; scripts de previsão de sinais"),
    ("detector_rostos/checkpoint_best_total.pth", "detector_rostos/checkpoint_best_total.pth", "Privacidade: detetor de rostos RF-DETR Small, 1 classe, 768 px (omissão da privacidade; substitui o YOLO)", "producao",
     "RF-DETR Apache-2.0; treinado no Open Images V7 (imagens CC BY 2.0, anotações CC BY 4.0 por confirmar): atribuição em licencas/oi_atribuicoes.csv", "afinado a partir de rf-detr-small.pth (COCO); 12 épocas; 5521 imagens, 34 995 caixas",
     "mAP50 0,558 (validação Open Images); recall 0,902 no teste OI, igual ao YOLO; concordância com o YOLO em Aveiro 89 % (150 vistas); sem exatidão em Aveiro", "privacy/blur_privacy.py (backend rfdetr)"),
    ("detector_matriculas/checkpoint_best_total.pth", "detector_matriculas/checkpoint_best_total.pth", "Privacidade: detetor de matrículas RF-DETR Small, 1 classe, 768 px (omissão da privacidade; substitui o YOLO)", "producao",
     "RF-DETR Apache-2.0; treinado no Open Images V7 (imagens CC BY 2.0, anotações CC BY 4.0 por confirmar): atribuição em licencas/oi_atribuicoes.csv", "afinado a partir de rf-detr-small.pth (COCO); 12 épocas; 6849 imagens (5355 com matrícula + 1494 negativas)",
     "mAP50 0,649 (validação Open Images); recall 0,429 contra 0,375 do YOLO no teste OI; EM AVEIRO quase não concorda com o YOLO anterior (cobre 7 % das 69 caixas); auditoria visual feita por um colega da equipa com resultado satisfatório (relato da equipa; números não registados)", "privacy/blur_privacy.py (backend rfdetr)"),
    ("detector_ecopontos_final/checkpoint_best_total.pth", "detector_ecopontos/checkpoint_best_total.pth", "Detetor de contentores: RF-DETR Small, `contentor`/`subterraneo`, 512 px. VERSÃO FINAL: só anotações finais do Porto, sem papeleiras (a papeleira passa a fundo e trata-se com o filtro CLIP)", "producao",
     "RF-DETR Apache-2.0; treinado em imagens do Mapillary do Porto (CC BY-SA 4.0: efeito sobre os pesos por esclarecer)", "afinado a partir de rf-detr-small.pth (COCO); 30 épocas; Porto: 792 imagens e 476 caixas de treino, 226 imagens e 152 caixas de validação (divisão por panorama)",
     "mAP50-95 0,432 (validação do Porto: contentor 0,315, subterrâneo 0,550; test = cópia da validação); sem exatidão medida em Aveiro", "familia residuos (catálogo 1.3)"),
    ("detector_luz_v2/checkpoint_best_total.pth", "detector_luz/checkpoint_best_total.pth", "Detetor de luz: RF-DETR Small, `candeeiro`/`poste_luz`, 768 px (v2: Lisboa + Porto)", "producao",
     "RF-DETR Apache-2.0; treinado em imagens do Mapillary de Lisboa e Porto (CC BY-SA 4.0)", "afinado a partir de rf-detr-small.pth (COCO); paragem antecipada na época 20; 1180 imagens, 2328 caixas",
     "mAP50-95 EMA 0,539 (validação Lisboa + Porto; 83 % das caixas do Porto são pré-anotações do v1, por isso é favorável); 0,383 em Lisboa nunca vista; sem exatidão em Aveiro", "familia iluminacao (UMS_LIGHT_DETECTOR=auto)"),
    ("bench_detector/rf-detr-small.pth", "bench_detector/rf-detr-small.pth", "Detetor de bancos: RF-DETR Small COCO oficial, só a classe `bench` (id 15), SEM fine-tuning; também é o ponto de partida de todos os treinos RF-DETR", "producao",
     "Apache-2.0 (checkpoint oficial da Roboflow, sha256 d81979a9…)", "https://repo.roboflow.com/rfdetr/small_coco/checkpoint_best_regular.pth", "AP@0,5 0,76 em 20 imagens COCO (pacote do colega); sem exatidão em Aveiro",
     "familia mobiliario (scripts/prever_bancos_aveiro.py)"),
    ("hier_sinal_mtsd/router.pt", "hier_sinal_mtsd/router.pt", "Classificador de sinais: router (família ou `nao_sinal`), DINOv2-small", "producao",
     "MTSD (CC BY-NC-SA, não comercial) + negativos de Aveiro; DINOv2 Apache-2.0", "afinado a partir de facebook/dinov2-small", "172 tipos; 17 % `desconhecido` em Aveiro; viés para «passadeira»", "tipo do sinal"),
    ("hier_sinal_mtsd/esp_complementar.pt", "hier_sinal_mtsd/esp_complementar.pt", "Classificador de sinais: especialista complementar", "producao", "idem", "idem", "idem", "tipo do sinal"),
    ("hier_sinal_mtsd/esp_informacao.pt", "hier_sinal_mtsd/esp_informacao.pt", "Classificador de sinais: especialista informação", "producao", "idem", "idem", "idem", "tipo do sinal"),
    ("hier_sinal_mtsd/esp_perigo.pt", "hier_sinal_mtsd/esp_perigo.pt", "Classificador de sinais: especialista perigo", "producao", "idem", "idem", "idem", "tipo do sinal"),
    ("hier_sinal_mtsd/esp_regulamentacao.pt", "hier_sinal_mtsd/esp_regulamentacao.pt", "Classificador de sinais: especialista regulamentação", "producao", "idem", "idem", "idem", "tipo do sinal"),
    ("hier_sinal_mtsd/manifest.json", "hier_sinal_mtsd/manifest.json", "Manifesto da hierarquia de sinais", "producao", "idem", "idem", "", "tipo do sinal"),
    ("classificador_fluxo4_porto_final.pt", "classificador_fluxo4.pt", "Classificador do tipo do caixote: DINOv2-small, 4 classes (indiferenciado, papel, embalagens, vidro). VERSÃO FINAL: só com as anotações do Porto, sem waste_container", "producao",
     "recortes do Porto (CC BY-SA 4.0: efeito sobre os pesos por esclarecer); sem waste_container", "DINOv2-small original + 627 recortes do Porto (387 indiferenciado, 102 embalagens, 79 papel, 59 vidro); amostragem equilibrada, 19 épocas",
     "validação cruzada por panorama (5 dobras, 20 épocas, n = 627): exatidão 63,2 %, equilibrada 62,6 %: SUGESTÃO, não verdade; sem exatidão medida em Aveiro", "tipo do caixote; ilhas de reciclagem"),
    ("subclassifier_residuos_v2.pt", "subclassifier_residuos_v2.pt", "Classificador antigo do tipo do caixote, 7 labels (LEGADO, só se não houver o de 4 classes)", "legado",
     "idem", "DINOv2-small + waste_container (7 labels), divisão por grupo", "56 % (mapeado) nos 25 recortes do Porto", "fallback do registo"),
    ("dedup/pontuacao_p.joblib", "dedup/pontuacao_p.joblib", "Deduplicação: p(mesmo objeto), regressão logística sobre aparência + geometria", "producao", "código e modelo da equipa (sem licença definida)",
     "treinado com 901 pares rotulados (rondas 1 a 3)", "AUC 0,897 em pares novos (ronda 3, modelo congelado); 0,898 ao nível do elemento (ronda 4)", "scripts/deduplicar.py"),
    ("dedup/pontuacao_p.json", "dedup/pontuacao_p.json", "Descrição do modelo p", "producao", "idem", "idem", "", "documentação"),
    ("dedup/limiares.json", "dedup/limiares.json", "Calibração da confiança e limiar automático por família (0,85 em sinais, contentores e luz)", "producao", "idem",
     "ronda 4 (356 itens); luz por decisão do utilizador (6 casos)", "sinais 79/80 e contentores/ilha 34/35 nos grupos prováveis", "scripts/deduplicar.py; exportar_entrega"),
    ("face_detection_yunet_2023mar.onnx", "face_detection_yunet_2023mar.onnx", "Privacidade: YuNet (rostos)", "apoio", "OpenCV Zoo (MIT, a confirmar)", "OpenCV Zoo", "", "privacy/gate.py"),
]
HF = [  # (repo, papel, licença, usado por, opcional)
    ("models--facebook--dinov2-small", "DINOv2-small: base dos classificadores e embeddings da deduplicação e da pesquisa visual", "Apache-2.0", "classificadores; deduplicação; pesquisa visual", False),
    ("models--openai--clip-vit-base-patch32", "CLIP ViT-B/32: verificador de suspeitos e filtro de papeleiras", "MIT (a confirmar)", "detection/postfilter", False),
    ("models--depth-anything--Depth-Anything-V2-Metric-Outdoor-Small-hf", "Depth Anything V2 métrico (Small): distância de cada caixa", "Apache-2.0 (as variantes maiores são CC BY-NC)", "geometry/depth.py", False),
    ("models--zju-community--efficientloftr", "EfficientLoFTR: emparelhador de pontos da deduplicação", "Apache-2.0", "scripts/deduplicar.py", False),
    ("models--IDEA-Research--grounding-dino-tiny", "Grounding DINO Tiny: detetor zero-shot (só para a demonstração de pré-anotação em demo_grounding_dino/ e os testes unitários 03, 04 e 07)", "Apache-2.0", "demo_grounding_dino/; testes", True),
]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(1 << 22), b""):
            h.update(b)
    return h.hexdigest()


def tree_sha(d: Path) -> tuple[int, str]:
    """(bytes, sha256 do conjunto) de uma pasta: hash de (caminho relativo + sha256 de cada ficheiro regular, seguindo os links)."""
    h, tot = hashlib.sha256(), 0
    for p in sorted(x for x in d.rglob("*") if x.is_file()):
        h.update(str(p.relative_to(d)).encode()); h.update(sha256(p).encode()); tot += p.stat().st_size
    return tot, h.hexdigest()


def exportar(out: Path, com_gdino: bool) -> None:
    if out.exists():
        sys.exit(f"{out} já existe: apaga-a ou escolhe outro nome (não escrevo por cima).")
    out.mkdir(parents=True)
    itens, t0 = [], time.time()
    for orig, dest, papel, estado, lic, prov, met, uso in FICHEIROS:
        src = M / orig
        if not src.exists():
            print(f"  AVISO: falta {src}", flush=True); continue
        (out / dest).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out / dest, follow_symlinks=True)
        itens.append({"path": dest, "tipo": "ficheiro", "papel": papel, "estado": estado, "bytes": (out / dest).stat().st_size, "sha256": sha256(out / dest), "licenca": lic, "proveniencia": prov,
                      "metricas": met, "usado_por": uso, "origem_no_repositorio": f"models/{orig}"})
        print(f"  {dest}  ({itens[-1]['bytes'] / 1e6:.0f} MB)", flush=True)
    hub_src, hub = M / "hf_cache" / "hub", out / "hf_cache" / "hub"
    hub.mkdir(parents=True, exist_ok=True)
    for repo, papel, lic, uso, opc in HF:
        if opc and not com_gdino:
            continue
        s = hub_src / repo
        if not s.exists():
            print(f"  AVISO: falta {s}", flush=True); continue
        # Na cache de origem os ficheiros de `snapshots/` são links para uma pasta `blobs/` comum: copiam-se os ficheiros REAIS (sem os links), só `refs/` e `snapshots/`,
        # que é o que o Hugging Face lê offline (`blobs/` não é preciso e duplicaria os dados).
        rev = (s / "refs" / "main").read_text().strip()                 # só a revisão a que `main` aponta (algumas caches têm duas, com o mesmo modelo em formatos diferentes)
        shutil.copytree(s / "refs", hub / repo / "refs")
        shutil.copytree(s / "snapshots" / rev, hub / repo / "snapshots" / rev, symlinks=False)
        b, h = tree_sha(hub / repo)
        itens.append({"path": f"hf_cache/hub/{repo}", "tipo": "pasta (cache do Hugging Face: refs + snapshots)", "papel": papel, "estado": "apoio", "bytes": b, "sha256": h, "licenca": lic, "proveniencia": "Hugging Face Hub",
                      "metricas": "", "usado_por": uso, "origem_no_repositorio": f"models/hf_cache/hub/{repo}"})
        print(f"  hf_cache/hub/{repo}  ({b / 1e6:.0f} MB)", flush=True)
    oi = ROOT / "data" / "oi_cache" / "LICENCAS.csv"                   # atribuição das imagens de treino dos detetores de rostos e matrículas (Open Images, CC BY 2.0: exige indicar o autor)
    if oi.exists():
        (out / "licencas").mkdir(exist_ok=True)
        shutil.copy2(oi, out / "licencas" / "oi_atribuicoes.csv")
        itens.append({"path": "licencas/oi_atribuicoes.csv", "tipo": "ficheiro", "papel": "Atribuição (autor, licença, origem) das imagens do Open Images usadas para treinar rostos e matrículas", "estado": "apoio",
                      "bytes": (out / "licencas" / "oi_atribuicoes.csv").stat().st_size, "sha256": sha256(out / "licencas" / "oi_atribuicoes.csv"), "licenca": "lista de atribuições (CC BY 2.0 exige indicar o autor)",
                      "proveniencia": "Open Images V7 (metadados oficiais)", "metricas": "", "usado_por": "detector_rostos, detector_matriculas", "origem_no_repositorio": "data/oi_cache/LICENCAS.csv"})
        print(f"  licencas/oi_atribuicoes.csv  ({itens[-1]['bytes'] / 1e6:.1f} MB)", flush=True)
    man = {"gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"), "como_usar": "export UMS_MODELS_DIR=<esta pasta> ; HF_HOME=<esta pasta>/hf_cache", "total_bytes": sum(i["bytes"] for i in itens),
           "contagem": {k: sum(1 for i in itens if i["estado"] == k) for k in ("producao", "candidato", "apoio", "legado")}, "itens": itens,
           "nao_exportado": ["detector_luz v1, detector_ecopontos3 v1, hier_sinal_gtsrb e classificadores antigos (descontinuados)", "checkpoints de retoma (last.ckpt, checkpoint_<n>.ckpt)", "LightGlue/DISK (testado, não adotado)",
                             ]}
    (out / "PESOS_MANIFEST.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
    linhas = "\n".join(f"| `{i['path']}` | {i['estado']} | {i['papel']} | {i['bytes'] / 1e6:.0f} MB | {i['licenca']} |" for i in itens)
    (out / "LEIA-ME_PESOS.md").write_text(f"""# Pesos da pipeline Ctrl+F

Esta pasta é o `UMS_MODELS_DIR` do pacote `urban_mobile_search`:
```bash
export UMS_MODELS_DIR=$PWD/pesos_ctrlf          # onde estão os pesos
export HF_HOME=$UMS_MODELS_DIR/hf_cache         # modelos do Hugging Face, sem internet
python -m ctrlf weights           # lista o que o pacote encontra
python -m ctrlf.scripts.exportar_pesos --verificar $UMS_MODELS_DIR     # confere o sha256 de tudo
```
Estados: **producao** = o que alimenta a entrega atual; **candidato** = treinado e medido, ainda não adotado; **apoio** = módulos de privacidade, profundidade, emparelhamento; **legado** = só fallback.
Tamanho total: {man['total_bytes'] / 1e9:.1f} GB. Contagem: {man['contagem']}.

| Ficheiro | Estado | Papel | Tamanho | Licença / termos |
|---|---|---|---|---|
{linhas}

## AVISO DE LICENÇAS (decisão do utilizador, 2026-11-20: aceita-se enviar os pesos tal como estão e fica documentado)
**Estes pesos são para INVESTIGAÇÃO / USO NÃO COMERCIAL.** Não os usar em produto comercial sem resolver o que está abaixo:
- **Sinais (detetor e classificador, treinados no MTSD, CC BY-NC-SA):** os pesos herdam o uso **não comercial** e a partilha nas mesmas condições.
- **Tipo do caixote:** o classificador atual foi treinado só com recortes do Porto (Mapillary, CC BY-SA 4.0; efeito sobre os pesos por esclarecer). O ficheiro de reserva `subclassifier_residuos_v2.pt` (legado) foi treinado com o `waste_container`: origem e termos **por verificar**; assumir só investigação.
- **Detetores de contentores e de luz, treinados com imagens do Mapillary (CC BY-SA 4.0):** o efeito da licença sobre os pesos está **por esclarecer**; atribuição: «Imagens © colaboradores do Mapillary».
- **Privacidade (rostos e matrículas), treinada com o Open Images (imagens CC BY 2.0):** exige atribuição aos autores: `licencas/oi_atribuicoes.csv`. No ensaio de 150 vistas de Aveiro os rostos concordaram com o YOLO anterior (89 %), mas as matrículas quase não (7 %). **Uma auditoria visual feita por um colega da equipa teve resultado satisfatório** (relato da equipa; os números não estão registados). No teste do Open Images a taxa de deteção de matrículas foi de 43 %: antes de partilhar imagens fora da equipa, convém repetir a auditoria com uma amostra registada.
- **Sem YOLO / Ultralytics:** os pesos YOLO (de terceiros, licença não verificada, AGPL-3.0) **não vão neste pacote**. O código mantém um backend `yolo` opcional que exige instalar o `ultralytics` e ter os pesos por conta própria.
- RF-DETR, DINOv2, CLIP, Depth Anything V2 Small, EfficientLoFTR e YuNet: licenças permissivas (Apache-2.0 / MIT) por verificar caso a caso; ver `docs/LICENCAS_DESCOBERTAS.md` no pacote de código.
- Os números de exatidão aqui são os medidos; **nenhum detetor tem exatidão medida em Aveiro** (apps de verificação por responder).
Não exportado: {"; ".join(man['nao_exportado'])}.
""", encoding="utf-8")
    print(f"\nFEITO: {len(itens)} itens, {man['total_bytes'] / 1e9:.2f} GB, {time.time() - t0:.0f}s -> {out}", flush=True)


def verificar(d: Path) -> int:
    man = json.loads((d / "PESOS_MANIFEST.json").read_text(encoding="utf-8"))
    mal = 0
    for i in man["itens"]:
        p = d / i["path"]
        if not p.exists():
            print(f"FALTA   {i['path']}"); mal += 1; continue
        h = sha256(p) if i["tipo"] == "ficheiro" else tree_sha(p)[1]
        if h != i["sha256"]:
            print(f"DIFERE  {i['path']}"); mal += 1
    print(f"manifesto: {len(man['itens'])} itens, {mal} problemas")
    import os
    env = {**os.environ, "UMS_MODELS_DIR": str(d), "HF_HOME": str(d / "hf_cache"), "PYTHONPATH": str(ROOT)}
    r = subprocess.run([sys.executable, "-m", "urban_mobile_search", "weights"], capture_output=True, text=True, env=env, cwd=ROOT)
    try:
        j = json.loads(r.stdout[r.stdout.index("{"):])
        falta = [x["modulo"] for x in j["modulos"] if not x["existe"]]
        print(f"o pacote vê {sum(1 for x in j['modulos'] if x['existe'])}/{len(j['modulos'])} módulos; em falta: {falta}")
    except Exception:
        print("não consegui ler a saída de `urban_mobile_search weights`:", r.stderr[-200:])
    return mal


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path)
    ap.add_argument("--verificar", type=Path)
    ap.add_argument("--com-gdino", action="store_true")
    a = ap.parse_args()
    if a.verificar:
        sys.exit(1 if verificar(a.verificar) else 0)
    exportar(a.out or ROOT / "pesos_ctrlf", a.com_gdino)
