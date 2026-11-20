# 07 · Ajuste à estrada (etapa 8)

## Problema
A profundidade monocular põe os objetos mais longe do que estão, muitas vezes para lá do passeio ou dentro de edifícios. Mas o mobiliário urbano fica **junto da estrada**.

## Desenho e porquê (`ctrlf/pipeline/ajustar_estrada.py`)
Mantém o **raio da câmara** (o azimute) e corrige só a **distância** ao longo dele:
1. posição estimada E = câmara + distância × direção(azimute);
2. via OSM mais próxima de E e lado da via onde E está;
3. **corredor** = linha paralela à via, a uma largura `--w` dela (meia faixa mais passeio), do lado de E;
4. se E já está dentro do corredor, não mexe; senão o novo ponto é onde o raio cruza o corredor;
5. **só se puxa para a câmara**: se o cruzamento fica mais longe do que E, atrás da câmara, a menos de 2 m, o raio é quase paralelo à via, ou cai fora do troço da via, mantém-se E.
Os elementos **triangulados** mantêm a posição triangulada (não dependem da profundidade).

## Alternativas que rejeitámos
- **Pôr os objetos na via ou no ponto OSM mais próximo**: apagaria a informação medida; só se corrige a distância ao longo do raio e só em direção à câmara.

## Resultados medidos
Erro de posição dos contentores contra os ecopontos do OSM (`resultados/posicao_aveiro_contentores_catalogo_atual.md`, **315 contentores**, 50 ecopontos OSM, limite de emparelhamento 40 m):

| | n | mediana | p25 | p75 | p90 |
|---|---|---|---|---|---|
| **Todos os pares** | 33 | **11,2 m** | 8,3 m | 18,3 m | 27,0 m |
| Triangulados (várias vistas) | 12 | **7,3 m** | | | 13,8 m |
| Vista única com profundidade | 21 | **14,5 m** | | | 27,8 m |

Distância estimada / real: mediana **1,59** (1 = certo); erro de rumo absoluto mediano 21°; 282 elementos ficaram sem par.

Com o **catálogo anterior** (498 contentores, `..._catalogo_anterior.md`) a mediana tinha sido 7,3 m em 32 pares. Com amostras tão pequenas a diferença não é conclusiva: **o número a citar é o do catálogo atual**.

## Resultados esperados (hipóteses)
- O ajuste ajuda sobretudo nos objetos de vista única; nos triangulados não altera nada.

## O que NÃO está medido
- ⚠ O erro **absoluto** (só há o OSM como referência aproximada, um ponto por ilha).
- **A conclusão sólida é qualitativa**: ver o objeto de mais do que uma vista melhora a posição (7 m contra 14 m).
- Só 33 pares: a mediana tem muita incerteza.

## Falhas conhecidas
- Sem vias OSM da zona, a etapa não tem corredor onde apoiar-se (o resumo é tolerante, mas o ajuste fica sem efeito).
- Elementos cujo raio é quase paralelo à via ficam como estão.

## Como correr e testar
```bash
python -m ctrlf.pipeline.ajustar_estrada aveiro_piloto
python -m ctrlf.pipeline.ajustar_estrada aveiro_piloto --varrer      # compara larguras do corredor contra o OSM
python -m ctrlf.pipeline.avaliar_posicao aveiro_piloto
```
