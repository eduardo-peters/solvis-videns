# ADR-0010: piloto com motor local sobre a API pública V1

- Status: aceito para o piloto
- Data: 2026-11-17
- Relaciona-se com: ADR-0001 (métricas no servidor), ADR-0006 (envelope), ADR-0009 (políticas)

## Contexto

O plano principal depende da API Analytics v1, que exige mudanças no `survey_system` (Fases 0 e 1). Antes desse investimento, a Solvis quer testar a skill com alguns clientes e medir se há demanda, sem alterar o backend. A API pública V1 só entrega avaliações brutas, com respostas identificadas por texto; a V2 só tem sentimentos, inacessíveis a partir da V1.

## Decisão

1. A skill do piloto traz um motor determinístico em Python (biblioteca padrão, 3.9+) que lê a API V1, normaliza as respostas para ids, guarda um cache local por credencial e calcula as métricas com as fórmulas das telas.
2. O princípio do ADR-0001 continua: **a LLM não calcula**. Muda só quem calcula: o motor local em vez do servidor.
3. O envelope mantém a forma do ADR-0006, acrescido de `coverage`, para a troca futura pelo servidor não mudar a skill.
4. Políticas: confiabilidade `all` por padrão com aviso em pesquisa com Data Quality (a credencial de API enxerga o cliente inteiro, como quem gerencia confiabilidade); incompletas incluídas; LGPD só em agregados; comentários mascarados.
5. Segurança aplicada no cliente: lista de permissão de pesquisas por `GET /api/v1/surveys/:id`, nenhum parâmetro fora de datas e paginação, nenhuma escrita, descarte de `web_access_info`.
6. A skill tem nome próprio (`solvis-survey-analysis-pilot`) e convive no repositório com o rascunho do plano principal (`solvis-survey-analysis`).

## Alternativas consideradas

| Alternativa | Por que não |
|---|---|
| LLM lê as avaliações e calcula | É o erro que o projeto inteiro evita (média de médias, N/A na média, MR somando 100%, fuso) |
| Usar o Data Chat (`/api/v1/data_chat/messages`) | Exige JWT de usuário, não a credencial de API; devolve texto narrado por outra LLM, não dados; consome a cota de LLM do cliente; fora de "API V1 e V2" pedido para o piloto |
| Usar `GET /api/v3/charts/:id/resume` | Sem autenticação (achado de segurança), só a primeira pergunta NPS e o histórico inteiro |
| Servidor MCP local | Mais uma peça para instalar e manter; o script na skill cobre os hosts do piloto. O motor já devolve dicionários e pode ganhar um adaptador MCP fino depois |
| Exportação CSV do `results_api` | Usa a senha de usuário do painel, um dia por chamada, colunas desalinhadas com campos adicionais |

## Consequências

- O primeiro uso de um período baixa avaliações; pesquisas grandes demoram (minutos) e geram carga na API. O cache e o orçamento de 90 s por comando limitam isso.
- Perguntas com texto repetido podem não ser calculáveis; o motor recusa em vez de errar.
- Paridade com as telas é responsabilidade do motor e precisa de conferência manual no teste interno (não há endpoint de referência na API pública).
- Os dados ficam no computador do usuário, sem dados pessoais diretos.
- Quando a API Analytics existir, `scripts/solvis_pilot/` vira um cliente dela e o cálculo local sai.
