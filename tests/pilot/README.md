# Testes do motor

Sem dependências fora da biblioteca padrão.

```bash
cd tests/pilot
python3 -m unittest discover -s . -p 'test_*.py'
```

| Arquivo | Conteúdo |
|---|---|
| `test_shortcuts.py` | `setup` (login testado antes de gravar, `.env` com permissão 600, senha por stdin, leitura/escrita do `.env` com caracteres especiais, prioridade do ambiente), `unit` (unidade contra rede, nome ambíguo, mês inicial) e `update` (baixa, pula o rebaixamento repetido, `--force`) |
| `test_units.py` | Fórmulas, arredondamento (NPS em ponto flutuante como o Ruby), períodos, máscara de dados pessoais, ingestão |
| `test_engine.py` | CLI de ponta a ponta contra a API falsa: escopo e lista de permissão, NPS/médias/distribuições contra valores calculados à mão, agregação por contagens, comparações, ambiguidade de texto, LGPD, respostas vazias, HTTP 400 e página cheia, cache, orçamento de tempo |
| `test_incremental.py` | Atualização incremental por `created_at` com relógio controlado: janela pedida, sobreposição sem duplicar, avaliação atrasada, intervalo maior que 7 dias, falha da API |
| `test_start_month.py` | Mês inicial: sem ele nada é baixado, períodos e comparações anteriores a ele são recusados sem chamar a API, aviso de tags |
| `test_flow.py` | Fluxo da pesquisa: regras de entrada e ramificações lidas do questionário, `flow` e `shown_to` em `questionnaire`, aviso `conditional_question`, `exposure` inferido (incompleta, pulou, desvio por ramificação, prioridade, grupo NPS), públicos das perguntas gêmeas |
| `test_sync_speed.py` | Download: janelas em paralelo dão o mesmo total que sequencial, página de 10.000 (limite da API), `sync --until-complete` (termina em várias rodadas e para sem progresso), timeout de leitura e resposta interrompida retentados, índice cobrindo a junção e `ANALYZE` no cache (inclusive cache antigo) |
| `fake_api.py` | API V1 falsa, fiel ao formato e aos comportamentos da real |
| `fixture.py` | Cliente "Rede Exemplo" com os casos de borda e os valores esperados no cabeçalho |

Nunca grave credencial ou dados reais nesta pasta.
