# Testes do motor do piloto

Sem dependências fora da biblioteca padrão.

```bash
cd tests/pilot
python3 -m unittest test_units test_engine test_incremental test_start_month
```

| Arquivo | Conteúdo |
|---|---|
| `test_units.py` | Fórmulas, arredondamento (NPS em ponto flutuante como o Ruby), períodos, máscara de dados pessoais, ingestão |
| `test_engine.py` | CLI de ponta a ponta contra a API falsa: escopo e lista de permissão, NPS/médias/distribuições contra valores calculados à mão, agregação por contagens, comparações, ambiguidade de texto, LGPD, falhas da API (lista vazia, HTTP 400, página cheia), cache, orçamento de tempo |
| `test_incremental.py` | Atualização incremental por `created_at` com relógio controlado: janela pedida, sobreposição sem duplicar, avaliação atrasada, intervalo maior que 7 dias, falha da API |
| `test_start_month.py` | Mês inicial: sem ele nada é baixado, períodos e comparações anteriores a ele são recusados sem chamar a API, aviso de tags |
| `fake_api.py` | API V1 falsa, fiel ao formato e às falhas da real (`handler_answers_service.rb`, `surveys_controller.rb`) |
| `fixture.py` | Cliente "Rede Exemplo" com os casos de borda e os valores esperados no cabeçalho |
| `demo.py` | Roda qualquer comando do motor contra a API falsa: `python3 tests/pilot/demo.py --pretty query --metric nps --survey 56 --question 812 --period month:2026-10 --group-by unit` |
| `bench.py` | Volume alto na API falsa: `python3 tests/pilot/bench.py 1000 30` |

Testes contra a API real usam uma credencial de teste fora do repositório (arquivo próprio apontado por `SOLVIS_CREDENTIALS_FILE` e `SOLVIS_CACHE_DIR` temporário). Nunca grave credencial ou dados reais nesta pasta.
