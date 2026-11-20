# Contrato de dados — CTRL+F (versão 2)

O formato de troca é o da **entrega do pipeline** (esquema 1.3, `python -m ctrlf.scripts.exportar_entrega`): `elementos.geojson`, `deteccoes.json`, `imagens.json`, `duplicados.json` e `decisoes`. A API devolve as mesmas formas, com campos extra para a interface. Mudanças ao esquema da base de dados combinam-se com a C.

## 1. Pipeline → base de dados

O pipeline entrega a pasta; a interface importa-a:

```
docker compose exec api python -m app.importar          # lê dados/entrega
```

O importador:
- valida os ficheiros contra `schema/*.schema.json`;
- **substitui** elementos, deteções, imagens e duplicados pelo conteúdo da entrega;
- **volta a aplicar** as decisões do técnico (tabela `edit_log`) aos elementos com o mesmo `id`.

**Pedido ao pipeline: manter os `id` estáveis entre entregas** (o mesmo objeto deve continuar a chamar-se `sin-aveiro-00001`). Se os ids mudarem, as decisões antigas são aplicadas ao objeto errado ou ignoradas. Alternativa: o pipeline lê `GET /decisions` e aplica-as antes de exportar.

### Como os campos entram na base

| Entrega | Base de dados | Notas |
| --- | --- | --- |
| `properties.id` | `element.ext_id` | O `id` público em toda a API |
| `class` | `element.class` | `sinal`, `poste_luz`, `candeeiro`, `contentor`, `subterraneo` |
| `subclass` | `element.subclass` | Tipo MTSD. `shared/taxonomia.json` dá o nome em português, o grupo e o código |
| — | `element.sign_group`, `code`, `name` | Calculados pela taxonomia. Sinais `desconhecido` usam o grupo da melhor deteção |
| `class = subterraneo` | `install_type = subterraneo` | |
| `class = contentor` | `install_type = NULL` | "Por classificar" até o pipeline separar ilha / indiferenciado |
| `geometry` / `position_original` | `geom` / `position_original` | |
| `geo_method`, `geo_residual`, `position_reliable`, `road_adjustment_*`, `n_units`, `osm_ref_match` | colunas com o mesmo nome | |
| `observations[].rank` | `detection.rank` | |
| `best_detection_id` | `element.best_detection_id` | O técnico pode escolher outra |
| `duplicate_group_id` | `element.duplicate_group_id` | Grupos e pares em `duplicate_group` e `duplicate_pair` |
| `deteccoes.json` (todas) | `detection` | Também as fora do catálogo (`in_catalog = false`) |
| `imagens.json` | `image` | `blurred = true`, `blur_audited = false` até haver auditoria |
| `path`, `crop_path` | `image_path`, `crop_path` | Relativos a `dados/`; servidos em `/media/...` |

### Quando o pipeline separar as ilhas de reciclagem

Sugestão de formato (o importador já lê estes campos):

```json
{ "class": "contentor", "install_type": "ilha", "color": "azul", "n_units": 3 }
```

`install_type`: `ilha` ou `indiferenciado`. `color`: `verde`, `azul`, `amarelo`, `vermelho`, `cinzento`, `castanho`. Se preferirem outros nomes, ajustem o importador e a taxonomia.

### Tipos de sinal novos

Se aparecer um `subclass` que não está em `shared/taxonomia.json`, o importador avisa. O elemento entra na mesma (nome = o próprio tipo, grupo pelo prefixo). Acrescentar o tipo ao ficheiro.

## 2. API → interface

Documentação interativa: http://localhost:8000/docs

| Rota | Para quê |
| --- | --- |
| `GET /elements` | GeoJSON no formato de `elementos.geojson` + campos da interface. Filtros: `family`, `class`, `subclass`, `sign_group`, `install_type` (inclui `por_classificar`), `color`, `status`, `min_conf`, `reliable`, `duplicates`, `q`, `bbox` |
| `GET /elements/{id}` | O elemento + `observations_detail` (cada imagem com caixa, câmara e atribuição), `duplicates`, `history` |
| `GET /detections?element_id=&image_id=&in_catalog=&excluded_reason=` | Formato de `deteccoes.json` + `crop_url` |
| `GET /images/{id}` | Formato de `imagens.json` + `url` e as deteções da imagem |
| `GET /duplicates` | Grupos por resolver, com o estado de cada membro |
| `GET /review-queue` | Por rever, da menor para a maior confiança |
| `GET /stats`, `/config`, `/taxonomy`, `/imports`, `/me` | Painel, licenças, classes, importações, perfil |
| `GET /export.geojson`, `/export.csv` | Exportação com os mesmos filtros |
| `/media/entrega/imagens/<id>.jpg`, `/media/entrega/recortes/<id>.jpg` | Imagens e recortes |

Campos extra em cada elemento (além dos da entrega): `name`, `code`, `sign_group`, `sign_group_label`, `class_label`, `install_type`, `install_label`, `color`, `lat`, `lon`, `uncertainty_m` (15 m nos de vista única; resíduo da triangulação, mínimo 3 m, nos triangulados), `confidence_pct`, `review_state` (`por_rever` / `verificado`), `best` (imagem, recorte, caixa, tamanho da imagem), `source` (licença e atribuição), `merged_into`, `split_from`, `updated_by`, `updated_at`.

## 3. Técnico → pipeline (decisões)

Ações (todas com o cabeçalho `X-Tecnico-Token`):

| Ação | Rota | Decisão gravada |
| --- | --- | --- |
| Validar | `POST /elements/{id}/validate` | `status: validado` |
| Rejeitar / repor | `POST /elements/{id}/reject`, `/restore` | `status: rejeitado` / `status_reset: true` |
| Corrigir tipo, cor, posição | `PATCH /elements/{id}` com `class`, `subclass`, `install_type`, `color`, `lat`, `lon` | `status: corrigido` + campos alterados |
| Escolher a melhor imagem | `PUT /elements/{id}/best-detection` | `best_detection_id` |
| Juntar duplicado | `POST /elements/{id}/merge` `{"into": ...}` | `merge_into` |
| Separar deteções | `POST /elements/{id}/split` `{"detection_ids": [...]}` | `split_detection_ids` (+ `new_element_id`) |

`GET /decisions` devolve tudo no formato de `decisoes.exemplo.json` (com `?since=` para só as recentes). `POST /decisions` aplica uma lista nesse formato, tudo ou nada.

Ao juntar ou separar, a API recalcula `n_views`, a ordem das observações e a confiança (`1 − ∏(1 − s)` sobre a melhor pontuação de cada imagem, sem o fator geométrico do pipeline).
