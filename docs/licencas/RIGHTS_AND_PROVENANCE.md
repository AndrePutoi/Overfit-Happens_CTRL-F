# Direitos e proveniência

> **⚠ Risco legal não resolvido.** Os direitos de redistribuição do dataset GTSRB e dos checkpoints treinados com ele **não foram estabelecidos de forma independente**. Este pacote foi preparado a pedido do responsável do projeto como **entrega técnica privada, só para a equipa**, no âmbito do ensaio pré-hackathon. **Não é publicação, não é licença e não autoriza uso comercial.** O facto de a partilha ser privada **não resolve** direitos de terceiros. A decisão de transferir cabe ao responsável do projeto.

## GTSRB (dataset incluído: `data/raw/gtsrb/`)

- **Origem:** arquivo público ERDA/SID, `https://sid.erda.dk/public/archives/daaeac0d7ce1152aea9b61d9f1e19370/`, criado a 2019-05-10 por Christian Igel (DIKU). Descarregado a 13-11-2026.
- **Ficheiros:** bytes originais, sem alterações. Os SHA-256 estão em `MANIFEST.json` e em `tools/extract_gtsrb.py`.
  - `GTSRB_Final_Training_Images.zip`: 276 294 756 B
  - `GTSRB_Final_Test_Images.zip`: 88 978 620 B
  - `GTSRB_Final_Test_GT.zip`: 99 620 B
- **Autores:** J. Stallkamp, M. Schlipsing, J. Salmen, C. Igel. Instituição: Institut für Neuroinformatik, Ruhr-Universität Bochum.
- **Citações listadas pela fonte:**
  - *Man vs. Computer: Benchmarking Machine Learning Algorithms for Traffic Sign Recognition*, Neural Networks 32, pp. 323–332, 2012;
  - *The German Traffic Sign Recognition Benchmark: A Multi-class Classification Competition*, IJCNN 2011, pp. 1453–1460.
- **Termos e licença: NÃO VERIFICADOS.**
  - A página ERDA não tem licença nem termos.
  - O site oficial `benchmark.ini.rub.de` estava inacessível (DNS) a 13 e 14-11-2026.
  - Os readmes dos arquivos não têm termos. O readme do teste pede que, ao publicar resultados, o conjunto de teste sirva só para a avaliação final.

## Checkpoints da hierarquia de sinais (`models/hier_sinal_gtsrb/`)

- **Ficheiros:** `router.pt` e `esp_circular_vermelho.pt`, com o seu `manifest.json`. São exatamente os ficheiros do ensaio PKG-4 (13-11-2026); não foram retreinados nem alterados.
- **O que são:** DINOv2-small (Apache-2.0) afinado com imagens GTSRB, mais uma cabeça linear.
- **Direitos sobre modelos derivados do GTSRB: NÃO ESTABELECIDOS.**

## Modelos base (`models/hf_cache/`): licença verificada

| Modelo | Revisão | Licença | Evidência |
|---|---|---|---|
| `IDEA-Research/grounding-dino-tiny` | `a2bb814dd30d776dcf7e30523b00659f4f141c71` | Apache-2.0 | metadados HF da revisão, mais o LICENSE do repositório original de código. O repositório do modelo não tem LICENSE, por isso a licença dos pesos assenta na etiqueta HF |
| `facebook/dinov2-small` | `ed25f3a31f01632728cabb09d1542f84ab7b0056` | Apache-2.0 | metadados HF, mais o README original: "code and model weights … Apache License 2.0" |

Texto da licença: `LICENSES/Apache-2.0.txt`. Os avisos estão em `LICENSES/THIRD_PARTY_NOTICES.md`.

## Código da equipa

`A_modelos/`, `common/`, `scripts/` e `reports/ensaio/*.json` são cópias exatas do commit `6f3ffaf`. O código **não tem licença definida**, e este pacote não lhe acrescenta nenhuma.

`tools/`, `smoke/`, `README_TEAM.md`, `MANIFEST.json` e este ficheiro foram criados para o empacotamento.

## Excluído

- Fotografias reais, que podem ter pessoas e matrículas.
- Recortes GTSRB derivados: regeneram-se com `A_modelos/gtsrb_prepare.py`.
- Classificador sintético, Depth Anything, YuNet, RF-DETR e MTSD/Vistas.
- `.venv`, `.git`, logs, credenciais.
