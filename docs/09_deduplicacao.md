# 09 · Deduplicação (etapa 10)

## Problema
O mesmo objeto aparece em várias vistas e panoramas (ângulos, escalas e posições diferentes). Queremos **um elemento por objeto** sem fundir objetos diferentes.

## Desenho e porquê (`ctrlf/scripts/deduplicar.py` e `ctrlf/pipeline/dedup_*.py`)
1. **Pares candidatos** de elementos: mesma família (nos sinais, mesma família de sinal e tipo igual ou desconhecido), a ≤ 20 m, câmaras e imagens diferentes.
2. **p(mesmo objeto)** por par: regressão logística (padronizada) sobre aparência (cosseno de DINOv2 e **inliers do EfficientLoFTR dentro do objeto**) e geometria (distância normalizada pela incerteza, rumo, profundidade média, número de vistas, lado mínimo, família).
3. **Restrições duras**: dois elementos que partilham uma imagem **nunca** se ligam; candeeiro e poste de luz só com p ≥ 0,9.
4. **Agrupamento por ligação média (UPGMA)** a dois níveis: **«provável»** (média ≥ 0,85) e **«possível»** (≥ 0,5). Os pares sem aresta contam como p = 0, o que impede o **encadeamento** (A–B e B–C ligados sem A–C dão média baixa).
5. **Posição recalculada** por grupo e, para todos, com a profundidade encolhida por um fator `k`.
- **Fusão automática só no nível «provável»** e só para sinais, contentores (como «ilha») e luz; **bancos nunca se fundem sozinhos**. Os grupos «possíveis» ficam como **sugestão para revisão humana**.
- `k` (escala da profundidade) mede-se nos elementos triangulados de cada zona; com menos de 20 observações triangulares usa-se um valor padrão (0,40 em Aveiro com câmaras do Mapillary a 100°).

## Alternativas que rejeitámos
- **Ligação simples ou DBSCAN sobre posições**: produziam grupos encadeados (chegaram a surgir grupos de 17 elementos).
- **Fundir tudo automaticamente**: só se funde sozinho onde a revisão humana mediu precisão suficiente (n ≥ 30 e limite inferior do intervalo de confiança a 95 % ≥ 0,85); o resto fica como sugestão.

## Resultados medidos
- **AUC 0,897** em pares novos (ronda 3, modelo congelado): é a estimativa honesta. Em validação cruzada agrupada a AUC foi 0,922, mas com o modelo treinado com **todos** os rótulos (`resultados/dedup_pontuacao_p.json`). Treino com **901 pares** (389 do mesmo objeto).
- **Ronda 4: revisão humana ao nível do elemento** (`resultados/dedup_avaliacao_ronda4.json`; **356 pares** de elementos do catálogo completo de Aveiro de então, todos respondidos, com controlos de atenção 100 % certos). Fração de pares que eram mesmo o mesmo objeto, por estrato:

  | Estrato | mesmo / n | fração | IC 95 % |
  |---|---|---|---|
  | **provável · sinais** | 79 / 80 | **98,8 %** | 93,3 a 99,8 % |
  | **provável · contentores (ilha)** | 34 / 35 | **97,1 %** | 85,5 a 99,5 % |
  | provável · luz e bancos | 24 / 24 | 100 % | 86,2 a 100 % |
  | possível · contentores | 36 / 40 | 90,0 % | 76,9 a 96,0 % |
  | possível · sinais | 50 / 60 | 83,3 % | 72,0 a 90,7 % |
  | quase · contentores | 17 / 25 | 68,0 % | 48,4 a 82,8 % |
  | quase · sinais | 16 / 40 | 40,0 % | 26,3 a 55,4 % |
  | baixo | 7 / 40 | 17,5 % | 8,7 a 32,0 % |

  **AUC do p ao nível do elemento: 0,898** (sinais 0,898; resíduos 0,828). A probabilidade está **calibrada**: com p entre 0,85 e 0,95 foram o mesmo objeto 98,4 % dos pares, e entre 0,10 e 0,30 só 17,5 %. **Critério da fusão automática**: n ≥ 30 e limite inferior ≥ 0,85 no nível «provável»: passam os **sinais** e os **contentores (ilha)**; a **luz** (e os bancos) só tinha 24 casos no total, por isso a fusão da luz é uma decisão da equipa com pouca evidência e os bancos nunca se fundem.
- **Estimativa de objetos únicos** no catálogo de então: **~2 542** (intervalo aproximado 2 500 a 2 663) para 4 120 elementos.
- No catálogo completo de Aveiro (4 120 elementos): 784 grupos «prováveis» (reduziriam 1 254 elementos) e 352 «possíveis».
- Nos contentores atuais (315 elementos): 3 grupos «prováveis» e 13 «possíveis», com `k` = 0,70 calibrado só com contentores.

## Resultados esperados (hipóteses)
- Em zonas com mais sobreposição entre vistas, a deduplicação tem mais evidência e funciona melhor.

## O que NÃO está medido
- A ronda 4 mediu **a precisão** (os pares recomendados que são mesmo o mesmo objeto); **não mediu os falsos negativos** (duplicados que não foram recomendados), e foi feita com **um par por grupo** e sobre o catálogo anterior de Aveiro.
- ⚠ A luz e os bancos têm muito poucos casos medidos (24 no total).
- ⚠ **Depois** da atualização dos contentores (315 elementos) a deduplicação **não foi revalidada** por revisão humana.
- ⚠ O comportamento noutras cidades.
- **Nota técnica:** a deduplicação dos contentores atuais correu sozinha e calibrou `k` = 0,70 só com contentores, enquanto no catálogo completo seria 0,40; os grupos de contentores podem por isso diferir dos que uma corrida completa daria.

## Falhas conhecidas
- Como a posição tem erro de ~10 m, há duplicados verdadeiros que não aparecem como par (e grupos que não são).
- O ruído numérico da GPU altera ligeiramente p (da ordem de 0,01) entre corridas; os agrupamentos mantiveram-se.

## Como correr e testar
```bash
python -m ctrlf.scripts.deduplicar --cidade aveiro_piloto            # [--tau-alto 0.85] [--tau-baixo 0.5]
python tests/unit/20_test_dedup_cluster.py
```
