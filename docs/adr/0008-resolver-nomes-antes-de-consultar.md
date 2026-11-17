# ADR-0008: nomes viram ids num passo explícito, antes da consulta

- Status: proposto
- Data: 2026-11-17

## Contexto

O Data Chat aceita nomes no próprio parâmetro da consulta e casa por substring sem acento: "centro" pega todas as unidades que contêm a palavra, silenciosamente. Para uma LLM externa isso é a principal fonte de cruzamento errado ("NPS da loja Centro" vira NPS de três lojas).

## Decisão

1. Endpoints de métrica aceitam só ids (`survey_id`, `question_id`, `unit_ids`, `choice_ids`, `tag_ids`, `property_value_ids`).
2. `POST /resolve` recebe texto e devolve candidatos com id, nome, tipo de casamento (`exact`, `prefix`, `contains`, `number`) e contexto (cidade/UF da unidade, pesquisa da pergunta).
3. A skill usa o candidato `exact` único. Se houver mais de um candidato e nenhum exato, pergunta ao usuário ou declara a escolha na resposta.
4. A API recusa ids fora do escopo com 404 indistinguível de "não existe", para não revelar ids de outros clientes.

## Consequências

- Uma chamada a mais por pergunta. Compensa pela redução de erro.
- O casamento continua no servidor (mesmo `Resolver` do Data Chat, com saída de candidatos em vez de união).
