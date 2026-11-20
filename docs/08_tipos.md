# 08 · Tipo do contentor (etapa 9)

## Problema
Para cada contentor ou subterrâneo, sugerir o **tipo de resíduo**: `indiferenciado`, `papel`, `embalagens` ou `vidro`. Serve para dar tipo às **ilhas** de reciclagem.

## Desenho e porquê (`ctrlf/scripts/tipar_residuos_catalogo.py`)
- **DINOv2-small** com cabeça de 4 classes, sobre o recorte da caixa (margem de 8 %), com **imagens sempre anonimizadas** (sha256 do manifesto).
- **Treinado só com as anotações do Porto** feitas pela equipa (**627 recortes em 199 imagens**: 387 indiferenciado, 102 embalagens, 79 papel, 59 vidro), sem o dataset `waste_container`, cuja origem e licença estão por verificar e que é de outro domínio (caixotes fotografados de perto).
- **Amostragem equilibrada por época** em vez de pesos de classe, aumentos fortes de imagem e backbone congelado na 1.ª época.
- **Validação cruzada por panorama** (5 dobras): as quatro vistas do mesmo local nunca ficam em lados diferentes.
- O tipo é uma **sugestão** (`subclass_source = "modelo"`) até um humano o corrigir. A papeleira não leva tipo (é `indiferenciado` por regra).

## Alternativas que rejeitámos
- **Usar o `waste_container`**: licença e domínio (ver acima).
- **Pesos de classe e amostragem equilibrada ao mesmo tempo**: compensar o desequilíbrio **duas vezes** fez o modelo deixar de prever o tipo mais frequente (exatidão de 16 %, abaixo do acaso). Ficou só a amostragem equilibrada.
- **Confiar numa estimativa antiga de «~40 %»**: vinha de apenas 43 exemplos e era ruído.

## Resultados medidos (`resultados/fluxo4_porto_cv20.json`)
Validação cruzada por panorama, 20 épocas, n = 627:

| | |
|---|---|
| Exatidão | **63,2 %** |
| Exatidão equilibrada | **62,6 %** (acaso: 25 %) |
| Recolha por classe | embalagens 72,5 % · indiferenciado 63,0 % · vidro 62,7 % · **papel 51,9 %** |

A classe maioritária (indiferenciado) vale 61,7 % dos recortes, por isso **a exatidão simples engana**: a métrica a citar é a equilibrada. Muitos «indiferenciado» são previstos como papel (66 de 387) ou como embalagens (52). Com 10 épocas (`fluxo4_porto_cv.json`) a exatidão era 51,8 % (equilibrada 47,3 %).

## Resultados esperados (hipóteses)
- Em imagens de outras cidades o desempenho deve ser pior (só vimos o Porto).

## O que NÃO está medido
- ⚠ **A exatidão do tipo em Aveiro** (e em qualquer outra cidade).
- O **viés de ancoragem** nas etiquetas do Porto (anotar sobre uma sugestão tende a confirmá-la), que pode inflacionar a exatidão; não o quantificámos.

## Falhas conhecidas
- O **papel** é a classe mais fraca (52 %).
- Com poucos dados (627 recortes) o resultado é sensível à divisão por panorama.

## Como correr e testar
```bash
python -m ctrlf.scripts.tipar_residuos_catalogo aveiro_piloto --clf $UMS_MODELS_DIR/classificador_fluxo4.pt
python -m ctrlf.treino.train_fluxo4_porto cv --porto-dir data/crops/fluxo4/porto_final      # só para treinar (capítulo 13)
```
