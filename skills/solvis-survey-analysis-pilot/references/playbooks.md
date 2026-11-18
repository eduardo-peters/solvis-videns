# Playbooks de análise

Receitas para os pedidos mais comuns. Cada passo é um comando do motor (`python3 scripts/solvis.py ...`); a resposta final segue `answer-format.md`. Os padrões vêm do roteamento do Data Chat da Solvis.

Antes de qualquer playbook: `scope` (uma vez por conversa), resolver nomes com `resolve` e ler `questionnaire` da pesquisa.

## 1. Panorama / fechamento de um período

Pedido: "como foi outubro?", "resumo do trimestre", "me dá os indicadores".

1. `query --metric evaluation_count --survey S --period P`
2. `query --metric nps --survey S --question <NPS> --period P --compare-with previous_period`. Com mais de uma pergunta NPS, uma consulta por pergunta, cada uma apresentada separada
3. `query --metric scale_mean --survey S --question <escalas principais> --period P` (se forem muitas, pergunte quais importam ou use as 3 primeiras e diga isso)
4. `query --metric tag_mentions --survey S --period P` e `comments --survey S --period P --limit 10`

Resposta: uma frase por bloco (volume, NPS, notas, o que disseram). Sem conclusões que os números não sustentem.

## 2. Por que o NPS caiu (ou subiu)

1. `query --metric nps ... --compare-with previous_period|previous_year`: confirma a variação
2. `query --metric nps ... --compare-with ... --group-by unit --order delta:asc --min-n 10 --limit 10`: onde caiu. Linhas com `only_in_comparison` são unidades que pararam de responder; mencione-as se forem relevantes
3. `query --metric tag_mentions --survey S --period P --nps-group detractor --compare-with ...`: assuntos marcados nos comentários dos detratores
4. `comments --survey S --period P --nps-group detractor --limit 20`: trechos

Resposta em texto corrido, nesta ordem, em até 8 frases (não use o modelo de relatório):
1. A variação com os dois NPS, os n e as datas.
2. Onde se concentra: a primeira linha do passo 2 com amostra suficiente. Se todas tiverem `small_sample`, diga que nenhuma unidade tem amostra para concluir. Diga se veio de menos promotores ou de mais detratores, pelas porcentagens (`delta.promoters_pct_display`, `delta.detractors_pct_display`), nunca pelas contagens.
3. As 2 ou 3 tags mais marcadas entre detratores, com número e porcentagem, e um trecho curto.
4. O que vale investigar primeiro.

Apresente tags como o que foi marcado nos comentários, não como causa provada. Com `no_tags`, use só os trechos e diga que não há classificação de temas.

## 3. Ranking de unidades

1. `query --metric <métrica> ... --group-by unit --order value:asc|desc --limit 10`
2. Se houver `small_sample`, rode de novo com `--min-n 30` ou diga quais posições têm amostra pequena.

Resposta: a primeira linha é a resposta; as demais são contexto. Cite o n de cada unidade mencionada. Volume por unidade é `evaluation_count`, não a métrica de nota.

## 4. Evolução mês a mês

1. `query --metric <métrica> ... --group-by month --period this_year|last_year` (ou `--start`/`--end`)

Resposta: valor do primeiro e do último mês e onde fica a maior variação entre dois meses seguidos. Para a variação entre meses, peça a comparação (`--compare-with previous_year` mostra cada mês contra o mesmo mês do ano anterior) ou consulte os dois meses com `--period month:AAAA-MM --compare-with previous_period`; não subtraia. Se o último mês estiver em andamento (`bucket.in_progress`), diga isso. Não projete.

## 5. Comparação entre períodos

1. Uma única consulta com `--compare-with`. Nunca duas consultas com datas calculadas.

Resposta: valor de cada período, n de cada um e `delta.display`.

## 6. Regionais, bandeiras ou outro atributo de unidade

1. `units --properties` ou `resolve --kind property --text regional` → id do nome
2. `query --metric <métrica> ... --group-by unit_property:<id>`

Resposta: cada valor é o agregado das unidades que hoje têm aquele valor. Para período antigo, avise que lojas que mudaram de regional aparecem na regional atual.

## 7. Distribuição de uma pergunta de escolha

1. `questionnaire` para confirmar o tipo
2. `query --metric choice_share|multi_response_share --question Q ...`

Resposta: porcentagens com vírgula decimal e o n. Em múltipla resposta, diga que somam mais de 100%.

## 8. "Qual é o nosso CSAT?" (top-2-box, % satisfeitos)

1. Liste as perguntas de escala da pesquisa (número, texto, escala) e pergunte qual é o CSAT do cliente e quais alternativas contam como "satisfeito". Não calcule a média de todas as escalas.
2. Com a resposta: se `metric_kind = weighted_sum`, use `weighted_sum`; senão, `choice_set_share --choices <ids das alternativas "satisfeito">`, ou `scale_mean` se o usuário quiser a média.
3. Declare: "O sistema não tem uma métrica chamada CSAT; usei <métrica> da pergunta <n>, <texto>, com as alternativas <...>".

## 9. O que os clientes estão dizendo

1. `query --metric tag_mentions --survey S --period P`
2. `comments --survey S --period P --limit 20` (com `--tag <id>` para ver trechos de uma tag, ou `--contains <palavra>`)

Resposta: tags com contagem e %, a parte dos comentários com tag (`tagged_share_display`), 1 a 3 trechos curtos. Contagem de comentários vem de `total_matching` ou `tag_mentions`, nunca de contar a amostra. Em pesquisa sem Data Quality, avaliações repetidas (mesmo texto em minutos) não são removidas; se aparecerem na amostra, diga que podem inflar as contagens.

## 10. Confiabilidade dos dados

1. `query --metric data_quality_summary --survey S --period P [--group-by unit]`

Resposta: confiáveis, reprovadas, não verificadas. "Reprovada" quer dizer que regras automáticas apontaram padrão suspeito, não que houve fraude comprovada. Quais regras falharam não está disponível nesta versão.

## 11. Horários e dias

1. `query --metric <métrica> ... --group-by hour_block` (ou `hour_block:3`, `day_of_week`)

Resposta: horários na hora local da unidade.

## 12. Qual pesquisa teve mais avaliações

1. `surveys --active-in <preset>` lista as pesquisas com avaliação no período.
2. Uma `query --metric evaluation_count --survey <id> --period <preset>` por pesquisa da lista. Com mais de 10 pesquisas, avise que a primeira vez demora (o motor baixa cada uma) ou pergunte quais interessam.

Não use `evaluation_count_all_time` do `scope`: é o histórico inteiro, em cache, e pode estar defasado.
