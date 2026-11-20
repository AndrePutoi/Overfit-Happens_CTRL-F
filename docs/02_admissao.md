# 02 · Admissão (etapa 3)

## Problema
Rejeitar, **antes** do passo mais caro (a anonimização), as imagens que não servem: sem posição, ilegíveis, demasiado desfocadas, escuras, etc.

## Desenho e porquê
- **Posição obrigatória** (do metadado ou do EXIF): sem ela não se pode georreferenciar nada. O **rumo** não é obrigatório: sem rumo a imagem é aprovada **com aviso** e marcada `geolocalizavel=false` (serve para detetar, não para localizar). **Nunca se inventa um rumo.**
- **Rejeita:** sem posição, posição inválida (fora do intervalo, ou 0,0), ficheiro ilegível, resolução baixa, duplicada, desfocada, escura, sobreexposta, tapada (contraste mínimo), saturada.
- **Avisa:** sem rumo, sem data, pouco nítida, fora da zona, sem licença.
- Limiares em `configs/admissao.yaml`: lado menor ≥ 480 px (planas) ou largura ≥ 2 000 px (panoramas); desfoque rejeitar a 0,40 (aviso a 0,36); brilho entre 30 e 220; contraste ≥ 14; saturação ≤ 35 % (alta) e ≤ 50 % (baixa).
- **Desfoque medido pelo método de Crété (2007)**, a 800 px de largura e na faixa central da imagem.
- Porque antes da privacidade: anonimizar custa cerca de **1,3 s por vista** segundo o código, e não vale a pena gastar isso em imagens que vão ser rejeitadas.

## Alternativas que rejeitámos
- **Variância do Laplaciano para o desfoque**: mede textura, não nitidez; dava 14 a 60 em fachadas lisas e nítidas e condenava-as. Por isso usamos Crété.

## Resultados medidos
Calibração nas **1 824 vistas de Aveiro** (`configs/admissao.yaml`): o índice de desfoque dos originais fica entre 0,19 e 0,34 (percentis 1 a 99; máximo 0,45); com o limiar 0,40 **rejeitam-se 2 das 1 824 (0,11 %)**. Com desfoque sintético, um desfoque gaussiano de σ = 1,5 dá ~0,48, movimento ~0,56 e σ = 2,5 ~0,65, ou seja, todos acima do limiar.

## Resultados esperados (hipóteses)
- Em zonas com outra câmara ou outras condições de luz, os limiares podem precisar de recalibração.

## O que NÃO está medido
- Quantos objetos úteis se perdem por rejeição (só medimos a taxa de rejeição sobre Aveiro, não o impacto na deteção).
- Os limiares foram calibrados só em Aveiro.

## Falhas conhecidas
- Se **todas** as vistas forem rejeitadas, a etapa falha explicitamente.
- A zona `--zona` só avisa «fora da zona» para as caixas definidas em `configs/admissao.yaml` (Aveiro, Porto, Lisboa).

## Como correr e testar
```bash
python -m ctrlf.ingest.admissao data/raw/aveiro_piloto_vistas                 # relatório, não altera nada
python -m ctrlf.ingest.admissao data/raw/aveiro_piloto_vistas --aplicar       # move as rejeitadas para _rejeitadas/
python tests/unit/14_test_admissao.py
```
