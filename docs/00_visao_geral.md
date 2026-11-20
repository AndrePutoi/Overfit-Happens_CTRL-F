# 00 · Visão geral

## Problema
Dado um conjunto de imagens de rua, produzir um **inventário georreferenciado** de mobiliário urbano (sinais, contentores de resíduos, iluminação, bancos): um ponto por objeto, com a sua classe e a incerteza da posição, e **sem expor pessoas**.

## A pipeline em 12 etapas
```
descarregar → vistas → admissao → privacidade → deteccao → referencias → catalogo → estrada → tipos → dedup → entrega → (mapa)
```
| # | Etapa | Entra | Sai |
|---|---|---|---|
| 1 | descarregar | caixa geográfica | `data/raw/<zona>/` + `meta.jsonl` |
| 2 | vistas | panoramas 360° | `data/raw/<zona>_vistas/` (vistas planas) |
| 3 | admissao | vistas | só as aprovadas (as rejeitadas vão para `_rejeitadas/`) |
| 4 | privacidade | vistas admitidas | `data/images_anon/` + `manifest.jsonl` (sha256) |
| 5 | deteccao | imagens anonimizadas | `data/zonas/<zona>/deteccoes/bloco_NNNN.jsonl` + COCO por família |
| 6 | referencias | caixa da zona | `data/reference/osm_<zona>_*` |
| 7 | catalogo | deteções + posição da câmara | `data/catalog/<zona>/catalog.geojson`, `observacoes.json` |
| 8 | estrada | catálogo + vias OSM | `catalog_ajustado.geojson` |
| 9 | tipos | recortes de contentores | `residuos_tipos.json` |
| 10 | dedup | catálogo ajustado | `dedup_v2/` (grupos, posições, pares) |
| 11 | entrega | tudo o anterior | `Entrega_C/entrega_<zona>_*.zip` e **`resultado/elementos_unicos.geojson`** |
| 12 | mapa | catálogo | `mapa.html` (opcional) |

## Princípios de desenho
1. **Privacidade primeiro, com falha fechada.** Nenhum modelo de deteção vê uma imagem que não esteja no manifesto de anonimização com o sha256 certo. Não há parâmetro para saltar este passo (ver capítulo 03).
2. **Um modelo de cada vez.** A GPU tem 6 GB. Carrega-se um modelo, processa-se um bloco de imagens, liberta-se a memória e passa-se ao seguinte. Picos de memória do PyTorch medidos por módulo (`resultados/vram_modulos.json`): privacidade 1,79 GB; contentores 0,17 GB; sinais 0,23 GB; bancos 0,19 GB; classificador de sinais 0,53 GB; CLIP 0,70 GB; profundidade 0,25 GB; DINOv2 0,26 GB; Grounding DINO 1,85 GB (só na demonstração).
3. **Retomável.** O estado de cada etapa fica em disco; uma corrida interrompida continua de onde parou (capítulo 12).
4. **Ids estáveis.** Quem consome o resultado pode guardar decisões associadas a ids; por isso não se renumera: o que desaparece deixa um buraco e fica registado.
5. **Honestidade sobre o que se sabe.** Cada capítulo separa o medido do não medido.

## O que é e o que não é
É um **protótipo funcional validado num piloto**, que produz um inventário **para rever por humanos**. **Não** é um sistema para decisões automáticas sem verificação.

## Resultados globais
Não há um número único de «exatidão da pipeline»: misturaria módulos com métricas diferentes. A exatidão está **por módulo**, nos capítulos seguintes, com indicação de onde foi medida.

## Escala do piloto (Aveiro)
17 170 vistas planas; catálogo de 4 120 elementos (3 352 sinais, 498 contentores, 130 de iluminação, 140 bancos), antes da última atualização dos contentores e da exclusão de categorias de sinais sem interesse.
