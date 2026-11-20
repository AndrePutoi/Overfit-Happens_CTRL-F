# dados/

Pasta ligada à API (`/data/media`). **Não vai para o git** (só este ficheiro).

## `dados/entrega/`: a entrega da pipeline
Descompacte aqui o pacote que a etapa `entrega` da pipeline gera (`Entrega_C/entrega_<zona>_<data>.zip`), **substituindo** o que lá estiver. Os ficheiros ficam diretamente dentro de `dados/entrega/`:

```
elementos.geojson   elementos_unicos.geojson   deteccoes.json   imagens.json
ilhas.json   duplicados.json   manifest.json   imagens/   recortes/   schema/
```
```bash
unzip -o ../../Entrega_C/entrega_aveiro_piloto_*.zip -d entrega      # a partir de interface/dados
docker compose exec api python -m app.importar                       # a partir de interface/
```
Só devem estar aqui imagens **anonimizadas** (a base de dados recusa as outras).

## `dados/entregas/pedido_<id>/`
Criada pelo worker (`worker/`) para cada pedido da página «Importar imagens».
