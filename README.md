# Ctrl+F · pipeline de deteção e geolocalização de mobiliário urbano

A partir de imagens de rua do Mapillary, esta pipeline **deteta sinais, contentores de resíduos, iluminação e bancos**, **calcula a posição de cada um no mapa**, **junta as várias vistas do mesmo objeto numa só entrada** e produz um GeoJSON (`elementos_unicos.geojson`). Corre numa GPU de 6 GB, **por zona** e de forma **retomável**, e **protege a privacidade antes de qualquer outro passo**: se uma imagem não tiver passado pelo anonimizador (com a integridade do ficheiro confirmada por sha256), nada a jusante corre. **Isto não garante que todos os rostos e matrículas foram apanhados** (ver secção 12).

Foi desenvolvida no Hackathon Aveiro Tech City #2 (piloto: Aveiro; testada também no Porto e em Lisboa).

> **Antes de usar os resultados, leia a secção 12 (limites).** A exatidão dos modelos foi medida sobretudo no Porto; em zonas novas **não está medida**, e a proteção das matrículas foi fraca no teste (43 %); a auditoria em Aveiro não tem números registados.

## Índice
1. [O que precisa](#1-o-que-precisa) · 2. [Instalar](#2-instalar) · 3. [Obter os pesos](#3-obter-os-pesos) · 4. [Token do Mapillary](#4-token-do-mapillary) · 5. [Definir uma zona](#5-definir-uma-zona) · 6. [Correr a pipeline](#6-correr-a-pipeline) · 7. [Retomar e refazer](#7-retomar-e-refazer) · 8. [Ler os resultados](#8-ler-os-resultados) · 9. [Uma etapa isolada e os testes](#9-uma-etapa-isolada-e-os-testes) · 10. [Demonstração do Grounding DINO](#10-demonstração-do-grounding-dino) · 11. [Problemas frequentes](#11-problemas-frequentes) · 12. [Limites e honestidade](#12-limites-e-honestidade) · 13. [Mapa do repositório](#13-mapa-do-repositório) · 14. [Usar a interface](#14-usar-a-interface-depois-de-preparar-os-dados)

---

## 1. O que precisa
| | |
|---|---|
| **GPU** | NVIDIA com **6 GB** (foi validada numa RTX 3060). Sem GPU corre com `--cpu`, mas é muito lento: serve para testar, não para trabalhar. |
| **Sistema** | Linux, **Python 3.12**. |
| **Disco** | cerca de 3 GB para os pesos (2,5 GB no zip), mais o espaço das imagens da zona, que cresce com o número de panoramas. |
| **Rede** | só nas etapas `descarregar` (Mapillary) e `referencias` (OpenStreetMap). Nenhuma envia imagens; só a caixa geográfica da zona. |
| **Conta** | um token da API do Mapillary (passo 4). |

## 2. Instalar
```bash
cd repositorio_limpo
python3.12 -m venv .venv
source .venv/bin/activate

# PyTorch primeiro, com a versão de CUDA do seu sistema (os requirements foram validados com CUDA 13.2).
pip install torch==2.15.0 torchvision==0.29.1 --index-url https://download.pytorch.org/whl/cu132
#   sem GPU:  pip install torch torchvision

pip install -r requirements.txt
pip install -e .                       # instala o pacote `ctrlf` (pasta src/)
```
**Confirmar que ficou instalado** (não deve dar erro e deve listar os comandos):
```bash
python -c "import ctrlf; print(ctrlf.__version__)"
python -m ctrlf zona --help
```
Opcionais: `requirements-treino.txt` (só para treinar modelos), `requirements-dev.txt` (testes), `requirements-yolo-opcional.txt` (só para o backend de privacidade `yolo`, que usa uma biblioteca AGPL-3.0; a omissão é o RF-DETR).

## 3. Obter os pesos
Os pesos (cerca de 2,5 GB) **não estão no repositório**. Estão num zip à parte (**`Ctrl-F_pesos.zip`**, 2,5 GB): **[descarregar do Google Drive]([COLAR_AQUI_A_LIGAÇÃO_DO_DRIVE](https://drive.google.com/drive/folders/1jhj4PVhDUhRxOHBiHwHsXTY-0p0lbeOs?usp=sharing))**.
Para confirmar que o ficheiro ficou inteiro: `sha256sum Ctrl-F_pesos.zip` deve dar `5a2d39d830a8879e30ca55e0294b375b8ccdd9e2034586034d0501e5d4060798`. Este zip tem o **detetor e o classificador de contentores finais** (treinados só com anotações do Porto).

```bash
mkdir -p models
unzip Ctrl-F_pesos.zip -d models        # as pastas descompactam diretamente para models/
export UMS_MODELS_DIR=$PWD/models       # onde a pipeline procura os pesos (omissão: ./models)
export HF_HOME=$UMS_MODELS_DIR/hf_cache # modelos do Hugging Face, sem internet

python -m ctrlf weights                 # lista o que encontra; "em_falta" tem de vir vazio
python -m ctrlf.scripts.exportar_pesos --verificar $UMS_MODELS_DIR     # confere o sha256 de cada ficheiro
```
- **Uso apenas para investigação / não comercial.** Parte dos pesos foi treinada com o MTSD (CC BY-NC-SA); ver [docs/15_licencas_e_riscos.md](docs/15_licencas_e_riscos.md).
- O pacote `weights` diz ficheiro a ficheiro **onde** deve estar cada peso.

## 4. Token do Mapillary
1. Crie uma conta em <https://www.mapillary.com/developer> e gere um token de cliente (começa por `MLY|`).
2. Guarde-o **fora do git**, num ficheiro `.env` na raiz (já está no `.gitignore`):
```bash
echo 'MAPILLARY_TOKEN=MLY|o_seu_token' > .env
```
(ou `export MAPILLARY_TOKEN=...` no terminal). **Nunca** o ponha no código nem num commit.

## 5. Definir uma zona
Uma **zona** é uma caixa geográfica mais uns limites de descarga, guardada em `data/zonas/<nome>/zona.json`.

**Opção A: usar a zona piloto do hackathon (Aveiro)**, já incluída:
```bash
mkdir -p data/zonas
cp -r zonas_exemplo/aveiro_piloto data/zonas/
```
Está limitada a 25 panoramas (`max_panoramas`) para a primeira corrida demorar poucos minutos. Para a zona inteira, apague esse campo do `zona.json`.

**Opção B: criar uma zona nova**
```bash
python -m ctrlf zona init meu_sitio --place "Baixa, Lisboa" --raio 250     # só o texto do nome vai à rede (Nominatim)
python -m ctrlf zona init meu_sitio --centro 38.7101 -9.1370 --raio 250    # ou a partir de um ponto
```
- O **raio** vai de 50 a 1500 m (omissão 250). A API do Mapillary **só aceita caixas com menos de 0,01° de lado**.
- Comece sempre por uma zona **pequena**. Campos do `zona.json` e mais exemplos: [zonas_exemplo/README.md](zonas_exemplo/README.md).

## 6. Correr a pipeline
```bash
python -m ctrlf zona plan aveiro_piloto     # mostra as 12 etapas e os comandos, SEM correr nada
python -m ctrlf zona run  aveiro_piloto     # corre tudo
```
As etapas, por ordem:

| # | Etapa | O que faz | Usa |
|---|---|---|---|
| 1 | `descarregar` | descarrega as imagens da caixa | rede |
| 2 | `vistas` | converte panoramas 360° em 4 vistas planas (0°, 90°, 180°, 270°; campo de visão 100°) | |
| 3 | `admissao` | rejeita imagens sem posição ou sem qualidade, antes de gastar GPU | |
| 4 | `privacidade` | desfoca rostos e matrículas e **confirma a integridade** de cada imagem (portão de falha fechada; ver nota abaixo) | GPU |
| 5 | `deteccao` | deteta sinais, contentores, luz e bancos, um modelo de cada vez | GPU |
| 6 | `referencias` | vias, luz e ecopontos do OpenStreetMap da zona | rede |
| 7 | `catalogo` | profundidade → posição; associa observações por raios; filtra papeleiras | GPU |
| 8 | `estrada` | corrige a escala da profundidade com o corredor da via | |
| 9 | `tipos` | tipo do contentor (indiferenciado, papel, embalagens, vidro) | GPU |
| 10 | `dedup` | junta as vistas do mesmo objeto (p(mesmo objeto)) | GPU |
| 11 | `entrega` | gera o pacote de entrega e o **resultado final** | |
| 12 | `mapa` | mapa HTML para inspeção (opcional) | |

**Tempo:** depende do número de imagens. Como referência medida: a deteção de contentores nas 17 170 vistas da zona piloto completa levou cerca de 15 minutos com as imagens já anonimizadas; **a privacidade é a etapa mais lenta** (um bloco de 200 vistas passou de ~11 s para 80 a 100 s quando teve de anonimizar). Com `max_panoramas: 25` (a omissão do exemplo) deve ser uma questão de minutos, mas **não medimos o tempo total dessa corrida**.

**Sobre «verificada» na etapa 4:** quer dizer que a imagem **passou pelo anonimizador e o ficheiro não foi alterado** desde então (sha256 no manifesto). **Não** quer dizer que todos os rostos e matrículas foram desfocados: a taxa de deteção é ~90 % nos rostos e ~43 % nas matrículas (secção 12).

O que vê no terminal: uma linha por etapa (`pendente` → `feita` ou `falhou`), com o tempo e as contagens que a verificação da etapa mediu.

## 7. Retomar e refazer
- O estado de cada etapa fica em `data/zonas/<zona>/estado.json` e o log em `data/zonas/<zona>/logs/<etapa>.log`.
- **Se parar a meio** (Ctrl+C, falta de luz, erro), volte a correr o mesmo `zona run`: as etapas já feitas, cujas saídas continuam no disco, são **saltadas**.
- Ver o estado: `python -m ctrlf zona status aveiro_piloto`. Listar zonas: `python -m ctrlf zona list`.
- Correr só até uma etapa: `--ate catalogo`. Correr só algumas: `--so dedup entrega`.
- **Refazer** uma etapa: `--refazer deteccao`. Ao refazer, **as etapas seguintes ficam pendentes** (dependem dela), e as suas caches são apagadas.
- Só se repete automaticamente o **aborto intermitente do PyTorch** (até 3 vezes). Qualquer outro erro pára à primeira, de propósito, para não esconder defeitos.
- Duas zonas não correm em paralelo na mesma GPU: há um *lock* em `data/zonas/.gpu.lock`.

## 8. Ler os resultados
| Ficheiro | O que é |
|---|---|
| **`data/zonas/<zona>/resultado/elementos_unicos.geojson`** | **O RESULTADO FINAL**: um ponto por objeto, com as várias vistas já fundidas. |
| `Entrega_C/entrega_<zona>_<data>.zip` | pacote completo (deteções, imagens, ilhas, duplicados, esquemas JSON): serve para auditar um elemento e **é o que a interface importa** (secção 14). |
| `data/catalog/<zona>/mapa.html` | mapa para inspeção visual (abre no navegador). |
| `data/zonas/<zona>/estado.json` | estado e contagens de cada etapa. |

Cada elemento tem, entre outros: `id`, `family` (`sinal`, `residuos`, `iluminacao`, `mobiliario`), `class` e `subclass` (por exemplo o tipo do contentor), `confidence`, `n_views` (quantas vistas o apoiam), `geo_method`, `position_sigma_m` (**incerteza da posição, em metros**), `position_reliable`, e `observations` (as deteções de origem). Descrição campo a campo em [docs/10_resultado_e_entrega.md](docs/10_resultado_e_entrega.md).

Pontos a ter presentes ao usar o resultado:
- **A posição tem erro** (ordem de 10 m, melhor com várias vistas); use `position_sigma_m`.
- **O tipo do contentor é uma sugestão** (cerca de 63 % de exatidão no Porto).
- **Os ids nunca se renumeram** entre atualizações: o que desaparece deixa um buraco.

## 9. Uma etapa isolada e os testes
`python -m ctrlf zona plan <zona>` imprime o comando exato de cada etapa. Por exemplo, para repetir só a deduplicação:
```bash
python -m ctrlf.scripts.deduplicar --cidade aveiro_piloto
```
**Testes** (autotestes sem GPU nem pesos; cada ficheiro termina com `overall: PASS` ou `FAIL`):
```bash
for f in tests/unit/*.py; do echo "== $f"; python "$f" | tail -1; done
```

## 10. Demonstração do Grounding DINO
Em [`demo_grounding_dino/`](demo_grounding_dino/) há uma demonstração de **pré-anotação sem treino** (o Grounding DINO propõe caixas a partir de texto). **Não faz parte da pipeline**: serve para mostrar o que um modelo zero-shot faz e as suas limitações (muitos falsos positivos). Instruções e resultados em [demo_grounding_dino/README.md](demo_grounding_dino/README.md).

## 11. Problemas frequentes
| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `nenhuma imagem descarregada` | caixa sem cobertura Mapillary, ou token em falta | confirme o `.env`; teste outra caixa; a caixa tem de ter < 0,01° de lado |
| `PORTÃO DE PRIVACIDADE: N vistas sem anonimização verificada` | a etapa 4 não correu ou o manifesto não bate | **não contorne**: refaça a etapa `privacidade` (`--refazer privacidade`) |
| `CUDA out of memory` | outro programa a usar a GPU, ou lotes grandes | feche o navegador/IDE com GPU; `export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True`; a pipeline carrega um modelo de cada vez |
| `getCount is non-monotonic`, `CUDA error: ...` | aborto intermitente do PyTorch | é repetido sozinho até 3 vezes; se persistir, reinicie a máquina |
| etapas muito lentas, GPU a 85 °C ou mais | a GPU reduz o relógio por calor | melhorar a ventilação; é mais lento mas não dá erro |
| `python -m ctrlf weights` mostra `em_falta` | pesos mal descompactados | veja o passo 3; cada ficheiro tem de estar no caminho que o comando indica |
| `ModuleNotFoundError: ctrlf` | pacote não instalado | `pip install -e .` com o ambiente ativo |
| zona «já existe com outra configuração» | já há uma zona com esse nome e outra caixa | crie outra zona (evita misturar imagens) |

## 12. Limites e honestidade
O que **está medido** (e onde): contentores mAP50-95 0,43 e tipo de contentor 63 % (Porto); classificador de sinais 94 % (conjunto MTSD); deduplicação AUC 0,90; privacidade em Open Images. O que **não está medido** em zonas novas (incluindo Aveiro): a exatidão dos detetores e do tipo, a dos sinais, da luz e dos bancos, e a proteção de matrículas.

- **Privacidade:** rostos ~90 % protegidos; **matrículas apenas ~43 %** no teste do Open Images. Em Aveiro, uma auditoria visual feita por um colega da equipa teve resultado satisfatório (relato da equipa; os números não estão registados). Confirme antes de publicar imagens.
- **Posição:** mediana de cerca de 11 m contra o OpenStreetMap em Aveiro (cerca de 7 m com várias vistas); a distância é sobrestimada.
- **Tipo do contentor:** 63 % de exatidão (62,6 % equilibrada); é sugestão.
- **Estado do sinal** (degradado, tapado): retirado deste repositório por ser experimental e sem exatidão que se possa apresentar.
- **Licença:** **ainda não há licença formal**: a declaração da equipa está em [`LICENSE.md`](LICENSE.md) (uso não comercial e partilha nas mesmas condições, segundo as Normas do hackathon; licença formal a confirmar com a organização). **Pesos e dados de uso não comercial.**

Detalhe por bloco, com o desenho, as alternativas rejeitadas e o que não está medido: pasta [`docs/`](docs/).

## 13. Mapa do repositório
```
README.md              este guia
LICENSE.md             licença e propriedade intelectual (declaração; licença formal por confirmar)
pyproject.toml         pacote `ctrlf`;  requirements*.txt  dependências
configs/               limiares e políticas (admissão, sinais ignorados, sigma de posição…)
src/ctrlf/
  urban_mobile_search/ orquestrador de zonas (zona/), pipeline, registo de modelos, CLI
  ingest/              Mapillary, vistas planas, admissão, referências OSM
  privacy/             rostos e matrículas, portão de verificação
  detection/           detetor, filtro de papeleiras, classificadores de sinais
  bench_detector/      detetor de bancos
  geometry/            profundidade e geometria
  pipeline/            catálogo, associação por raios, estrada, deduplicação, entrega
  scripts/             as etapas executáveis (`python -m ctrlf.scripts.<nome>`)
  treino/              treino dos modelos (só para quem quiser treinar)
demo_grounding_dino/   demonstração de pré-anotação sem treino
zonas_exemplo/         zona piloto de Aveiro, exemplo de Lisboa e molde
tests/                 autotestes (sem GPU nem pesos)
docs/                  documentação por bloco
```
O código vive em `src/ctrlf/`; os dados, os pesos, as imagens e os resultados ficam em `data/`, `models/` e `Entrega_C/`, que **não** vão para o git. A interface (base de dados, API e frontend) está descrita no capítulo 16, mas **o seu código não está neste repositório** (secção 14).

## 14. Usar a interface depois de preparar os dados
A interface (técnico da câmara e público) está em [`interface/`](interface/): base de dados PostgreSQL com PostGIS, API FastAPI e frontend React com mapa. Descrição completa no [capítulo 16](docs/16_interface.md) e no [`interface/README.md`](interface/README.md). **Precisa de Docker** (Docker Desktop no Windows); o Node.js só é preciso para desenvolver o frontend.

**Passo a passo, da imagem ao ecrã**
1. **Preparar os dados com a pipeline** (secções 5 e 6), até à etapa `entrega`. Fica `Entrega_C/entrega_<zona>_<data>.zip`.
2. **Copiar o pacote para a interface**, **substituindo** o que lá estiver (a partir da raiz deste repositório):
   ```bash
   mkdir -p interface/dados/entrega
   unzip -o Entrega_C/entrega_aveiro_piloto_*.zip -d interface/dados/entrega
   ```
   Tem de ficar com `elementos.geojson`, `elementos_unicos.geojson`, `deteccoes.json`, `imagens.json`, `ilhas.json`, `duplicados.json`, `imagens/`, `recortes/` e `schema/`. Só imagens **anonimizadas** devem ir para aqui (a base de dados recusa as outras).
3. **Arrancar tudo:**
   ```bash
   cd interface
   docker compose up --build -d
   ```
   Aplicação em <http://localhost:5173>; API e documentação em <http://localhost:8000/docs>.
4. **Importar:** `docker compose exec api python -m app.importar`. Valida cada ficheiro contra `schema/*.schema.json`, usa `elementos_unicos.geojson` (o inventário já com as fusões automáticas), **substitui os dados da pipeline** e **volta a aplicar as decisões que os técnicos já tinham tomado** aos elementos com o mesmo `id`. No fim mostra o resumo (elementos, deteções, imagens, grupos de duplicados, decisões reaplicadas).
5. **Abrir a aplicação** (Ctrl+F5 se já estava aberta). **Ela mostra o que está na base de dados, não o que está na pasta**: sem o passo 4 continua a ver os dados antigos.
6. **Entrar.** À entrada escolhe-se o perfil:
   - **Técnico:** código de acesso (para testar, `demo-ana`). Vê todos os elementos e pode validar, corrigir, rejeitar, juntar, separar, exportar, rever a fila «Por rever» (da menor para a maior confiança), consultar o histórico e importar imagens.
   - **Público:** sem código. Vê só os elementos **verificados** (por isso, **no início o mapa público está vazio** até um técnico validar elementos) e pode reportar um problema (posição errada, estado, tipo, duplicado).

**Pedir imagens de uma rua (worker).** Na página «Importar imagens» o técnico escreve uma rua. O `interface/worker/ctrlf_worker.py` corre **no computador da pipeline**, cria a zona do pedido, corre a pipeline e **junta** o resultado ao catálogo (os elementos novos ficam «Por rever»; nada do que existe é apagado). Edite as 3 pastas de `iniciar_worker.bat` (Windows) ou corra: `python interface/worker/ctrlf_worker.py --pipeline <esta pasta> --dados interface/dados --pesos <pasta dos pesos>`. Precisa dos pesos e do token do Mapillary (passos 3 e 4).

**Atualizar com uma nova corrida da pipeline.** Repita os passos 1, 2, 4 e 5. As decisões dos técnicos são reaplicadas **desde que os ids não mudem**: as de um id que desapareceu ficam ignoradas (a importação regista quantas) e as de um id mantido passam a valer para um elemento que pode ter outra composição. Se renumerar tudo, importe com `--sem-decisoes`. A pipeline nunca renumera ids de propósito.

**Devolver as decisões à pipeline.** `GET /decisions` (com o cabeçalho `X-Tecnico-Token`) devolve as correções no formato `decisoes`.

**Cuidados**
- **Nunca usar `docker compose down -v`**: apaga a base de dados, incluindo o histórico de decisões e as reclamações.
- **Valores por omissão só para desenvolvimento:** a base de dados tem utilizador e palavra-passe `ctrlf` e publica a porta 5432, e o técnico de demonstração é `demo-ana`. **Trocar antes de expor a interface** (ver «Usar noutro município» em `interface/README.md`).
- As fotos das reclamações dos cidadãos **não são desfocadas automaticamente** (só os técnicos as veem).
- O tipo do contentor aparece como **sugestão do modelo** (cerca de 63 % de exatidão no Porto); o técnico confirma ou corrige.

**O que verificámos e o que não.** Com o pacote de Aveiro produzido por esta pipeline: arrancar a base de dados e a API, **30 testes da interface a passar**, importar o pacote (1 938 elementos únicos, 13 930 deteções, 7 032 imagens), os perfis público e técnico, e compilar e servir o frontend. **Não verificámos** o uso da aplicação no navegador nem um pedido completo do worker.
