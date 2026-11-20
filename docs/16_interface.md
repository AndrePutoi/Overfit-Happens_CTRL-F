# 16 · Interface (base de dados, API, frontend e worker)

> Código em [`../interface/`](../interface/). Esta pasta é **autónoma** (tem o seu `docker-compose.yml` e o seu `README.md`), e liga-se à pipeline por **ficheiros**: a interface importa o pacote de entrega (capítulo 10) e, opcionalmente, um *worker* corre a pipeline para os pedidos de imagens.

## Problema
Pôr o inventário da pipeline nas mãos de duas pessoas diferentes: o **técnico da câmara**, que valida, corrige, junta e exporta, e o **público**, que vê só o que está verificado e pode reportar problemas.

## Desenho e porquê
```
pipeline → entrega (zip) → interface/dados/entrega → Importador → PostgreSQL + PostGIS + pgvector → API FastAPI → Frontend React + Leaflet
                                  ▲                                                    ▲                              │
              worker (pedidos "Importar imagens") ── corre `python -m ctrlf zona run`         └─ decisões do técnico (edit_log) ◄┘ GET /decisions → pipeline
```
| Camada | Tecnologia |
|---|---|
| Base de dados | PostgreSQL 16 com PostGIS e pgvector (embeddings DINOv2-S das deteções) |
| API | Python, FastAPI, psycopg 3; testes com pytest |
| Frontend | React 18, Vite, Leaflet; servido por nginx |
| Worker | Python (só biblioteca padrão); corre ao lado da pipeline e fala com a API |
| Arranque | Docker Compose (`db`, `api`, `web`) |

**Pastas:** `interface/db/init/` (esquema e configuração SQL), `api/app/` (`main.py`, `importar.py`, `acoes.py`, `reclamacoes.py`, `taxonomia.py`, `db.py`), `web/src/` (`App.jsx`, `api.js`, `tax.js`, `components/`), `shared/taxonomia.json` (classes, tipos de sinal, grupos, cores), `worker/`, `docs/` (contrato de dados e operação), `dados/` (entrega e pedidos; fora do git).

### Ligação com a pipeline
- A interface importa **o pacote de entrega** (capítulo 10): obrigatórios `elementos.geojson`, `deteccoes.json`, `imagens.json`, `duplicados.json`; opcionais `elementos_unicos.geojson` (usado em vez dos elementos se existir), `ilhas.json`, `manifest.json`. Valida contra `schema/*.schema.json`.
- **Os ids têm de ser estáveis entre entregas.** O importador apaga e recria os elementos de cada entrega, mas **nunca apaga o `edit_log`**; depois volta a aplicar cada decisão ao elemento com o mesmo `id`. Se um id desaparece, a decisão fica ignorada (conta em `decisions_skipped`); se um id se mantém mas o objeto mudou, a decisão passa a valer para **outro objeto**. Se a pipeline renumerar os elementos, importe com `--sem-decisoes` e limpe as decisões.
- **Modos do importador:** por omissão **substitui** os dados da pipeline; `--juntar` **soma** ao catálogo (os ids repetidos recebem o prefixo `<pasta>:`; é o que o worker usa); `--sem-decisoes` não reaplica decisões.
- **Resíduos:** `partially_underground` = subterrâneo; senão, conjunto colorido = ilha de reciclagem; senão, indiferenciado. O **tipo sugerido pelo modelo** é só uma sugestão: o técnico confirma ou corrige. **Taxonomia:** se aparecer um tipo novo, o elemento entra na mesma e fica um aviso para o acrescentar.

### Base de dados
- **Configuração** (`municipality`, `source`, `technician`), **entrega do pipeline** (`image`, `detection`, `element`, `duplicate_group`, `duplicate_pair`), **técnico** (`edit_log`), **cidadão** (`complaint`), **registo** (`import_run`, `job`).
- **Decisões de desenho:** `edit_log` e `duplicate_pair` ligam-se ao elemento pelo `ext_id`, **sem chave estrangeira**, para o histórico sobreviver à recriação; **nada é apagado pelo técnico** (rejeitar e juntar mudam só o `status` e podem reverter-se); a base **recusa imagens não desfocadas** (`image_must_be_blurred`); estados `auto`, `validado`, `corrigido`, `rejeitado`, `fundido` («verificados» = `validado` e `corrigido`).

### API (`http://localhost:8000/docs`)
- **Sem token (público):** `GET /elements`, `/elements/{id}` e as exportações devolvem **só elementos verificados**; as rotas de revisão, estatísticas, deteções, processamentos e decisões respondem 401.
- **Com token** (cabeçalho `X-Tecnico-Token`): acesso a tudo, e cada ação grava uma linha no `edit_log` com o nome do técnico.

| Grupo | Rotas |
|---|---|
| Sistema | `/health`, `/config`, `/imports`, `/taxonomy` |
| Catálogo | `GET /elements` (filtros: `family`, `class`, `subclass`, `sign_group`, `install_type`, `color`, `status`, `min_conf`, `min_conf_familia`, `reliable`, `duplicates`, `q`, `bbox`), `/elements/{id}`, `/detections`, `/images/{id}`, `/stats` 🔒 |
| Revisão 🔒 | `/review-queue` (da menor para a maior confiança), `/duplicates`, `/elements/{id}/history`, `/history` e `/history/export.csv`, `/me` |
| Ações 🔒 | `POST /elements/{id}/validate`, `/reject`, `/restore`, `/merge`, `/split`; `PATCH /elements/{id}` (corrigir classe, tipo, cor, posição); `PUT /elements/{id}/best-detection` |
| Decisões (ligação à pipeline) 🔒 | `GET /decisions` (`?since=`), `POST /decisions` (atómico) |
| Reclamações | `POST /complaints` (foto até 8 MB), `GET /complaints`, `PATCH /complaints/{id}` 🔒, exportação em CSV 🔒 |
| Exportação | `GET /export.geojson`, `GET /export.csv` (separador `;`), com as licenças das fontes |
| Pedidos de imagens | `GET /jobs`, `PATCH /jobs/{id}`, `POST /jobs/video` 🔒, `POST /jobs/source` 🔒, `POST /jobs/{id}/importar` (fontes desligadas, como o Street View, devolvem 403) |

### Frontend
| | Técnico da câmara | Público |
|---|---|---|
| Entrada | código de acesso | sem código |
| Separadores | Mapa, Catálogo, Por rever, Histórico, Importar imagens, Reclamações | Mapa, Reclamações |
| Elementos visíveis | todos | só verificados |
| Ações | validar, corrigir, rejeitar, juntar, separar, exportar, importar | reportar um problema |

O **mapa** (Leaflet) mostra um marcador por elemento, o círculo de incerteza e, no selecionado, as câmaras que o viram; o painel mostra a imagem com a caixa, o tipo, a confiança, a fonte e a licença. Nos contentores isolados mostra o tipo sugerido pelo modelo.

### Worker (pedidos «Importar imagens»)
O técnico escreve uma rua e pede imagens. O `worker/ctrlf_worker.py` corre **no computador da pipeline** e, em ciclo: (1) lê os pedidos na fila; (2) cria a zona `pedido_<id>` à volta da rua (raio de 150 m, até 40 imagens) e corre `python -m ctrlf zona run pedido_<id>`; (3) mostra o progresso na interface (lê o `estado.json` da zona); (4) descompacta a entrega em `dados/entregas/pedido_<id>` e pede à API para a **juntar** ao catálogo. Os elementos novos aparecem como «Por rever»; **nada do que já existe é apagado**. Vídeos: ainda não (a pipeline não tem essa etapa).

## Alternativas que rejeitámos
- **Street View como fonte:** desligado, porque os termos do Google Maps Platform não permitem guardar as imagens nem treinar modelos com elas.
- **Apagar ou fundir de verdade:** rejeitar e juntar só mudam o estado, para se poderem desfazer.
- **Chaves estrangeiras para o histórico:** não, para não o perder quando o importador recria os elementos.

## Resultados medidos (verificados por nós, com a pipeline atual)
- **Testes da interface:** `docker compose exec api pytest -q` → **30 passed** (o documento original indicava 24).
- **Importação do pacote de Aveiro** produzido pela pipeline deste repositório (já com a atualização dos contentores): esquemas válidos; **1 938 elementos únicos** (de 2 822), **13 930 deteções**, **7 032 imagens** (incluindo as 12 sem ficheiro, com `path` nulo), **249 grupos de duplicados**; versão do esquema 1.3.
- **Perfis:** o público vê 0 elementos enquanto nenhum estiver validado e recebe **401** em `/stats`; o técnico vê os **312** contentores e ilhas. Recortes e imagens são servidos (`/media/...`); uma imagem sem ficheiro devolve 200 com `url: null`.
- **Frontend:** compila (`vite build`), é servido pelo nginx (`http://localhost:5173`, título «CTRL+F — Mapa do mobiliário urbano») e o nginx encaminha `/api` e `/media` para a API (por exemplo, a luz devolve 120 elementos pelo nginx).
- **Worker:** liga-se à API, termina quando não há pedidos e recusa uma pasta de pipeline errada.

## Resultados esperados (hipóteses)
- Se os ids dos contentores mudarem entre entregas, as decisões sobre os que desaparecem ficam sem elemento e as dos que mantêm o id passam a referir-se a um elemento que pode ter outra composição (capítulo 10).

## O que NÃO está medido
- ⚠ **O frontend no navegador** (interações, o que mostra para uma imagem sem ficheiro): só se verificou que compila e é servido; **não se usou a aplicação**.
- ⚠ **Um pedido completo do worker** (criar a zona, descarregar do Mapillary, correr a pipeline e juntar ao catálogo): não foi executado por nós.
- ⚠ O importador marca `blur_audited = false` até haver auditoria registada na base de dados; o desfoque foi auditado por um colega (capítulo 03), mas **a base de dados não o sabe**.

## Falhas conhecidas e cuidados
- **Valores por omissão só para desenvolvimento:** a base de dados usa utilizador e palavra-passe `ctrlf`, publica a porta 5432, e o técnico de demonstração tem o código `demo-ana`. **Trocar antes de expor a interface** (ver «Usar noutro município» no `interface/README.md`).
- **Não usar `docker compose down -v`**: apaga a base de dados, incluindo o `edit_log` e as reclamações.
- **Depois de copiar uma entrega nova é preciso correr o importador e recarregar a página**: a aplicação mostra o que está na base de dados, não o que está em `dados/entrega/`.
- **As fotos das reclamações não são desfocadas automaticamente**: só os técnicos as veem, ficam fora de `/media`, e o formulário pede para não fotografar pessoas nem matrículas.
- O `.bat` do worker é para **Windows** e tem de ser ajustado às pastas de cada máquina.

## Como correr
```bash
cd interface
docker compose up --build -d                         # http://localhost:5173  (API: http://localhost:8000/docs)
docker compose exec api python -m app.importar       # importar interface/dados/entrega
docker compose exec api pytest -q                    # esperado: 30 passed
```
O passo a passo completo, desde a pipeline, está na [secção 14 do README](../README.md#14-usar-a-interface-depois-de-preparar-os-dados).
