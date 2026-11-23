# Changelog

## 0.2.0 (2026-11-23)

Primeira versão publicada.

- Motor local `scripts/solvis.py` (Python 3.9+, só biblioteca padrão) sobre a API pública V1: extração com cobertura por dia, normalização das respostas por id, cache SQLite por credencial, privacidade na ingestão (dados pessoais nunca guardados, comentários mascarados).
- Métricas: `evaluation_count`, `response_count`, `nps`, `scale_mean`, `weighted_sum`, `choice_share`, `choice_set_share`, `multi_response_share`, `tag_mentions`, `data_quality_summary`. Recortes por unidade, propriedade de unidade, UF, tempo, dia da semana, faixa de horário, canal, completude, confiabilidade, grupo NPS e alternativa.
- Envelope de evidência em toda consulta (`query_id`, n, período, filtros, políticas, cobertura, frescor, avisos) e comando `explain` para reabrir uma consulta.
- Testes com API falsa em `tests/pilot/`.
- Um cliente por pasta de trabalho: credencial, contexto, marca e cache ficam em `.solvis-videns/` dentro da pasta em que o host está rodando (`SOLVIS_WORKDIR` força outra), com `.gitignore` próprio; os relatórios gerados ficam na mesma pasta. `setup` e `scope` mostram `workdir`; `setup --username` com outro usuário na mesma pasta recusa com `client_mismatch` (`--replace-client` só com pedido explícito). Quem instalou antes refaz o primeiro uso na pasta do cliente.
- Produto batizado **Solvis Videns**; a skill passa a se chamar `solvis-videns` e é instalada a partir de https://github.com/eduardo-peters/solvis-videns.
- Primeiro uso completo pelo chat: credencial (`setup --username U --password -`, testada antes de gravar), mês inicial da análise, decisão do usuário sobre guardar o texto de perguntas protegidas por LGPD (`setup --lgpd-text on|off`) e descrição do cliente (`context`), tudo guardado na pasta de trabalho.
- Materiais com a cara do cliente: antes de relatório, deck ou página, a skill pede manual da marca, site, logo e modelos e guarda o perfil (`brand`). Atalhos `/lgpd`, `/contexto` e `/marca`.
- Validação antes da entrega: `validate --claims arquivo.json` confere cada afirmação de um material gerado (números, qualificadores, rankings, tendências, comparações, contagens de palavras, tags, citações, padrões, linguagem causal, títulos e exemplos) com recálculo independente sobre o cache e devolve o parecer do protocolo ([validation-protocol.md](skills/solvis-videns/references/validation-protocol.md)). Toda comparação de NPS e de proporções traz `delta.significance`; `--composition-check` separa efeito de composição.
- Atalhos `/ajuda`, `/status`, `/configurar`, `/inicio`, `/pesquisas`, `/unidades`, `/unidade XXXX`, `/atualizar`, `/ranking`, `/comentarios` e `/limpar`; comandos `unit` e `update`.
- Fluxo da pesquisa: `questionnaire` mostra regras de entrada e ramificações; `query` avisa `conditional_question` e traz `exposure`.
- Mês inicial da análise: nada anterior a ele é baixado; períodos anteriores são recusados (`period_before_start`).
- Download mais rápido (janelas em paralelo, `sync --until-complete`), atualização incremental dos dias recentes, aviso `tags_as_of_last_sync` e índice no cache para consultas por pergunta.
