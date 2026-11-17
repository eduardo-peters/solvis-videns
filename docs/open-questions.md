# Perguntas em aberto

Decisões que dependem de produto, comercial ou jurídico. Cada uma indica o que muda no plano.

| # | Pergunta | Por que importa | Proposta padrão |
|---|---|---|---|
| Q1 | Quais LLMs/plataformas os clientes usam (ChatGPT Enterprise, Claude, Gemini, Copilot, modelo próprio)? Eles rodam agentes com skills e MCP, ou só assistentes com function calling? | Define a ordem dos artefatos (skill + MCP vs. OpenAPI) | Levantar com os 2-3 clientes do piloto antes da Fase 2 |
| Q2 | A skill é gratuita para todos os clientes ou um módulo pago? | Escopos, limites e feature flag por cliente (como `clients.data_chat_enabled`) | Flag por cliente, desligada por padrão |
| Q3 | Licença e termos de uso da skill e do servidor MCP | O campo `license` do `SKILL.md` e o arquivo LICENSE | "Proprietary" até o jurídico definir |
| Q4 | Linguagem do servidor MCP: TypeScript (npx) ou Python (uvx)? | Manutenção pela equipe e facilidade de instalação no cliente | TypeScript: SDK MCP de referência e `npx` é o padrão mais comum em hosts MCP |
| Q5 | Limiar de amostra pequena (`small_sample`) | O sistema hoje não tem mínimo | 30 respostas, configurável por cliente |
| Q6 | "Hoje" dos presets: fuso de São Paulo para todos, ou fuso configurado do cliente? | Bordas de mês para clientes fora de Brasília | `America/Sao_Paulo`, revisar se houver cliente internacional |
| Q7 | Meta de latência e cotas por credencial | Dimensionamento do `analytics_api_reader` | p95 < 3 s por `/query`; 60 req/min e 5.000 req/dia por credencial |
| Q8 | Comentários entram no piloto (Fase 3 antecipada)? | Diagnóstico de queda sem comentários fica pela metade | Não; entram depois do piloto numérico estabilizar |
| Q9 | Quem pode criar credencial com `analytics:lgpd` e `analytics:reliability`? | Exposição de dado pessoal e de avaliações reprovadas | Só usuário com permissão de administração do cliente e `view_lgpd_protected_data_permission` / `manage_evaluations_reliability_permission` |
| Q10 | O Data Chat ("Fale com a Olvi") e a API Analytics devem compartilhar o mesmo catálogo de código? | Evita duas implementações das mesmas fórmulas | Sim (ADR-0005) |
| Q11 | Versionamento de alternativas e perguntas no produto (guardar a versão do questionário por avaliação) | Hoje o histórico é relido com o cadastro atual | Fora deste plano; registrar como dívida de produto |
