# 13 · Treino dos modelos

> Este capítulo é para quem quiser **voltar a treinar**. Para usar a pipeline basta o zip de pesos. Os dados de treino **não** estão neste repositório. Dependências extra: `requirements-treino.txt`.

## Visão geral
| Modelo | Dados | Preparação → treino | Notas |
|---|---|---|---|
| **Detetor de contentores** | anotações **finais do Porto** (exportação COCO do CVAT), sem papeleiras | `scripts/preparar_lixo_porto_final.py` → `treino/train_detector.py` | RF-DETR Small, 512 px, 2 classes; divisão 80/20 **por panorama** |
| **Detetor de sinais** | **MTSD v2** (8 000 imagens de treino, 1 500 de validação) | `treino/mtsd_detection_coco.py` → `treino/train_detector.py --size small --resolution 768 --batch 2 --accum 8 --epochs 10` | 5 classes (regulamentação, perigo, informação, complementar, orientação e outros) |
| **Classificador de sinais** (router + especialistas) | recortes do MTSD | `treino/mtsd_prepare.py` → `treino/train_hier_mtsd.py` | DINOv2-small + cabeça linear, 2 fases (cabeça congelada, depois backbone com lr baixo), AMP, pesos inversos à frequência |
| **Detetor de luz** | exportações COCO do CVAT de Lisboa e Porto; imagens de `images_anon` | `treino/preparar_luz_det.py` → `treino/train_detector.py` | RF-DETR Small, 768 px; classes `candeeiro` e `poste_luz`; negativos = imagens revistas sem caixas |
| **Rostos e matrículas** | **Open Images V7** | `scripts/preparar_privacidade_oi.py` → `treino/train_detector.py` | **dois** detetores de uma classe (ver abaixo) |
| **Tipo de contentor** | **627 recortes do Porto** | `scripts/preparar_lixo_porto_final.py --recortes` → `treino/train_fluxo4_porto.py cv` / `final` | DINOv2-small, 4 classes |
| **Bancos** | nenhum | | pré-treino COCO do RF-DETR; **sem treino nosso** |
| **Pontuação p(mesmo objeto)** | rondas de rotulagem manual de pares | (fora deste repositório) | regressão logística; 901 pares |

## Princípios que aprendemos (e que evitam erros caros)
1. **Dividir por panorama (ou por grupo), nunca ao acaso por imagem.** As quatro vistas do mesmo local são quase iguais. Um treino anterior do tipo de contentor dividiu ao acaso por imagem e deu 93,4 % na validação, **otimista**, porque imagens quase idênticas caíram nos dois lados.
2. **Compensar o desequilíbrio de classes uma só vez.** Amostragem equilibrada **e** pesos de classe ao mesmo tempo fizeram o classificador do tipo ignorar a classe mais frequente (16 % de exatidão, abaixo do acaso).
3. **Treinar sempre com imagens anonimizadas**, vindas do manifesto verificado, nunca das exportações originais.
4. **Um detetor por classe quando o rótulo não está completo.** No Open Images só se anota uma classe numa imagem se foi verificada para essa imagem; nas imagens com matrícula, 98 % não têm o rosto verificado (e vice-versa). Um modelo de 2 classes aprenderia que rostos ou matrículas não anotados são fundo, o pior erro num portão de privacidade. Cada conjunto usa **só** imagens onde a sua classe foi verificada.
5. **Cuidado com o viés de ancoragem** quando se anota sobre pré-anotações de um modelo.
6. **Papeleiras**: foram retiradas das anotações do detetor final (passam a fundo) e tratadas por um filtro à parte.

## Hardware
RTX 3060 de 6 GB. Para o detetor, `train_detector.py` documenta `batch 4 × acumulação 4` (pico de 3,1 GiB, recomendado); se faltar memória, `--batch 2 --accum 8`. Em máquinas com pouca memória, defina `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`.

## Exemplo: treinar o tipo de contentor
```bash
python -m ctrlf.scripts.preparar_lixo_porto_final --zip final_lixo_annotations.zip --recortes
python -m ctrlf.treino.train_fluxo4_porto cv    --porto-dir data/crops/fluxo4/porto_final     # exatidão honesta (5 dobras por panorama)
python -m ctrlf.treino.train_fluxo4_porto final --porto-dir data/crops/fluxo4/porto_final --epochs 19
```
O ficheiro guardado tem o mesmo formato do anterior (`{state, labels, meta}`): substitui `classificador_fluxo4.pt` sem mexer no código.

## O que NÃO está medido
- ⚠ A reprodutibilidade exata: não guardámos as sementes de todos os treinos, e os dados de treino não estão aqui.
