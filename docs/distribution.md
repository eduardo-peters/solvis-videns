# Distribuição

## Artefatos de release

Cada tag `vX.Y.Z` deste repositório gera, no GitHub Releases:

| Arquivo | Conteúdo |
|---|---|
| `solvis-survey-analysis-X.Y.Z.zip` | A pasta `skills/solvis-survey-analysis/` (nome da pasta = `name` do `SKILL.md`, como exige o padrão) |
| Pacote MCP `solvis-analytics` X.Y.Z | Publicado no registro de pacotes escolhido em Q4 |
| `openapi.analytics.v1.yaml` | Contrato da API, quando publicado |
| `CHANGELOG.md` | Mudanças para cliente, inclusive mudanças de `model_version` |

O que nunca entra no artefato: `docs/`, `evals/`, relatórios de pesquisa, exemplos com dados reais.

## Versões

- Skill: semver em `SKILL.md` → `metadata.version`.
- Modelo semântico: `metadata.semantic-model-version` e `model_version` nos YAML. Regras de bump em [ADR-0002](adr/0002-modelo-semantico-versionado.md).
- Uma release da skill declara o intervalo de `model_version` com que funciona. MAJOR novo do modelo exige release nova da skill.

## Instalação no cliente

O padrão Agent Skills define o formato, não o lugar de instalação; cada host tem o seu. O guia de instalação de cada release lista os hosts testados no piloto. Passos genéricos:

1. Criar a credencial de API na Solvis (tela de credenciais) com os escopos desejados.
2. Instalar a skill: descompactar o zip na pasta de skills do host (ex.: `.agents/skills/` do projeto, que vários hosts leem) ou enviar o zip pela interface do host.
3. Configurar o servidor MCP no host com as variáveis `SOLVIS_API_USERNAME`, `SOLVIS_API_PASSWORD` e, opcionalmente, `SOLVIS_API_BASE_URL`.
4. Testar com "quais pesquisas eu tenho e quantas avaliações cada uma teve no último mês?".

Fase 4: o servidor MCP remoto dispensa o passo 3; o host abre o fluxo OAuth e o usuário entra com a conta Solvis.

## Plataformas só com function calling

Para assistentes que aceitam apenas OpenAPI e um prompt de sistema:
- importar `openapi.analytics.v1.yaml`;
- usar como instrução o `SKILL.md` condensado (gerado no build), que inclui as regras invioláveis, o fluxo e a lista do que não existe;
- as referências longas (`metrics.yaml`, `invariants.md`) são servidas por `GET /model` em vez de ficarem no prompt.

## Canal de feedback

Clientes reportam respostas erradas com o `query_id` citado na resposta. A Solvis reabre a consulta pela auditoria (`analytics_queries`), corrige a skill ou o modelo e acrescenta o caso em `evals/`.
