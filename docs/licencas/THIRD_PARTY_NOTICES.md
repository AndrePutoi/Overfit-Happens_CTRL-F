# Avisos de terceiros: modelos incluídos

Este pacote inclui pesos e ficheiros de configuração/tokenizer **não modificados** de dois modelos publicados no Hugging Face. O texto da licença aplicável está em `LICENSES/Apache-2.0.txt`.

Origem desse texto: o corpo do ficheiro `LICENSE` da distribuição `transformers 5.23.0`, sem a linha de copyright da Hugging Face.

## 1. Grounding DINO Tiny

**Repositório e revisão:**
- Repositório: `IDEA-Research/grounding-dino-tiny` (Hugging Face).
- Revisão: `a2bb814dd30d776dcf7e30523b00659f4f141c71`.
- Caminho no pacote: `models/hf_cache/hub/models--IDEA-Research--grounding-dino-tiny/`.

**Licença declarada: Apache-2.0.** Foi lida em 13-11-2026 em três sítios:
- metadados `license: apache-2.0` do `README.md` da revisão fixada;
- `cardData.license` da API do Hugging Face para essa revisão;
- `LICENSE` do código original em `github.com/IDEA-Research/GroundingDINO`, com "Copyright 2023 - present, IDEA Research".

**Limitação da evidência:**
- O repositório do modelo **não tem** ficheiro LICENSE nem NOTICE.
- O README do código original não indica a licença dos pesos.
- A licença dos pesos assenta, portanto, na etiqueta de metadados do Hugging Face.

**Citação pedida pelos autores:** Liu et al., *Grounding DINO: Marrying DINO with Grounded Pre-Training for Open-Set Object Detection*, 2023 (arXiv:2303.05499).

## 2. DINOv2 Small

**Repositório e revisão:**
- Repositório: `facebook/dinov2-small` (Hugging Face).
- Revisão: `ed25f3a31f01632728cabb09d1542f84ab7b0056`.
- Caminho no pacote: `models/hf_cache/hub/models--facebook--dinov2-small/`.

**Licença declarada: Apache-2.0.** Foi lida em 13-11-2026 em dois sítios:
- metadados `license: apache-2.0` do `README.md` da revisão fixada e `cardData.license` da API;
- README do código original em `github.com/facebookresearch/dinov2`: "DINOv2 code and model weights are released under the Apache License 2.0".

O mesmo README aplica outras licenças, não comerciais, a variantes que **não** estão incluídas aqui: XRay-DINO e Cell-DINO.

O repositório do modelo não tem ficheiro LICENSE nem NOTICE.

**Citação pedida pelos autores:** Oquab et al., *DINOv2: Learning Robust Visual Features without Supervision*, 2023 (arXiv:2304.07193).

## Alterações

Nenhuma. Os ficheiros são cópias byte a byte dos ficheiros em cache. Os SHA-256 estão em `MANIFEST.json`, e o SHA-256 de cada `model.safetensors` coincide com o identificador LFS do blob em cache.
