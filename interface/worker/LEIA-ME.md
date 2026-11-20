# Worker: pedidos de imagens → pipeline → mapa

A página **Importar imagens** regista os pedidos (tabela `job`). Este programa corre ao lado do Docker, no computador
onde está o pipeline, e trata deles um de cada vez:

1. lê os pedidos em fila (`GET /jobs?status=na_fila`);
2. cria a zona `pedido_<id>` no pipeline à volta da rua escrita pelo técnico (raio de 150 m, até 40 imagens) e corre
   `python -m ctrlf zona run pedido_<id>`;
3. mostra na interface a etapa em curso e o progresso;
4. descompacta a entrega em `dados/entregas/pedido_<id>` e a API **junta-a ao catálogo** (`POST /jobs/<id>/importar`,
   importador com `--juntar`): os elementos novos aparecem no mapa como "Por rever"; nada do que já existe é apagado.

Vídeos: ainda não (o pipeline não tem essa etapa); o pedido fica com o estado "Erro" e a explicação.

## Arrancar (Windows)

Precisa da pipeline instalada com o seu ambiente Python (secções 2 a 4 do `README.md` da raiz do repositório), dos pesos e do token do
Mapillary no ficheiro `.env` da pasta do repositório da pipeline. Depois, duplo clique em `iniciar_worker.bat` (ajuste as pastas lá
dentro) e deixe a janela aberta. Opções úteis no fim da linha do `.bat`: `--cpu` (sem GPU, muito mais lento),
`--max 20` (menos imagens, mais rápido), `--raio 100`.

Se a rua escrita não for encontrada no OpenStreetMap, usa-se a zona piloto inteira (com o mesmo limite de imagens).
Registo de cada pedido: `<pipeline>/data/zonas/pedido_<id>/worker.log`.
