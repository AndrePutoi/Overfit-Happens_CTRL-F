# 11 · Mapa (etapa 12, opcional)

## Problema
Ver o que foi detetado, sobre um mapa, para **inspecionar** o resultado.

## Desenho e porquê (`ctrlf/scripts/build_map.py`)
- Gera um ficheiro **HTML único e local** (Leaflet sobre OpenStreetMap) com as deteções do catálogo por família (contorno grosso = triangulado/confirmado), a referência OSM, as posições das câmaras e a caixa da zona.
- Ao clicar numa deteção mostra a(s) **imagem(ns) anonimizadas** com a caixa desenhada, a partir de `data/images_anon`. As imagens **não** vão embutidas no HTML: o `--serve` serve-as só a partir da pasta anonimizada e só as listadas no manifesto.
- É **opcional**: falhar não pára a cadeia. Serve a equipa, não faz parte do resultado.

## Alternativas que rejeitámos
- **Embutir as imagens no HTML**: tornaria o ficheiro enorme e arriscaria partilhar imagens sem controlo.

## Resultados medidos
Não há métrica: é uma ferramenta de inspeção. Foi testada em Aveiro.

## O que NÃO está medido / Falhas conhecidas
- Os mosaicos do OpenStreetMap só carregam se a página for servida por **http** (têm de levar `Referer`): abrir o ficheiro com duplo clique mostra os pontos mas o fundo fica bloqueado. Por isso o `--serve`.
- Precisa de rede para o Leaflet e os mosaicos quando se abre.

## Como correr
```bash
python -m ctrlf.scripts.build_map --city aveiro_piloto            # -> data/catalog/aveiro_piloto/mapa.html
python -m ctrlf.scripts.build_map --city aveiro_piloto --serve    # abre em http://localhost:8765/mapa.html
```
