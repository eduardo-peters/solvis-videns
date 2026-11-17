# Tipos de pergunta

O sistema tem 12 tipos (`answer_type`). O tipo decide quais métricas existem para a pergunta.

| `answer_type` | O que é | Métricas | Observações |
|---|---|---|---|
| `NPS` | Nota de 0 a 10 de recomendação | `nps`, `response_count` | Promotores 9-10, neutros 7-8, detratores 0-6. Pode haver zona de referência |
| `Scale` | Escala de alternativas com valor numérico (ícones, estrelas, 1 a 5, 0 a 10...) | `scale_mean` ou `weighted_sum` (conforme `metric_kind`), `choice_share`, `response_count` | O número vem do `value` da alternativa. Alternativas sem valor ("Não se aplica") ficam fora da média |
| `Multiple Choice` | Escolha única | `choice_share`, `response_count` | Alternativas não têm valor numérico. "Outro: ___" conta como alternativa; o texto vai para comentários |
| `Multiple Response` | Várias alternativas | `multi_response_share`, `response_count` | Porcentagens somam mais de 100% |
| `Text` | Comentário longo (até 1.000 caracteres) | `response_count`, comentários, `theme_mentions` | Único tipo analisado pelo Radar de Comentários |
| `Short Text` | Texto curto (até 255) | `response_count`, comentários | Não analisado pelo Radar |
| `Numeric` | Número digitado (só dígitos, vírgula e ponto) | `response_count` | Sem média: o valor é guardado como texto, com vírgula ou ponto |
| `Email`, `Phone`, `CPF`, `CNPJ` | Dados de contato e documento | `response_count` | Dado pessoal. Nunca sai como comentário |
| `Date` | Data digitada (dia/mês com 1 ou 2 dígitos, separador `/`, `-` ou espaço, ano com 2 ou 4 dígitos) | `response_count` | — |

## Opções de pergunta que mudam a leitura

| Opção | Efeito |
|---|---|
| `metric_kind = weighted_sum` (Scale) | Indicador vira `weighted_sum` (100 × média), em geral lido como % |
| `reference_zone` (NPS) | `none` esconde zonas; `with_enchantment` acrescenta a Zona de Encantamento (91-100) |
| `lgpd_protected` | Respostas individuais só com escopo `analytics:lgpd`. Métricas agregadas continuam disponíveis |
| `mandatory` | Pergunta aberta ou de múltipla resposta obrigatória (na múltipla resposta, força ao menos uma alternativa) |
| `choices_ordering = random` ou `random_with_last_fixed` | Ordem de exibição aleatória (a segunda mantém a última alternativa fixa); a distribuição vem ordenada por contagem |

## Como ler o questionário

`get_questionnaire` devolve, por pergunta: `id`, `number` (como o respondente viu), `text`, `answer_type`, `metric_kind`, `scale_min`/`scale_max`, `lgpd_protected`, alternativas (`id`, `letter`, `text`, `value`, `is_valueless`) e um resumo dos desvios ("se respondeu a → vai para 5").

Desvios explicam por que uma pergunta tem n menor: só quem escolheu determinada alternativa chega até ela. Diga isso quando o n de uma pergunta for bem menor que o da anterior.
