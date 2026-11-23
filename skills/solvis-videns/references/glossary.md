# Glossário

Termos que o usuário pode usar e o conceito do modelo a que correspondem.

| O usuário diz | Conceito no modelo | Observação |
|---|---|---|
| loja, filial, ponto, agência, restaurante, praça, unidade, PDV | `unit` | |
| regional, bandeira, região, formato, cluster, tamanho da loja | `unit_property` e seus valores | `units --properties` ou `resolve --kind property` |
| estado, UF | `unit_state` | Cadastro atual da unidade |
| pesquisa, questionário, survey | `survey` | |
| pergunta, questão, item, Q3, "a 3" | `question` | Número = posição atual no questionário |
| avaliação, "quantas respostas tivemos" | `evaluation_count` | Se for sobre uma pergunta específica, `response_count` |
| nota, satisfação, média, estrelas, carinhas | `scale_mean` (ou `weighted_sum`) | Dizer a escala |
| recomendação, NPS, promotores, detratores, neutros, passivos | `nps` | "Passivos" = neutros |
| CSAT, top-2-box, % satisfeitos | Não existe como métrica. `choice_set_share` com as alternativas que o usuário considerar "satisfeito", ou `scale_mean`/`weighted_sum` | Declarar o mapeamento |
| comentários, elogios, reclamações, sugestões, o que disseram | `comments` | |
| temas, assuntos, motivos, categorias | `tag_mentions` | Tags de pessoas ou do Radar |
| tom, sentimento | Não disponível nesta versão | Oferecer tags e comentários |
| promotores que reclamaram, detratores que elogiaram | `--nps-group` + `comments` ou `tag_mentions` | Grupo de quem escreveu ≠ tom do texto |
| confiáveis, reprovadas, suspeitas, fraude | `reliability` / `data_quality_summary` | "Reprovada" não é fraude comprovada |
| incompletas, abandonadas, parciais | `completion = incomplete` | Não chamar de taxa de abandono |
| totem, tablet, presencial | `channel = device` | |
| link, QR code, online, e-mail, WhatsApp | `channel = web` | |
| manhã, tarde, noite, horário de pico | `hour_block` | Turno cadastrado não sai na API |
| dia da semana, fim de semana | `day_of_week` | |
| mês a mês, evolução, tendência, série | `--group-by month` (ou week, day, quarter) | "Tendência" = descrever a série, não projetar |
| comparar com o ano passado, mesmo período do ano anterior | `--compare-with previous_year` | |
| comparar com o mês anterior, período anterior | `--compare-with previous_period` | |
| zona de excelência/qualidade/crítica | `reference_zone` do NPS | Só quando a pergunta tem zona |

## Termos do sistema

| Termo | Definição |
|---|---|
| Radar de Comentários | Classificador por LLM da Solvis que lê comentários do tipo Text e aplica até 3 tags da lista do cliente. Nesta versão só as tags aplicadas chegam à skill |
| Data Quality | Motor de regras que marca avaliações como confiáveis ou reprovadas (intervalo curto entre avaliações, duração curta, comentários repetidos etc.) |
| Avaliação | Uma sessão de resposta a uma pesquisa, completa ou não. A mesma pessoa pode gerar várias |
| `eval_ref` | Id único da avaliação no sistema (o mesmo "Response ID" das exportações) |
| Zona de referência | Faixa qualitativa do NPS: Crítica (≤ 0), Aperfeiçoamento (1-50), Qualidade (51-75), Excelência (76-100 ou 76-90), Encantamento (91-100, quando habilitada) |
