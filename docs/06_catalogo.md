# 06 · Catálogo: profundidade, posição e associação por raios (etapa 7)

## Problema
Transformar caixas em imagens num **ponto no mapa** por objeto, juntando as observações do mesmo objeto vistas de câmaras diferentes.

## Desenho e porquê
- **Posição de uma vista**: azimute = rumo da câmara + ângulo da coluna do centro da caixa; distância = **profundidade monocular** (Depth Anything V2 Metric Outdoor Small, `ctrlf/geometry/depth.py`, mediana da zona central da caixa para evitar o fundo). Tudo em metros no sistema ETRS89 / PT-TM06 (EPSG:3763); entra e sai WGS84.
- **Triangulação**: com 2 ou mais posições de câmara, as semirretas cruzam-se e a posição vem de mínimos quadrados; não depende da profundidade, por isso vale mais do que uma vista única.
- **Associação por raios** (`ctrlf/pipeline/assoc_rays.py`): usa o que é fiável (o **azimute** de cada observação) e trata a distância só como verificação grosseira. Algoritmo: (1) para cada par de observações de câmaras diferentes calcula onde os raios se cruzam e aceita o par se o cruzamento fica à frente das duas câmaras, dentro de um alcance máximo, com ângulo mínimo e com distâncias coerentes com a profundidade; (2) os cruzamentos válidos agrupam-se (DBSCAN) em objetos candidatos; (3) cada observação junta-se ao candidato mais próximo do seu raio e os candidatos reajustam-se por mínimos quadrados; os que ficam com menos de 2 câmaras desfazem-se; (4) as vistas únicas agrupam-se por posição e juntam-se a um candidato confirmado se o seu raio passar perto.
- **Filtro de papeleiras** (capítulo 04) e o **agrupamento por aparência** das vistas únicas (`--catchall appearance`, a partir de embeddings dos recortes) completam o catálogo.
- Cada elemento guarda a **incerteza da posição** (`position_sigma_m`).

## Alternativas que rejeitámos
- **Agrupar as posições de vista única com DBSCAN**: o erro de vários metros fazia juntar objetos diferentes ou deixar o mesmo repetido. Daí os raios.
- **Distância fixa por omissão**: sem profundidade o erro de uma vista é de vários metros.
- O plano inicial previa o **Depth Anything 3**; usámos o **V2 Small** por já estar disponível e caber na GPU.

## Resultados medidos
- A profundidade monocular **sobrestima a distância**: nos contentores de Aveiro a distância estimada é, na mediana, **×1,6 a real** com o catálogo atual (e ×1,35 com o anterior).
- Erro de posição contra o OSM no catálogo atual (315 contentores; 33 pares 1-para-1): ver o capítulo 07.
- `configs/sigma_posicao.json` guarda o modelo de incerteza medido nos elementos triangulados de Aveiro (5 525 observações, 878 elementos): σ do azimute de 23° e um viés e σ da distância por intervalo (por exemplo, de 0 a 8 m o viés mediano é −4,4 m e o σ robusto 1,8 m).

## Resultados esperados (hipóteses)
- Os objetos vistos de **várias vistas** ficam bem melhor posicionados do que os de vista única.

## O que NÃO está medido
- ⚠ O erro de posição **com GPS no terreno**: as medições são contra o OSM, que é aproximado. O próprio código nota que `k` não foi validado com GPS.
- ⚠ O desempenho do catálogo noutras cidades.

## Falhas conhecidas
- **Objetos de vista única**: erro maior e muito dependente da profundidade.
- A mesma ilha de reciclagem pode ser partida em vários elementos (tratado na deduplicação, capítulo 09).

## Como correr e testar
```bash
python -m ctrlf zona plan aveiro_piloto                        # mostra o comando completo da etapa `catalogo`
python tests/unit/13_test_avaliar_posicao.py
python -m ctrlf.pipeline.avaliar_posicao aveiro_piloto         # erro de posição contra o OSM
```
