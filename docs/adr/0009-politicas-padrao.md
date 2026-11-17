# ADR-0009: políticas padrão das consultas

- Status: proposto (os valores marcados com * dependem de Q5 e Q6 em [open-questions.md](../open-questions.md))
- Data: 2026-11-17

## Decisão

| Tema | Padrão | Origem | Como a skill trata |
|---|---|---|---|
| Confiabilidade | Pesquisa com Data Quality ligado e credencial sem `analytics:reliability`: só `reliable = TRUE`. Caso contrário: todas | Mesma regra das telas (`results_controller.rb:305-313`) e do Data Chat (`session.rb:61-65`) | Declara a política quando o envelope trouxer `reliable_only` |
| Incompletas | Incluídas | Telas incluem por padrão (`evaluations_filter.rb:48`) | Só filtra `completed_only` se o usuário pedir; declara |
| Período sem data | A API exige período. A skill usa os últimos 90 dias até hoje* e declara | Data Chat usa 90 dias (`period.rb:10`) | Diz "nos últimos 90 dias (de X a Y)" |
| "Hoje" | Data atual em `America/Sao_Paulo`* | Cota do Data Chat usa SP; as telas usam UTC no eixo temporal | O envelope traz as datas efetivas |
| Amostra pequena | Aviso `small_sample` quando `n < 30`*; não oculta o valor | O sistema não tem mínimo (`minimum_answers = 0`) | Mostra o valor com a ressalva; não ranqueia unidades com aviso sem dizer |
| Semana | Começa na segunda (ISO) | `periodic_time_axis.rb:16-21` | — |
| Arredondamento | NPS inteiro (meio para longe do zero); média com casas por amplitude da escala (<10 → 2, <100 → 1, senão 0); percentuais com 1 casa | `utils.rb:10-12`, `question.rb:323-335`, Data Chat | Usa o `display` do envelope, sem rearredondar |
| Unidades desabilitadas | Entram se tiverem avaliações no período | Data Chat `evaluations_by_unit` | — |
| Pesquisas arquivadas | Entram nas consultas; aparecem marcadas em `list_surveys` | API v1 atual inclui arquivadas | Avisa quando a pesquisa está arquivada |

Os valores com * viram configuração por cliente se houver pedido.
