# Demonstração de pré-anotação (Grounding DINO) — só para mostrar, fora da pipeline

O **Grounding DINO Tiny** (IDEA-Research, Apache-2.0) deteta objetos a partir de **texto**, sem treino: escreve-se «recycling container.» e ele propõe caixas. Esta pasta existe **só para mostrar como fica uma pré-anotação** (caixas propostas por texto, prontas a importar no CVAT para um humano corrigir). Nada mais.
**Não faz parte da pipeline** (a pipeline usa RF-DETR treinados com as nossas imagens) e **não vai nos pesos**: o modelo (~690 MB) descarrega-se do Hugging Face na primeira utilização.

## Correr
```bash
pip install torch transformers pillow                      # GPU opcional
python preanotar_grounding_dino.py --imagens imagens --out preanotado --overlay overlay
python preanotar_grounding_dino.py --imagens imagens --solucoes descritivo --box-thr 0.4 --out outra_pasta     # uma só solução, outro limiar
```
Cada solução escreve `preanotado/<solução>/instances_default.json` (COCO 1.0, **importável no CVAT**) e, com `--overlay`, as imagens com as caixas desenhadas em `overlay/<solução>/`.

## Os resultados que já estão aqui
8 imagens de exemplo (`imagens/`: do Porto, já **anonimizadas**; 3 com subterrâneo, 3 com contentor, 2 sem nenhum). Nestas 8 imagens as anotações finais têm **21 caixas reais** (12 contentores, 9 subterrâneos). O que cada solução propôs (limiares 0,30 / 0,25):

| Solução | Frases | Caixas propostas | Classes que devolve |
|---|---|---|---|
| `simples` | «trash bin», «recycling container» | 13 | só contentor |
| `descritivo` | 5 frases de contentor com cor e material + «an underground waste container» | 33 | contentor 27, subterrâneo 6 |
| `por_classe` | as mesmas, uma classe de cada vez | 45 | contentor 30, subterrâneo 15 |

Abre `overlay/<solução>/` para ver. O padrão que se repete:
- **Mais frases, mais caixas, mais falsos positivos** (bancos, caixotes de rua, caixas de eletricidade, portas). A solução `por_classe` propõe mais do dobro das caixas reais.
- **Distingue mal contentor de subterrâneo**: a classe vem da frase que produziu a caixa, e o modelo não sabe a diferença real; usa-se como sugestão.
- **Nenhuma serve sem revisão humana.** O fluxo útil é: correr, importar no CVAT, apagar o que está a mais, corrigir a classe, acrescentar o que falta.

## Licenças
Modelo e código: Apache-2.0. Imagens: «© colaboradores do Mapillary, CC BY-SA 4.0» (ver `imagens/ATRIBUICAO.txt`).
