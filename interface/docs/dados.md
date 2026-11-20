# Dados: importar a entrega do pipeline

Os comandos funcionam em PowerShell e em bash, dentro da pasta `interface/`, com o `docker compose up` a correr.

## O que vem na base de dados

| Origem | Conteúdo |
| --- | --- |
| `db/init/01_schema.sql` | Tabelas, índices, vista `v_element` (só na criação da base) |
| `db/init/02_config.sql` | Município, zona piloto, fontes com licenças, técnica `demo-ana` (só na criação da base) |
| Entrega do pipeline em `dados/entrega` | Elementos, deteções, imagens, duplicados (com `app.importar`) |

## Importar (primeira vez ou entrega nova)

1. Descompactar o zip da entrega para `dados\entrega` (os ficheiros `elementos.geojson`, `deteccoes.json`, … ficam diretamente dentro de `dados\entrega`).
2. Correr:
   ```powershell
   docker compose exec api python -m app.importar
   ```
3. No fim aparece o resumo: elementos, deteções, imagens, duplicados e quantas decisões do técnico foram reaplicadas.

Numa entrega nova: apagar o conteúdo de `dados\entrega`, descompactar a nova e repetir o passo 2. As decisões do técnico mantêm-se (são reaplicadas pelo `id` de cada elemento).

Opções:
- outra pasta: `docker compose exec api python -m app.importar /data/media/outra_pasta` (tem de estar dentro de `dados\`)
- sem reaplicar decisões: `... python -m app.importar --sem-decisoes`

## Apagar as decisões do técnico (recomeçar a revisão)

```powershell
docker compose exec db psql -U ctrlf -d ctrlf -c "TRUNCATE edit_log"
docker compose exec api python -m app.importar
```

## Consultar a base diretamente

```powershell
docker compose exec db psql -U ctrlf -d ctrlf
```

Exemplos (sair com `\q`):

```sql
SELECT ext_id, name, status, round(confidence::numeric, 2) FROM v_element ORDER BY confidence LIMIT 20;
SELECT sign_group, count(*) FROM element WHERE family = 'sinal' GROUP BY 1 ORDER BY 2 DESC;
SELECT * FROM import_run ORDER BY id DESC;
```

## Testes automáticos

Usam uma amostra de 10 elementos (`api/tests/fixture`) numa base à parte (`ctrlf_test`); não mexem nos teus dados.

```powershell
docker compose exec api pytest -q
```
