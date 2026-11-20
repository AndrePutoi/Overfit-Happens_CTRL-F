# 04 · Deteção (etapa 5)

## Problema
Em cada imagem anonimizada, encontrar **sinais, contentores de resíduos, iluminação e bancos**, classificar o que for preciso e guardar tudo num formato único.

## Desenho e porquê
- **Um detetor por família**, todos RF-DETR Small (Apache-2.0), carregados **um de cada vez** e libertados antes do seguinte, em blocos de imagens (`--bloco`, 150 por omissão) para limitar a memória. Orquestração em `ctrlf/scripts/detetar_zona.py`; registo de modelos em `ctrlf/urban_mobile_search/`.
- **Saída num formato único**: `data/zonas/<zona>/deteccoes/bloco_NNNN.jsonl` (uma linha por imagem; retoma por bloco), `modelos.json` (versão e pesos de cada modelo usado, para rastreio) e um COCO por família em `data/preannot/{sinais,ecopontos,luz,bancos}/<zona>/annotations/instances_default.json`, que o catálogo lê.
- **Limiares de confiança**: sinais 0,3; contentores 0,3; luz 0,3; bancos 0,5 (`Settings`; ajustáveis por variável de ambiente, por exemplo `UMS_CONF_SINAL`). O de 0,6 para sinais foi tentado e revertido por decisão da equipa; `tests/unit/22_test_limiar_sinais.py` falha se alguém mudar estes valores sem decidir de novo.

### As quatro famílias
| Família | Modelo | Dados | Notas |
|---|---|---|---|
| **Contentores** (`contentor`, `subterraneo`) | RF-DETR Small, 512 px, 2 classes | anotações do **Porto** feitas à mão, sem papeleiras | o tipo (papel, vidro…) é um classificador à parte (capítulo 08) |
| **Sinais** | RF-DETR Small, 768 px, 5 famílias do MTSD, mais um **classificador hierárquico** (router + especialistas, DINOv2-small) | **MTSD** (Mapillary Traffic Sign Dataset: 8 000 imagens de treino e 1 500 de validação na preparação) | categorias sem interesse em Aveiro são ignoradas (ver abaixo) |
| **Luz** (`candeeiro`, `poste_luz`) | RF-DETR Small, 768 px | anotações de Lisboa e do Porto | |
| **Bancos** | RF-DETR Small **pré-treinado no COCO**, só a classe `bench` (id 15) | **nenhum treino nosso** | limiar 0,5 |

- **Sinais ignorados** (`configs/sinais_ignorados.json`): o grupo «orientação e outros» e os tipos `complementary_tow_away_zone` (painel de reboque), `complementary_chevron_*` (baliza de curva) e `complementary_trucks*` (painel de veículos pesados), porque em Aveiro «quase só apanham lixo». Ficam por decidir a baliza de obstáculo e os sinais de tipo desconhecido nos restantes grupos. A lista é lida tanto pela deteção como pela entrega.
- **Filtro de papeleiras** (CLIP ViT-B/32 sem treino, `ctrlf/detection/postfilter/papeleiras.py`): compara o recorte de cada contentor com frases de «ecoponto» e de «papeleira» (caixote pequeno preso a um poste) e devolve probabilidades. É uma **heurística validada à vista num conjunto pequeno**, não uma medição.

## Alternativas que rejeitámos
- **Grounding DINO como detetor**: sem treino, na validação do Porto teve precisão de 8 % a 18 % nos contentores (capítulo 14). Serve para pré-anotar, não para detetar.
- **Uma 3.ª classe «papeleira» no detetor de contentores** (versões v3 e v2): mAP50-95 de 0,39 e 0,41; o modelo final de **2 classes, treinado sem papeleiras**, deu **0,43**, e as papeleiras tratam-se com o filtro CLIP.
- **Treinar os bancos**: usámos o pré-treino do COCO; não houve treino nem medição própria.

## Resultados medidos
**Contentores** (`resultados/comparacao_detetor_lixo_final.json`; validação do Porto: 226 imagens, 152 caixas):

| Versão | mAP50-95 | mAP50 | por classe (contentor / subterrâneo) |
|---|---|---|---|
| v1 (2 classes, 1.ª versão) | 0,367 | 0,566 | 0,218 / 0,515 |
| v3 (3 classes) | 0,388 | 0,616 | 0,244 / 0,532 |
| v2 (3 classes, correções do Porto) | 0,415 | 0,639 | 0,267 / 0,563 |
| **FINAL (2 classes, Porto, sem papeleira)** | **0,432** | **0,685** | **0,315 / 0,550** |

A IoU 0,5, o detetor antigo teve precisão 0,66 e revocação 0,70, e o final **precisão 0,81 e revocação 0,69** (mesmas 226 imagens).

**Luz** (`resultados/comparacao_detetores_luz.json`): a versão treinada só em Lisboa teve mAP50-95 **0,39** na validação de Lisboa (76 caixas) e **0,70** em imagens do Porto (468 caixas).

**Sinais** (`resultados/mtsd_hier_eval.json`): o router acerta **94,3 %** (n = 7 442, conjunto MTSD) e o grupo «orientação e outros» tem recolha de 82,7 %.

## Resultados esperados (hipóteses)
- Em cidades novas, o desempenho dos detetores de contentores e de luz tende a descer (foram treinados em Porto e Lisboa).
- O contentor à superfície é mais difícil do que o subterrâneo (0,32 contra 0,55).

## O que NÃO está medido
- ⚠ **A exatidão de qualquer detetor em Aveiro** (não há verdade-terreno lá).
- ⚠ **Os bancos** (nem em Aveiro nem noutro sítio).
- ⚠ A exatidão dos sinais fora do MTSD.
- **Validação do detetor final de contentores:** as 226 imagens de validação (152 caixas) estão **separadas do treino** (792 imagens; divisão por panorama, com as quatro vistas do mesmo local do mesmo lado), mas o conjunto é pequeno, foi usado para escolher o melhor ponto do treino, e o `test` é uma **cópia** da validação: **não há um teste independente**, por isso o 0,43 pode estar ligeiramente otimista.

## Falhas conhecidas
- Se um modelo faltar, a etapa falha com o nome do ficheiro em falta (`python -m ctrlf weights` mostra onde pôr cada um).
- Em Aveiro, depois de trocar o detetor de contentores, **quase metade das deteções antigas deixou de existir** (2 235 de 4 675): o novo é mais exigente; não sabemos quantas eram falsos positivos.

## Como correr e testar
```bash
python -m ctrlf.scripts.detetar_zona aveiro_piloto                  # todas as famílias
python -m ctrlf.scripts.detetar_zona aveiro_piloto --familias residuos --bloco 200
python -m ctrlf weights                                             # onde estão os pesos
python tests/unit/15_test_urban_mobile_search.py                    # com detetores FALSOS, sem GPU
```
