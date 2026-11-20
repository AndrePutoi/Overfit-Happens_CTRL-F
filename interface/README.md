# CTRL+F — Identificação automática do mobiliário urbano

> Parte do repositório da pipeline Ctrl+F (ver o `README.md` da raiz, secção 14, e `docs/16_interface.md`). Esta pasta é autónoma: o `docker compose` corre aqui.

Aveiro Tech City Hackathon 2026, desafio 2. Catálogo georreferenciado de sinalização vertical, iluminação pública e resíduos, com revisão por técnicos e exportação em GeoJSON e CSV.

## Arrancar

1. Descompactar a entrega do pipeline para `dados/entrega` (ver `dados/LEIA-ME.md`).
2. Arrancar:
   ```bash
   docker compose up --build
   ```
3. Noutro terminal, importar a entrega:
   ```bash
   docker compose exec api python -m app.importar
   ```

- **Aplicação: http://localhost:5173**
- API: http://localhost:8000 (documentação interativa em http://localhost:8000/docs)
- Imagens e recortes: http://localhost:8000/media/entrega/...
- PostGIS: `localhost:5432`, base `ctrlf`, utilizador e palavra-passe `ctrlf`
- Token de técnico para testar: `demo-ana` (cabeçalho `X-Tecnico-Token`)

**Dois perfis.** Na aplicação escolhe-se à entrada:
- **Técnico** (código de acesso, ex.: `demo-ana`): vê tudo, revê, corrige, exporta e importa.
- **Público**: só o mapa, só com os elementos já verificados (validados ou corrigidos), e o separador Reclamações.

Na API é o mesmo: sem o cabeçalho `X-Tecnico-Token`, `GET /elements`, `GET /elements/{id}` e as exportações só devolvem elementos verificados; as rotas de revisão, estatísticas, deteções, processamentos e decisões pedem o token. Em http://localhost:8000/docs, preencha `x-tecnico-token` com `demo-ana` para ver tudo.

**Reclamações dos cidadãos.** No perfil público, ao abrir um elemento, "Reportar um problema" permite dizer que:
- está no sítio errado (o cidadão clica no mapa na posição certa, até 300 m);
- está partido, sujo ou vandalizado (com foto opcional, até 8 MB);
- o tipo está errado (escolhe o tipo certo);
- está repetido (escolhe o outro elemento, a menos de 60 m).
- não é mobiliário urbano (deteção errada; o técnico pode rejeitar o elemento);
- outros (descrição obrigatória no comentário).

O separador **Reclamações** mostra o estado de cada uma (por resolver, a resolver, resolvido) e a resposta da câmara; "Só as minhas" usa os números guardados no próprio browser. O público não vê o comentário escrito nem a foto. No perfil técnico, o separador Reclamações permite filtrar por estado e tipo, ver a foto, mudar o estado, responder ao cidadão, aplicar a correção proposta (mover, mudar o tipo, juntar, rejeitar) e descarregar tudo em CSV. A tabela `complaint` é criada pela API ao arrancar (`db/init/03_reclamacoes.sql`), por isso uma base de dados já existente não precisa de ser apagada. Rotas: `POST /complaints`, `GET /complaints`, `PATCH /complaints/{id}`, `GET /complaints/{id}/photo`, `GET /complaints/export.csv`.

**Entrega v1.3 do pipeline.** O importador usa `elementos_unicos.geojson` quando existe (inventário único, com as fusões automáticas já feitas; `merged_from` guarda os ids juntados) e `ilhas.json` (composição sugerida de cada ilha de reciclagem: um contentor com 2 ou mais caixotes fica como "ilha"). Bancos: família `mobiliario`, classe `banco`. A posição dos elementos de vista única usa `position_sigma_m`; `clip_suspect` aparece como aviso ao técnico. As colunas novas são criadas pela API ao arrancar (`db/init/04_entrega_v13.sql`).

**Atenção quando os ids mudam entre entregas.** As decisões do técnico são reaplicadas pelo id do elemento. Se o pipeline renumerar os elementos, importe com `--sem-decisoes` e limpe as decisões e reclamações antigas, que apontariam para outros objetos:

```bash
docker compose exec db psql -U ctrlf -d ctrlf -c "TRUNCATE edit_log, complaint;"
docker compose exec api python -m app.importar --sem-decisoes
```

**Pedidos de imagens (Importar imagens → pipeline).** O técnico escreve uma rua e carrega em "Pedir imagens desta rua". O programa `worker/ctrlf_worker.py`, que corre no computador do pipeline (ver `worker/LEIA-ME.md`), processa o pedido e junta o resultado ao catálogo, sem apagar o que existe (`python -m app.importar <pasta> --juntar`).

Base limpa (apaga também as decisões do técnico):

```bash
docker compose down -v && docker compose up --build
docker compose exec api python -m app.importar
```

## Frontend em modo de desenvolvimento

Para mexer na interface e ver as alterações logo no browser (precisa de Node.js; a API tem de estar a correr no Docker):

```bash
cd web
npm install        # só da primeira vez
npm run dev        # http://localhost:5173
```

Pare antes o serviço `web` do Docker (`docker compose stop web`), porque usa a mesma porta.

## Testes

```bash
docker compose exec api pytest -q
```

Correm sobre uma amostra de 10 elementos numa base à parte (`ctrlf_test`); não mexem nos dados importados.

## Usar noutro município

O CTRL+F não tem nada de Aveiro no código: o município, a zona, as fontes e as classes estão em configuração. Para outra câmara usar o sistema:

1. **Copiar o repositório** e instalar o Docker Desktop. Não é preciso mais nada.
2. **Indicar o município e a zona** em `db/init/02_config.sql`, na linha `INSERT INTO municipality`:
   - `name`: nome do município (aparece no ecrã de entrada e no perfil);
   - `pilot_zone_name`: nome da zona (aparece no cabeçalho);
   - `area`: polígono da zona em longitude/latitude. Para o obter, desenhar um retângulo em https://geojson.io e copiar as coordenadas.

   Exemplo:
   ```sql
   INSERT INTO municipality (id, name, code_prefix, pilot_zone_name, area) VALUES
     (1, 'Ílhavo', 'IL', 'Ílhavo — Centro',
      ST_GeomFromText('POLYGON((-8.676 40.596, -8.660 40.596, -8.660 40.606, -8.676 40.606, -8.676 40.596))', 4326));
   ```
3. **Escolher as fontes de imagem** no mesmo ficheiro (`INSERT INTO source`): `enabled = true` nas que se usam. O Street View fica desligado salvo autorização escrita da Google.
4. **Criar os técnicos** no mesmo ficheiro (`INSERT INTO technician`), cada um com um código de acesso próprio. Trocar o `demo-ana`.
5. **Rever as classes** em `shared/taxonomia.json`. Os sinais seguem o Regulamento de Sinalização do Trânsito, igual em todo o país, por isso em regra não é preciso mudar nada. Só se o município tiver equipamentos diferentes (outro tipo de contentor, outra cor de ecoponto).
6. **Criar a base e arrancar** (o `02_config.sql` só corre numa base nova):
   ```bash
   docker compose down -v
   docker compose up --build -d
   ```
7. **Gerar e importar os dados.** Correr o pipeline sobre as imagens do município, pôr a entrega em `dados/entrega` e importar:
   ```bash
   docker compose exec api python -m app.importar
   ```

Cada município fica com a sua instalação e os seus dados, separados dos de outras câmaras. A base de dados já tem a tabela `municipality` preparada para vários municípios na mesma instalação; para isso faltaria a API filtrar por município.

## Estrutura

| Pasta | Conteúdo |
| --- | --- |
| `shared/taxonomia.json` | Classes do pipeline, tipos de sinal em português, grupos, cores |
| `db/init/` | Esquema PostGIS (`01_schema.sql`), configuração (`02_config.sql`) e reclamações (`03_reclamacoes.sql`) |
| `api/app/main.py` | API FastAPI |
| `api/app/acoes.py` | Ações do técnico (usadas pela API e pelo importador) |
| `api/app/reclamacoes.py` | Reclamações dos cidadãos |
| `api/app/importar.py` | Importação da entrega do pipeline |
| `api/tests/` | Testes e amostra da entrega |
| `web/src/` | Interface: `App.jsx` (estado e filtros), `components/` (mapa, detalhe, rever, catálogo, importar), `tax.js` (ícones e rótulos), `api.js` |
| `dados/` | Entrega do pipeline (fora do Git) |
| `docs/contrato-dados.md` | Formato de troca entre pipeline, API e interface |
| `docs/dados.md` | Importar, recomeçar, consultar |

## Privacidade e licenças

- As imagens vêm do pipeline com rostos e matrículas desfocados (desfoque já auditado).
- A base de dados recusa guardar o caminho de uma imagem que não esteja marcada como desfocada (restrição `image_must_be_blurred`).
- Imagens do Mapillary (CC BY-SA 4.0): a atribuição vai em cada imagem e em cada exportação. Posições de referência e vias: © colaboradores do OpenStreetMap (ODbL).
- O Google Street View está desligado (`source.enabled = false`): os termos do Google Maps Platform não permitem guardar as imagens, treinar com elas nem mostrá-las sobre um mapa que não seja da Google.
- Fotos das reclamações: só os técnicos as veem (pedido com token), guardadas fora da pasta pública `/media`. O formulário pede ao cidadão para não fotografar pessoas nem matrículas, mas a foto não é desfocada automaticamente.
- Licença do código, propriedade intelectual e licenças de terceiros: ver `LICENSE.md`.
