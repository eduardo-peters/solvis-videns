# ADR-0003: distribuição como Agent Skill + servidor MCP + OpenAPI

- Status: proposto (depende da pergunta Q1 em [open-questions.md](../open-questions.md))
- Data: 2026-11-17

## Contexto

Os clientes usam LLMs diferentes. Em 2026 o formato [Agent Skills](https://agentskills.io/specification) (pasta com `SKILL.md`, `references/`, `scripts/`, `assets/`) é aceito por dezenas de ferramentas, e o [Model Context Protocol](https://modelcontextprotocol.io/specification/2025-11-25) é o protocolo comum para ferramentas, com autorização OAuth 2.1 para servidores remotos. Plataformas que só aceitam function calling por OpenAPI (ações de assistentes corporativos) não leem skills nem MCP.

## Decisão

Três artefatos, todos gerados deste repositório e com a mesma versão:

| Artefato | Para quem | Conteúdo |
|---|---|---|
| Agent Skill `solvis-survey-analysis` (zip) | Clientes com hosts compatíveis com Agent Skills | Instruções, modelo semântico, playbooks, formato de resposta |
| Servidor MCP `solvis-analytics` | Hosts com MCP | Ferramentas finas sobre a API Analytics. Fase 2: pacote local (stdio) com credencial em variável de ambiente. Fase 4: servidor remoto hospedado pela Solvis (Streamable HTTP, OAuth 2.1 com PKCE contra o Doorkeeper) |
| `openapi.analytics.v1.yaml` + prompt de sistema | Plataformas só com function calling | Contrato HTTP e uma versão condensada do `SKILL.md` |

A regra de negócio fica só na API. Skill e MCP não calculam nada, então os três artefatos dão o mesmo número para a mesma pergunta.

## Alternativas

| Alternativa | Trade-off |
|---|---|
| Só OpenAPI | Funciona em quase tudo, mas a LLM não recebe as regras de interpretação de forma progressiva; o prompt fica grande |
| MCP remoto desde o início, dentro do Rails (SDK Ruby oficial) | Nada a instalar e atualização central. Exige fluxo authorization code + PKCE no Doorkeeper (hoje só `password`) e descoberta de metadados OAuth. Mais trabalho antes do piloto |
| MCP local em pacote (escolhido para o piloto) | Rápido de entregar e auth simples (credencial). O cliente instala e guarda a credencial na máquina; atualizações dependem do cliente |

## Consequências

- O piloto pode começar sem mudar o Doorkeeper além dos escopos.
- O MCP remoto entra quando houver mais de um punhado de clientes ou exigência de SSO.
- Linguagem do pacote MCP é decisão em aberto (Q4).
