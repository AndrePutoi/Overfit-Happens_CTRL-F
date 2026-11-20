# 03 · Privacidade (etapa 4): o portão

## Problema
Garantir que **nenhum modelo de deteção, e nada a jusante, vê rostos ou matrículas legíveis**, e que isso se pode **verificar**.

## Desenho e porquê
- **Dois mecanismos correm sempre:** rostos e matrículas, com detetores RF-DETR Small (Apache-2.0) treinados no **Open Images** (capítulo 13). A área detetada é desfocada.
- **Portão de falha fechada** (`ctrlf/privacy/gate.py`): não existe parâmetro para saltar o desfoque. Se faltar um modelo, levanta `PrivacyConfigError` e o detetor nem arranca.
- **Cache verificada** (`ctrlf/privacy/anon_cache.py`): cada imagem anonimizada guarda-se uma vez, com o mesmo nome da origem, e só é aceite como «já anonimizada» se existir no manifesto `data/images_anon/manifest.jsonl` **com o mesmo sha256** do ficheiro guardado, da origem e dos parâmetros de privacidade. Se qualquer coisa mudar (origem, ficheiro, modelos, limiares), reanonimiza a partir da origem.
- **A etapa `privacidade` é um portão no orquestrador:** confirma, vista a vista, que a imagem anonimizada existe no manifesto com o sha256 certo; se falhar, **nada a jusante corre**.
- Dois modos de desfoque: `faces-plates` (omissão: só rostos e matrículas) e `strict` (também a caixa inteira de pessoas e veículos).
- Para o detetor de pessoas e veículos do modo `strict`, reutiliza-se o RF-DETR COCO dos bancos (via adaptador `privacy/rfdetr_boxes.py`).

### O que «verificado» quer dizer (e o que não quer)
- **Verifica a integridade, não a qualidade do desfoque.** O portão confirma que (1) a imagem anonimizada existe, (2) o seu sha256 coincide com o do manifesto, e (3) o manifesto foi gerado a partir da **mesma origem** e dos **mesmos parâmetros e modelos**. Assim, nenhum modelo vê uma imagem que não passou pelo anonimizador, nem uma que foi editada depois.
- **Não verifica que todos os rostos e matrículas foram apanhados.** Isso depende da taxa de deteção do modelo (~90 % nos rostos, ~43 % nas matrículas no nosso teste). Uma imagem pode estar «verificada» e ter uma matrícula legível.
- Medir a qualidade exige uma **auditoria** (contar à mão o que escapa numa amostra). **Foi feita por um colega da equipa, com resultado satisfatório** (relato da equipa; os números não estão registados neste repositório).

## Alternativas que rejeitámos
- **YOLO (Ultralytics) como omissão:** é AGPL-3.0, o que complica a distribuição. Fica como backend opcional (`UMS_PRIVACY_BACKEND=yolo`, com `requirements-yolo-opcional.txt` e pesos por conta própria).
- **Modo `strict` por omissão:** mais seguro, mas desfoca blocos grandes que os detetores confundem com contentores.

## Resultados medidos
Teste em **Open Images** (300 imagens positivas; `resultados/privacidade_rfdetr_oi.json` e `privacidade_yolo_oi.json`):

| | Rostos (891) | Matrículas (413) |
|---|---|---|
| **RF-DETR** (omissão): taxa de deteção | **90,2 %** | **42,9 %** |
| YOLO: taxa de deteção | 90,2 % | 37,5 % |
| RF-DETR matrículas por tamanho | | <16 px: 72 %; 16 a 40 px: 60 %; **>40 px: 27 %** |
| Falsos positivos por imagem sem o alvo (RF-DETR) | 0,65 | 0,28 |

**Concordância em Aveiro** (150 vistas, `resultados/privacidade_concordancia_aveiro_resumo.json`; é **concordância, não exatidão**): nos **rostos** os dois detetores coincidem (o RF-DETR cobre 89 % das caixas do YOLO e o YOLO 95,5 % das do RF-DETR); nas **matrículas quase não coincidem** (69 caixas do YOLO contra 29 do RF-DETR; o RF-DETR cobre só 7,2 % das caixas do YOLO).

## Resultados esperados (hipóteses)
- Os rostos ficam bem protegidos em imagens como as do teste.
- No teste do Open Images as matrículas escapam com frequência (43 % de taxa de deteção). **Em Aveiro o resultado pode ser melhor**: nas vistas de rua as matrículas são pequenas e o modelo deteta melhor as pequenas (72 % abaixo de 16 px); a auditoria do colega vai nesse sentido, mas sem números não o afirmamos.

## O que NÃO está medido
- **Os números da auditoria em Aveiro**: um colega da equipa auditou o desfoque das vistas de Aveiro e o resultado foi satisfatório, mas **a amostra e as contagens (quantas imagens, quantas matrículas e rostos escaparam) não estão registadas aqui**. Convém registá-las antes de citar o resultado.
- O teste do Open Images tem um domínio diferente das vistas do Mapillary (matrículas maiores e fotografadas de perto: a taxa por tamanho mostra que o modelo é pior nas grandes).
- Numa repetição posterior do mesmo anonimizador antigo sobre as mesmas imagens, a contagem de matrículas por imagem foi inferior à da primeira corrida; **não conseguimos explicar a diferença**.

## Falhas conhecidas
- **Matrículas não protegidas** (ver acima): não publique imagens sem rever esta limitação.
- O portão pára a pipeline quando falha; **não o contorne**: refaça a etapa (`--refazer privacidade`).

## Como correr e testar
```bash
python -m ctrlf.privacy.anon_cache data/raw/aveiro_piloto_vistas      # enche a cache e o manifesto
python tests/unit/21_test_privacy_rfdetr.py
```
**Melhorias propostas (não implementadas):** combinar os dois detetores (união das caixas), baixar o limiar das matrículas e repetir a auditoria com uma amostra registada.
