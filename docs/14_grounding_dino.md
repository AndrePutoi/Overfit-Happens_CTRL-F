# 14 · Grounding DINO: a demonstração de pré-anotação

> **Não faz parte da pipeline.** Está em [`../demo_grounding_dino/`](../demo_grounding_dino/).

## Problema
Mostrar o que um modelo **sem treino** (zero-shot) consegue fazer para **pré-anotar** imagens, e porque não o usamos como detetor.

## Desenho e porquê
- O **Grounding DINO Tiny** (IDEA-Research, Apache-2.0) deteta objetos a partir de **texto** («recycling container.»). A demonstração propõe caixas em 8 imagens de exemplo do Porto (já anonimizadas) com três formulações de frases (`simples`, `descritivo`, `por_classe`) e escreve COCO 1.0 importável no CVAT, mais imagens com as caixas desenhadas.
- Serve para **acelerar a anotação manual**: correr, importar, apagar o que sobra, corrigir a classe, acrescentar o que falta.

## Resultados medidos
Nas 8 imagens de exemplo (21 caixas reais: 12 contentores e 9 subterrâneos):

| Solução | Caixas propostas | Classes devolvidas |
|---|---|---|
| `simples` | 13 | só contentor |
| `descritivo` | 33 | contentor 27, subterrâneo 6 |
| `por_classe` | 45 | contentor 30, subterrâneo 15 |

**O padrão**: mais frases dão mais caixas e **mais falsos positivos** (bancos, caixotes de rua, caixas de eletricidade, portas); distingue mal contentor de subterrâneo (a classe vem da frase, não da imagem); **nenhuma solução serve sem revisão humana**.

Numa validação maior do Porto (226 imagens, 152 caixas, IoU 0,5), o Grounding DINO teve **precisão de 8 % a 18 %** nos contentores, contra **81 %** do detetor RF-DETR treinado com as nossas anotações. Por isso a pipeline usa RF-DETR treinados.

## O que NÃO está medido
- A comparação não foi repetida com outros limiares nem noutras cidades.

## Como correr
```bash
pip install torch transformers pillow
python demo_grounding_dino/preanotar_grounding_dino.py --imagens demo_grounding_dino/imagens --out preanotado --overlay overlay
```
O modelo (~690 MB) descarrega-se do Hugging Face na primeira utilização. Imagens: «© colaboradores do Mapillary, CC BY-SA 4.0».
