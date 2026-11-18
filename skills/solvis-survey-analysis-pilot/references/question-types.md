# Tipos de pergunta

O sistema tem 12 tipos (`answer_type`). O tipo decide quais métricas existem para a pergunta.

| `answer_type` | O que é | Métricas | Observações |
|---|---|---|---|
| `NPS` | Nota de 0 a 10 de recomendação | `nps`, `response_count` | Promotores 9-10, neutros 7-8, detratores 0-6 |
| `Scale` | Escala de alternativas com valor (carinhas, estrelas, 1 a 5, 0 a 100...) | `scale_mean` ou `weighted_sum` (conforme `metric_kind`), `choice_share`, `choice_set_share`, `response_count` | O número vem do `value` da alternativa. Alternativas sem valor (`is_valueless`, ex.: "Não se aplica") ficam fora da média |
| `Multiple Choice` | Escolha única | `choice_share`, `choice_set_share`, `response_count` | Alternativas sem valor numérico. "Outro: ___" conta como alternativa; o texto sai em `comments` |
| `Multiple Response` | Várias alternativas | `multi_response_share`, `response_count` | Porcentagens somam mais de 100% |
| `Text` | Comentário longo | `response_count`, `comments`, `tag_mentions` | É o tipo que o Radar de Comentários classifica |
| `Short Text` | Texto curto | `response_count`, `comments` | Muitas vezes pede nome; o motor mascara contatos, não nomes |
| `Numeric` | Número digitado | `response_count` | Sem média: o valor nem é guardado pelo motor |
| `Email`, `Phone`, `CPF`, `CNPJ`, `Date` | Dados pessoais e datas | `response_count` | O motor guarda só que houve resposta; o conteúdo nunca sai |

## Opções de pergunta que mudam a leitura

| Opção (em `questionnaire`) | Efeito |
|---|---|
| `metric_kind = weighted_sum` (Scale) | Indicador vira `weighted_sum` (100 × média), em geral lido como %. `scale_mean` é recusado |
| `reference_zone` (NPS) | `none` esconde zonas; `with_enchantment` acrescenta a Zona de Encantamento (91-100) |
| `lgpd_protected: true` | O texto das respostas nunca é guardado nem exibido. Contagens e métricas continuam disponíveis |
| `mapping: ambiguous_text` | Outra pergunta tem o mesmo tipo e texto. A métrica pode ser recusada (`ambiguous_question_text`) |

## Como ler o questionário

`questionnaire --survey <id>` devolve, por pergunta: `id`, `number` (como o respondente viu hoje), `text`, `answer_type`, `metric` (a métrica principal do tipo; `weighted_sum` quando a escala é configurada assim), e, quando definidos, `metric_kind`, `scale_min`/`scale_max`, `lgpd_protected`, `reference_zone` e as alternativas (`id`, `letter`, `text`, `value`, `is_valueless`, `has_additional_field`). Campo ausente quer dizer o padrão: sem `metric_kind`, a escala é de média; sem `lgpd_protected`, a pergunta não é protegida.

O n de uma pergunta costuma ser menor que o da anterior: incompletas param no meio e desvios fazem só parte dos respondentes chegar a certas perguntas. Diga isso quando o n cair muito.

Pesquisas grandes costumam repetir blocos de perguntas para públicos diferentes (mesmo texto em posições diferentes). Cada pergunta é uma métrica separada; nunca some as gêmeas.
