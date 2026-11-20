# Documentação por bloco

Cada capítulo explica **como o bloco foi pensado e desenhado, porquê, que resultados dá e o que não está medido**, sempre pela mesma ordem:

1. **Problema**: o que entra e o que sai.
2. **Desenho e porquê**.
3. **Alternativas que rejeitámos** (e a razão).
4. **Resultados medidos**: valor, tamanho da amostra, em que dados. A origem está em [`resultados/`](resultados/).
5. **Resultados esperados**: hipóteses, claramente marcadas como tal.
6. **O que NÃO está medido.**
7. **Falhas conhecidas** e como o sistema reage.
8. **Como correr e testar** o bloco isolado.

**Regra de ouro deste repositório:** um número só aparece com a sua origem; o que não foi medido diz-se. Os valores marcados **⚠** não estão medidos em zonas novas (incluindo Aveiro).

| Capítulo | Bloco |
|---|---|
| [00 Visão geral](00_visao_geral.md) | a pipeline de ponta a ponta, princípios, hardware |
| [01 Descarregar e vistas](01_descarregar_e_vistas.md) | etapas 1 e 2 |
| [02 Admissão](02_admissao.md) | etapa 3 |
| [03 Privacidade](03_privacidade.md) | etapa 4 (o portão) |
| [04 Deteção](04_detecao.md) | etapa 5 (sinais, contentores, luz, bancos) |
| [05 Referências OSM](05_referencias_osm.md) | etapa 6 |
| [06 Catálogo](06_catalogo.md) | etapa 7 (profundidade, posição, associação por raios) |
| [07 Estrada](07_estrada.md) | etapa 8 |
| [08 Tipos](08_tipos.md) | etapa 9 (tipo do contentor) |
| [09 Deduplicação](09_deduplicacao.md) | etapa 10 |
| [10 Resultado e entrega](10_resultado_e_entrega.md) | etapa 11 (formato de saída) |
| [11 Mapa](11_mapa.md) | etapa 12 (opcional) |
| [12 Orquestração](12_orquestracao.md) | como as etapas se encadeiam, retomam e falham |
| [13 Treino](13_treino.md) | como se treinaram os modelos |
| [14 Grounding DINO](14_grounding_dino.md) | a demonstração de pré-anotação |
| [15 Licenças e riscos](15_licencas_e_riscos.md) | termos de dados e pesos, riscos |
| [16 Interface](16_interface.md) | base de dados, API e frontend que consomem a entrega |
