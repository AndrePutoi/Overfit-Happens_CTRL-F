# 15 · Licenças e riscos

> Isto **não é aconselhamento jurídico**: é o que sabemos e o que ficou por verificar.

## Código
**Ainda não há licença formal.** O ficheiro [`LICENSE.md`](../LICENSE.md) tem a declaração da equipa: segundo as Normas de Participação do hackathon (art. 22.º, n.º 3), a propriedade intelectual dos projetos é atribuída à **entidade que apresentou o desafio**, para uso e adaptação **sem objetivos comerciais e com obrigação de partilha**. A licença formal está **por confirmar com a organização**: a proposta da equipa é a EUPL-1.2 com um aditamento de uso não comercial, e a alternativa considerada é a CC BY-NC-SA 4.0 (cobre as duas condições, mas não é pensada para software). **Antes de publicar, confirme por escrito com a entidade do desafio se pode escolher a licença e publicar o repositório.** A entrega do código é opcional (art. 14.º) e a organização pode divulgar as soluções durante 36 meses, só para divulgar a iniciativa (art. 23.º, n.º 3).

## Dados e modelos
| Componente | Licença / termos | Consequência |
|---|---|---|
| Imagens do Mapillary | CC BY-SA 4.0 | atribuição («© colaboradores do Mapillary») e partilha nas mesmas condições |
| OpenStreetMap | ODbL | atribuição; as bases derivadas mantêm a licença |
| Open Images (rostos e matrículas) | imagens CC BY 2.0 (16 115 verificadas); anotações CC BY 4.0 **por confirmar** | atribuição aos autores (`licencas/oi_atribuicoes.csv`) |
| **MTSD** (sinais) | **CC BY-NC-SA** | os pesos de sinais herdam o uso **não comercial** |
| `waste_container` (tipo antigo) | origem e termos **por verificar** | **não é usado** no modelo atual; assumir só investigação se se usar |
| RF-DETR, DINOv2, Depth Anything V2 Small, EfficientLoFTR, Grounding DINO Tiny | Apache-2.0 | permissiva |
| CLIP ViT-B/32, YuNet | MIT (por confirmar) | permissiva |
| Ultralytics (backend `yolo` opcional) | **AGPL-3.0** | fora dos requisitos por omissão; só se instalado de propósito |
| **CVAT** (ferramenta de anotação, **externa**: não está neste repositório) | MIT (o código; confirmado em fontes secundárias, falta ver o `LICENSE` oficial em `github.com/cvat-ai/cvat`) | só usamos as **exportações COCO** das nossas anotações. Se se usou o serviço alojado `cvat.ai` em vez de uma instalação própria, aplicam-se os **termos desse serviço**, que não verificámos |

**Os pesos são para investigação e uso não comercial.** O efeito da licença do Mapillary sobre os pesos treinados com as suas imagens está por esclarecer.

## Riscos
1. **Privacidade (o maior).** Rostos ~90 % protegidos e **matrículas ~43 %** no teste do Open Images; em Aveiro, uma auditoria visual feita por um colega da equipa teve resultado satisfatório (relato da equipa; os números não estão registados) (capítulo 03). Não publique imagens sem confirmar isto. Uma utilização real exigiria **avaliação de impacto** e melhorar a proteção das matrículas. A anonimização foi pensada para reduzir o risco; **não afirmamos conformidade com o RGPD**.
2. **Sem verdade-terreno em zonas novas.** Os detetores e o tipo foram medidos sobretudo no Porto; em Aveiro não há medição (capítulos 04 e 08).
3. **Posição aproximada** (ordem de 10 m, melhor com várias vistas) e só contra o OSM, cuja completude para mobiliário urbano **não está medida** (capítulo 07).
4. **O tipo do contentor é uma sugestão** (63 %).
5. **Dependência de serviços externos**: Mapillary e Overpass (limites, indisponibilidade, mudanças de licença).
6. **Reprodutibilidade parcial**: os dados de treino e as anotações não estão no repositório.
7. **Fusões automáticas** podem juntar objetos diferentes (no nível «provável», 1 em 80 sinais e 1 em 35 contentores na revisão humana); guardam `merged_from` para se poderem desfazer.
8. **Hardware**: uma GPU de 6 GB sujeita a calor; as corridas longas podem estrangular.
