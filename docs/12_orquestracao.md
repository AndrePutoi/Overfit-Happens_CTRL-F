# 12 · Orquestração

## Problema
Encadear 12 etapas (com modelos pesados, rede e GPU de 6 GB) de forma **repetível, retomável e que falhe de maneira legível**.

## Desenho e porquê (`ctrlf/urban_mobile_search/zona/`)
- **Uma etapa é só dados** (`etapas.py`): nome, comando(s), saídas obrigatórias, uma verificação própria e *flags* (`gpu`, `externa`, `portao`, `opcional`). Para mudar um parâmetro ou trocar um script edita-se aqui, sem tocar no runner.
- **Estado em disco** (`data/zonas/<zona>/estado.json`): por etapa, `pendente | feita | falhou`, início e fim, segundos, comando, contagens da verificação, erro e log (`data/zonas/<zona>/logs/<etapa>.log`).
- **Retoma**: uma etapa `feita` com as saídas ainda no disco é saltada.
- **Invalidação**: correr ou refazer uma etapa põe as seguintes em `pendente` (dependem dela) e apaga as suas caches de retoma (por exemplo, os blocos de deteção).
- **Portão**: se a privacidade falhar (ou a sua verificação reprovar), a corrida pára e nada a jusante corre.
- **Tentativas**: só se repetem as falhas **intermitentes** conhecidas do PyTorch/CUDA (`getCount is non-monotonic`, erros de inicialização do CUDA…), até 3 vezes. **Qualquer outro erro falha à primeira**, para não esconder defeitos.
- **GPU**: as etapas `gpu` correm uma de cada vez, com um *lock* em `data/zonas/.gpu.lock`; duas zonas não partilham a placa. `--cpu` desliga a GPU (muito lento, para testar).
- **Rede**: só as etapas `externa` (Mapillary, Overpass) a usam, e só enviam a caixa da zona e um nome de cliente genérico; nenhuma envia imagens.

## Alternativas que rejeitámos
- **Scripts manuais por cidade** (um `prever_*_aveiro.py` por família): a cadeia de Aveiro era feita à mão, passo a passo. O orquestrador substitui-os e torna o piloto repetível noutra zona.
- **Repetir qualquer falha**: esconderia defeitos reais; só se repetem as intermitentes conhecidas.

## Resultados medidos
- A cadeia completa corre de ponta a ponta numa zona de exemplo (foi provada num ambiente limpo no repositório anterior).
- Neste repositório: `tests/unit/23_test_zonas.py` testa o orquestrador; e correu-se a cadeia catálogo → estrada → tipos → deduplicação → entrega sobre os dados de Aveiro, com resultado equivalente ao do código anterior (os mesmos grupos e ids; as diferenças são numéricas e minúsculas, de ruído da GPU).

## O que NÃO está medido
- ⚠ **A instalação a partir de zero** (`pip install -r requirements.txt` num ambiente novo) **não foi repetida neste repositório**; estava provada no repositório anterior.
- ⚠ A corrida completa da zona de exemplo `aveiro_piloto` **não foi cronometrada** neste repositório.

## Falhas conhecidas
- Uma GPU muito quente (85 °C ou mais) reduz o relógio e deixa tudo mais lento; não dá erro.
- O aborto intermitente do PyTorch pode aparecer várias vezes seguidas; se persistir após as 3 tentativas, reinicie a máquina.
- **O hash dos parâmetros de privacidade inclui o caminho da pasta de modelos**: usar uma pasta de pesos diferente invalida a cache de anonimização e refaz tudo.

## Como correr e testar
```bash
python -m ctrlf zona plan aveiro_piloto
python -m ctrlf zona run aveiro_piloto --ate catalogo
python -m ctrlf zona status aveiro_piloto
python tests/unit/23_test_zonas.py
```
