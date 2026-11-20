# 10 · Resultado e entrega (etapa 11)

## Problema
Produzir um resultado **legível por outros programas**, validável e com identificadores estáveis.

## O resultado final de uma zona
**`data/zonas/<zona>/resultado/elementos_unicos.geojson`**: um ponto por objeto (WGS84, `[lon, lat]`), com as várias vistas já fundidas. É extraído pelo `ctrlf.scripts.extrair_resultado` do pacote de entrega mais recente, depois de validar que o JSON é **estrito** (sem `NaN`) e que todas as posições são finitas.

O resto do pacote (`Entrega_C/entrega_<zona>_<data>.zip`) é material de apoio para **auditar** um elemento e é **o que a interface importa** (capítulo 16).

## O pacote de entrega (esquema 1.3)
| Ficheiro | Conteúdo |
|---|---|
| `elementos_unicos.geojson` | **o inventário único**: igual a `elementos.geojson` mas com as fusões automáticas já aplicadas |
| `elementos.geojson` | todos os elementos candidatos (os absorvidos mantêm-se, com `merged_into`) |
| `deteccoes.json` | **todas** as caixas previstas, ligadas ao elemento quando entraram no catálogo |
| `imagens.json` | as imagens referenciadas: posição da câmara, rumo, campo de visão, licença e atribuição |
| `ilhas.json` | ilhas de reciclagem, com o tipo dos caixotes e as imagens |
| `duplicados.json` | grupos e pares de elementos que podem ser o mesmo objeto, com `p` e `confidence` |
| `schema/*.schema.json` | **esquemas JSON** de cada ficheiro (o pacote é validado contra eles) |
| `manifest.json` | contagens e sha256 de cada ficheiro |
| `LEIA-ME.md`, `ATRIBUICOES.md` | descrição e atribuições (Mapillary, OSM) |

## Campos de um elemento único
| Campo | Significado |
|---|---|
| `id` | identificador estável: `sin-` (sinal), `res-` (contentor), `ilu-` (luz), `mob-` (banco) + zona + número |
| `family` | `sinal`, `residuos`, `iluminacao` ou `mobiliario` |
| `class`, `subclass` | classe do detetor e subclasse (por exemplo, o **tipo do contentor** sugerido) |
| `subclass_source`, `subclass_p` | origem da subclasse (`modelo`) e probabilidade do tipo |
| `confidence`, `n_views` | confiança do elemento (nas fusões, `1 − ∏(1 − cᵢ)`) e número de vistas que o apoiam |
| `status` | `auto`, `validado`, `corrigido` ou `rejeitado`; a pipeline só produz `auto` |
| `geo_method`, `geo_residual` | `triangulado` ou `vista_unica_profundidade`; resíduo da triangulação (m), quando existe |
| `position_reliable` | **`true` só nos triangulados** (≥ 2 câmaras); os de vista única têm erro típico de ~15 m |
| `position_method`, `position_sigma_m` | `triangulada_catalogo` ou `vista_unica_k`; **incerteza da posição em metros** (nos de vista única) |
| `position_original`, `position_previous` | a posição original (sem ajuste à estrada) e a anterior |
| `road_adjustment_m`, `road_adjustment_method` | quanto e como o ajuste à estrada moveu o ponto |
| `n_units`, `ilha_id` | número de unidades (nos contentores) e a ilha a que pertence |
| `osm_ref_match` | se coincide com um ecoponto do OSM |
| `observations`, `best_detection_id` | as deteções de origem, ordenadas por qualidade, e a melhor |
| `duplicate_group_id`, `duplicate_level`, `duplicate_possible_group_id` | grupo de duplicados e o seu nível (`provavel`, `possivel`) |
| `auto_merged`, `merged_from`, `merged_into` | fusões automáticas: quais elementos foram fundidos (para **desfazer**) |
| `clip_suspect`, `clip` | verificação por CLIP de que o objeto é o que o detetor diz (`true` = suspeito) |

Os esquemas completos estão dentro do pacote, em `schema/`.

## Desenho e porquê
- **Ids que não se renumeram**: quem consome os dados pode ter decisões associadas a um id. Em atualizações, o que desaparece deixa um buraco e fica registado; os ids novos continuam a seguir ao último.
- **Fusão automática só onde foi medida** (capítulo 09): nos grupos «provável» de sinais e contentores (como ilha) e, por decisão da equipa, na luz. **Bancos nunca.** Cada fusão guarda `merged_from` para se poder desfazer.
- **`position_sigma_m` e `position_reliable`** permitem a quem usa o resultado **mostrar a incerteza** em vez de fingir precisão.
- **JSON estrito**: o pacote falha se houver `NaN` ou coordenadas infinitas (já aconteceu uma vez e produzia todas as posições `[NaN, NaN]`).

## Alternativas que rejeitámos
- **Entregar só os pontos**: perderia a possibilidade de auditar de onde vem cada ponto (observações, imagens, grupos).
- **Fundir tudo automaticamente**: ver capítulo 09.

## Resultados medidos
- Aveiro (entrega atual, depois da atualização dos contentores e da exclusão de categorias de sinais): **2 822 elementos, 1 938 únicos**, 13 930 deteções, 7 032 imagens.
- A confiança das fusões foi medida na ronda 4 (capítulo 09).

## O que NÃO está medido
- ⚠ A exatidão do conteúdo (classes, tipos) em zonas novas: o pacote garante o **formato**, não a verdade.

## Falhas conhecidas
- O erro de posição dos objetos de vista única é de ~15 m: quem usa o resultado deve respeitar `position_sigma_m`.
- Se faltar um ficheiro ou o JSON não for estrito, a etapa `entrega` falha com a mensagem do que falta.

## Como correr e testar
```bash
python -m ctrlf.scripts.exportar_entrega aveiro_piloto                # -> Entrega_C/entrega_aveiro_piloto_<data>.zip
python -m ctrlf.scripts.extrair_resultado aveiro_piloto               # -> data/zonas/aveiro_piloto/resultado/elementos_unicos.geojson
python -m ctrlf.scripts.exportar_entrega aveiro_piloto --sem-imagens  # sem copiar as imagens (só os recortes)
```
