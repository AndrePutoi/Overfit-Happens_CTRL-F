# Zonas de exemplo

Uma **zona** é uma caixa geográfica mais uns limites de descarga. Este diretório tem um molde e um exemplo real; a pasta que a pipeline lê é `data/zonas/<nome>/zona.json`.

## Criar uma zona nova (3 comandos)
```bash
# 1. a partir do nome de um sítio (OpenStreetMap/Nominatim: só este texto vai à rede) ...
python -m urban_mobile_search zona init meu_sitio --place "Baixa, Lisboa" --raio 250
#    ... ou a partir de um ponto
python -m urban_mobile_search zona init meu_sitio --centro 38.7101 -9.1370 --raio 250

# 2. ver as etapas e os comandos, sem correr nada
python -m urban_mobile_search zona plan meu_sitio

# 3. correr tudo (precisa de MAPILLARY_TOKEN no ambiente ou num ficheiro .env na raiz, e dos pesos em UMS_MODELS_DIR)
python -m urban_mobile_search zona run meu_sitio
```
O resultado é `Entrega_C/entrega_meu_sitio_AAAA-MM-DD.zip` (esquema 1.3) e `data/zonas/meu_sitio/estado.json`.

## Campos de `zona.json`
| Campo | Significado |
|---|---|
| `nome` | minúsculas, dígitos e `_` (2 a 41 caracteres); entra em nomes de ficheiros |
| `bbox` | `[minLon, minLat, maxLon, maxLat]` (a ordem do Mapillary). A API do Mapillary só aceita caixas com menos de 0,01° de lado |
| `since` | só imagens capturadas desde esta data |
| `max` | máximo de imagens a descarregar (as primeiras por sequência e hora: ficam seguidas) |
| `max_panoramas` | lugares reservados, dentro de `max`, a panoramas 360° (cada um dá 4 vistas) |
| `stride` | 1 imagem em cada N |
| `raio_m`, `centro`, `fonte_da_caixa` | só informação de como a caixa foi criada (opcionais) |

Dados do OpenStreetMap © colaboradores do OpenStreetMap (ODbL). Imagens do Mapillary sob CC BY-SA 4.0 (a atribuição vai por imagem no pacote).
