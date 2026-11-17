# ADR-0002: modelo semântico versionado, com fonte no survey_system e snapshot na skill

- Status: proposto
- Data: 2026-11-17

## Contexto

A LLM precisa conhecer métricas, dimensões e regras antes de chamar a API, para escolher bem e para explicar o resultado. As fórmulas rodam no `survey_system`. Se o mesmo conteúdo for mantido à mão nos dois repositórios, os dois divergem.

## Decisão

1. A definição canônica fica no `survey_system`, junto do código que calcula: um registro de métricas e dimensões (Ruby ou YAML em `config/analytics/`) usado pelo `QueryPlanner` para validar pedidos e pelo endpoint `GET /api/analytics/v1/model` para publicá-lo.
2. A skill guarda um snapshot em `skills/solvis-survey-analysis/references/{metrics,dimensions,entities}.yaml`, com `model_version`.
3. O CI deste repositório baixa o modelo de staging e falha se o snapshot divergir (teste de contrato). A atualização do snapshot é um PR revisado.
4. Semver:
   - MAJOR: uma métrica muda de fórmula, denominador ou unidade; uma dimensão muda de significado; algo é removido.
   - MINOR: métrica, dimensão ou combinação nova.
   - PATCH: rótulos, descrições, exemplos.
5. Cada envelope de resposta traz `model_version`. Se o MAJOR do envelope for diferente do MAJOR do snapshot, a skill avisa o usuário e usa as descrições que vierem do endpoint `/model`.

Até o endpoint existir, o snapshot desta pasta é a especificação que o backend implementa.

## Formato

YAML legível por pessoa e por LLM, com identificadores em inglês (`nps`, `scale_mean`) e rótulos em pt-BR, en e es (os idiomas de pesquisa aceitos pelo sistema). Não adotamos um padrão externo de semantic layer (MetricFlow, Cube) porque o motor não é SQL genérico: as métricas compilam para templates fechados. O formato pode ser convertido depois se houver demanda.

## Consequências

- Mudança de fórmula no `survey_system` exige bump de versão do modelo e atualização da skill.
- A skill funciona offline para explicar conceitos, mas nunca para produzir números.
