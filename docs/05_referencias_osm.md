# 05 · Referências do OpenStreetMap (etapa 6)

## Problema
Obter, para a zona, as **vias** (para o ajuste à estrada, capítulo 07) e os **ecopontos, luz, papeleiras e sinais** já mapeados (como referência para medir o erro de posição).

## Desenho e porquê
- **Overpass API** (OpenStreetMap, ODbL). Só a **caixa da zona** e um nome de cliente genérico vão à rede.
- `ctrlf/ingest/osm_vias.py`: só **vias de circulação** (não passeios, ciclovias, escadas, caminhos, serviços), porque é aí que andam as câmaras e que ficam sinais e contentores. Guarda em cache (`data/reference/osm_<zona>_vias.json`).
- `ctrlf/ingest/osm_ref.py`: uma consulta por **mosaico de ~500 m** devolve os quatro temas (luz, reciclagem, papeleiras, sinais); cada mosaico fica em cache, por isso repetir só pede os que faltam.
- **Respostas parciais contam como falha**: o Overpass responde 200 com `remark: runtime error` quando estoira o tempo ou a memória e devolve resultados incompletos; isso não é guardado como completo.
- Contentores mapeados como caminho ou relação entram pelo centro (`out center`).

## Alternativas que rejeitámos
- A versão anterior (`osm_luz`, só luz) deixava células por obter e aceitava respostas incompletas.

## Resultados medidos
- Em Aveiro há **50 ecopontos** mapeados no OSM na zona piloto (`resultados/posicao_aveiro_*`). **Isto não prova que o OSM esteja incompleto**: o OSM guarda um ponto por ilha e nós contamos contentores (50 contra 315 não é uma comparação direta), e parte das nossas deteções pode ser falso positivo. Só emparelhámos 33 dos 50 pontos OSM, e não sabemos de que lado está a falha.

## Resultados esperados (hipóteses)
- A cobertura do OSM varia muito entre cidades; em zonas mal mapeadas, a referência é pobre.

## O que NÃO está medido
- ⚠ A completude do OSM em cada zona. **O OSM é uma referência, não uma verdade-terreno**: guarda um ponto por ilha (não por contentor), pode estar desatualizado e tem erro de alguns metros.

## Falhas conhecidas
- Falha de rede ou limite do Overpass: repetir; a cache evita refazer o que já foi obtido.
- A etapa `referencias` é externa (usa rede); as restantes etapas a jusante só dependem dos ficheiros em disco.

## Como correr e testar
```bash
python -m ctrlf.ingest.osm_vias aveiro_piloto            # --refresh para forçar
python -m ctrlf.ingest.osm_ref aveiro_piloto --status    # só mostra a cobertura, não consulta
```
