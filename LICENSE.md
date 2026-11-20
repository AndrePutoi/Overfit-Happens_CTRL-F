# Licença e propriedade intelectual

## Código do CTRL+F

**Âmbito:** todo este repositório (a pipeline em `src/`, a interface em `interface/`, os testes e a documentação), exceto os dados e os componentes de terceiros da secção seguinte.

Este projeto foi desenvolvido no Aveiro Tech City Hackathon 2026 (desafio #2, Câmara Municipal de Aveiro e Universidade de Aveiro).

As Normas de Participação do hackathon (artigo 22.º, n.º 3) definem que a propriedade intelectual dos projetos é atribuída às entidades que apresentaram os desafios, para facultar o livre acesso de uso e adaptação, sem objetivos comerciais, mas com obrigação de partilha, a todos os interessados na sua aplicação.

Em conformidade:

- qualquer entidade pública ou pessoa interessada pode usar, estudar e adaptar este código;
- as versões adaptadas devem ser partilhadas nas mesmas condições;
- não é permitido o uso com objetivos comerciais.

**A confirmar com a organização:** a licença formal a aplicar ao repositório. Sugestão da equipa: a Licença Pública da União Europeia (EUPL-1.2, https://interoperable-europe.ec.europa.eu/collection/eupl), pensada para administrações públicas e com versão oficial em português, que garante a obrigação de partilha das versões adaptadas. A restrição a usos não comerciais das Normas teria de ficar num aditamento, porque a EUPL não a prevê.

**Alternativa também considerada:** CC BY-NC-SA 4.0, que cobre as duas condições das Normas (não comercial e partilha nas mesmas condições) numa só licença, mas que a Creative Commons desaconselha para software (não tem cláusula de patentes) e que não é uma licença «open source» no sentido da OSI. Não existe uma licença de software padrão que seja ao mesmo tempo não comercial e de partilha igual.

**Enquanto isto não estiver confirmado, não está concedida nenhuma licença formal.** A decisão cabe à entidade que lançou o desafio e à organização; a entrega do código é opcional (Normas, art. 14.º).

## Dados e componentes de terceiros

Cada um mantém a sua própria licença:

| Componente | Licença | Obrigação |
| --- | --- | --- |
| Imagens do Mapillary | CC BY-SA 4.0 | Atribuição e partilha nas mesmas condições (feitas na aplicação e nas exportações) |
| OpenStreetMap (mapa de fundo, ruas) | ODbL | Atribuição "© colaboradores do OpenStreetMap" (feita no mapa) |
| Leaflet | BSD-2-Clause | Manter o aviso de copyright |
| React, Vite, FastAPI | MIT | Manter o aviso de copyright |
| PostgreSQL, PostGIS, pgvector | PostgreSQL License / GPL-2.0 (PostGIS) | Usados como serviços, sem alterações |
| Modelos da pipeline: RF-DETR, DINOv2, Depth Anything V2 Small, EfficientLoFTR, Grounding DINO Tiny | Apache-2.0 | Manter o aviso de licença |
| CLIP ViT-B/32, YuNet | MIT (a confirmar) | Manter o aviso de licença |
| **MTSD** (dados com que se treinou o detetor e o classificador de sinais) | **CC BY-NC-SA** | Os pesos de sinais herdam o **uso não comercial** e a partilha nas mesmas condições |
| Open Images (privacidade: rostos e matrículas) | imagens CC BY 2.0; anotações CC BY 4.0 (a confirmar) | Atribuição aos autores (`licencas/oi_atribuicoes.csv`, dentro do zip de pesos) |
| Ultralytics / YOLO (backend de privacidade opcional) | AGPL-3.0 | Fora dos requisitos por omissão; para uso fechado ou comercial exige licença própria |
| CVAT (ferramenta de anotação externa) | MIT | Não está neste repositório; só usamos as exportações |
| **Pesos dos modelos** (zip à parte) | **Uso de investigação / não comercial** | Ver `docs/15_licencas_e_riscos.md` |

O Google Street View não é usado: os termos do Google Maps Platform não permitem guardar as imagens, treinar modelos com elas nem mostrá-las sobre um mapa que não seja da Google.
