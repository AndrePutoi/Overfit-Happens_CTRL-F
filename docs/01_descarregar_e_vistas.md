# 01 · Descarregar e vistas planas (etapas 1 e 2)

## Problema
Obter imagens de rua de uma zona, com a posição e o rumo de cada uma, e prepará-las para os detetores.

## Desenho e porquê
- **Fonte: Mapillary API v4** (imagens CC BY-SA 4.0, com posição e rumo). Código: `ctrlf/ingest/mapillary_download.py`.
- **A API só aceita caixas com menos de 0,01° de lado.** O descarregador parte a caixa em células de ≤ 0,009° e subdivide uma célula se esta devolver 2 000 resultados (o limite da API).
- Opções úteis: `--since` (só imagens recentes), `--stride N` (1 em cada N, ordenadas por sequência e hora, para zonas muito redundantes), `--max-panoramas`, `--count-only` (só conta).
- **Panoramas 360° → 4 vistas planas** (yaws 0°, 90°, 180°, 270°; campo de visão 100°), em `ctrlf/ingest/pano_to_perspective.py`. Cada vista tem o seu rumo (rumo do panorama + yaw). As vistas planas já existentes passam inalteradas.
- O token do Mapillary lê-se de `MAPILLARY_TOKEN` (ambiente ou `.env`); **nunca** vai para o código nem para o git.

## Alternativas que rejeitámos
- **Detetar diretamente no panorama equirretangular**: as formas ficam distorcidas e os detetores funcionam mal. As vistas planas resolvem isso.
- **Street View**: não usado (licença e custo).

## Resultados medidos
- Aveiro (zona piloto): **17 170 vistas planas** obtidas a partir dos panoramas.
- A conversão tem autoteste: `tests/unit/11_test_pano_to_perspective.py`; o descarregador, `tests/unit/10_test_mapillary_offline.py` (sem rede).

## Resultados esperados (hipóteses)
- Em zonas com pouca cobertura do Mapillary, haverá poucas imagens e muitos objetos vistos só de uma vista (o que degrada a posição, capítulo 06).

## O que NÃO está medido
- A cobertura e a data das imagens do Mapillary por zona.
- A **convenção de rumo do centro do panorama** está implementada como o centro apontar para o `compass_angle`, mas o próprio código marca-a como *a confirmar em imagens reais*; o autoteste só verifica o que está explicitamente verificado.

## Falhas conhecidas
- Sem token, ou com caixa sem cobertura, a etapa falha com «nenhuma imagem descarregada».
- Nesta fase as imagens **ainda não foram anonimizadas**: ficam em `data/raw/` (temporário) e não podem ser partilhadas.

## Como correr e testar
```bash
python -m ctrlf.ingest.mapillary_download --bbox -8.6550 40.6405 -8.6455 40.6461 --since 2023-01-01 --count-only
python -m ctrlf.ingest.pano_to_perspective data/raw/aveiro_piloto data/raw/aveiro_piloto_vistas --yaws 0 90 180 270 --fov 100
python tests/unit/10_test_mapillary_offline.py && python tests/unit/11_test_pano_to_perspective.py
```
