# Glossário

Termos que o usuário pode usar e o conceito do modelo a que correspondem.

| O usuário diz | Conceito no modelo | Observação |
|---|---|---|
| loja, filial, ponto, agência, restaurante, praça, unidade, PDV | `unit` | |
| regional, bandeira, região, formato, cluster | `unit_property` (nome) e seus valores | Confirme o nome da propriedade com `list_units` / `resolve_entities` |
| pesquisa, questionário, survey | `survey` | Questionário é a estrutura de perguntas da pesquisa |
| pergunta, questão, item, Q3, "a 3" | `question` | Número = como o respondente viu |
| avaliação, resposta (no sentido de "quantas respostas tivemos") | `evaluation_count` | Confirme se é respondentes ou respostas a uma pergunta |
| nota, satisfação, média, estrelas, carinhas | `scale_mean` (ou `weighted_sum`) | Diga a escala |
| recomendação, NPS, promotores, detratores, neutros, passivos | `nps` | "Passivos" = neutros |
| CSAT, top-2-box, % satisfeitos | Não existe como métrica. Mapear para `scale_mean`, `weighted_sum` ou `choice_share` da pergunta indicada; a partir da fase 3, `choice_set_share` | Declarar o mapeamento |
| comentários, elogios, reclamações, sugestões, o que disseram | `search_comments` | |
| temas, assuntos, motivos, categorias de reclamação | `theme_mentions` (Radar) | |
| tom, sentimento do texto | `comment_tone` | Tom do texto |
| promotores que reclamaram, detratores que elogiaram | `author_nps_group` + `comment_tone` | Grupo de quem escreveu ≠ tom do texto |
| confiáveis, reprovadas, suspeitas, fraude, avaliações inválidas | `reliability` / `data_quality_summary` | Exige escopo `analytics:reliability` |
| incompletas, abandonadas, parciais | `completion = incomplete` | Não chamar de taxa de abandono |
| totem, tablet, presencial | `channel = device` | |
| link, QR code, online, e-mail, WhatsApp | `channel = web` | |
| turno, manhã/tarde/noite | `shift` (se cadastrado) ou `hour_block` | |
| mês a mês, evolução, tendência, série | `time_bucket` | "Tendência" = descrever a série, não projetar |
| comparar com o ano passado, mesmo período do ano anterior | `compare_with = previous_year` | |
| comparar com o mês anterior, período anterior | `compare_with = previous_period` | |
| zona de excelência/qualidade/crítica | `reference_zone` do NPS | |
| GUT, gravidade/urgência/tendência, prioridade | GUT do Radar em `search_comments` | Só comentários negativos |

## Termos do sistema

| Termo | Definição |
|---|---|
| Radar de Comentários | Classificador por LLM que lê comentários do tipo Text e atribui tom, até 3 temas, resumo, sugestão e matriz GUT (negativos) |
| Data Quality | Motor de regras que marca avaliações como confiáveis ou não (intervalo curto entre avaliações, duração curta, comentários repetidos etc.) |
| Espelho | Cópia analítica dos dados de resultados. Pode ter algumas horas de atraso, declarado em `freshness` |
| Zona de referência | Faixa qualitativa do NPS: Crítica (≤ 0), Aperfeiçoamento (1-50), Qualidade (51-75), Excelência (76-100 ou 76-90), Encantamento (91-100, quando habilitada) |
