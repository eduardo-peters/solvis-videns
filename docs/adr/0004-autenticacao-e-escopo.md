# ADR-0004: autenticação por credencial de API com escopo equivalente ao das telas

- Status: proposto
- Data: 2026-11-17

## Contexto

- `ApiCredential` (Doorkeeper, grant `password`) só tem `client_id`: enxerga todas as pesquisas e unidades do cliente, sem restrição por unidade, LGPD ou confiabilidade, e o Doorkeeper não usa escopos.
- O Data Chat monta o escopo a partir da `Ability` de um usuário (`Services::DataChat::Session`): pesquisas com `:view_results`, unidades acessíveis, LGPD, avaliações só confiáveis quando falta permissão.
- O JWT de usuário de `/api/v4/sessions` exige e-mail e senha de pessoa, ruim para integração de máquina.

## Decisão

1. Escopos OAuth novos no Doorkeeper: `analytics:read` (métricas e metadados), `analytics:comments` (texto de comentários), `analytics:lgpd` (respostas de perguntas protegidas), `analytics:reliability` (ver avaliações não confiáveis e detalhes de qualidade de dados).
2. `ApiCredential` ganha restrições opcionais: lista de pesquisas, lista de unidades (ou valores de propriedade), e os escopos máximos que pode pedir. Sem restrição, vale o cliente inteiro, como hoje.
3. Um objeto `Analytics::CredentialScope` expõe a mesma interface que `DataChat::Session` (`client_id`, `survey_ids`, `surveyed_unit_ids`, `reliable_only_survey_ids`, `lgpd?`), para o motor do catálogo rodar sem saber se a origem é usuário ou credencial.
4. Os escopos e restrições são configurados pela tela de credenciais de API, por usuário com permissão de administração do cliente.
5. Fase 4: authorization code + PKCE para o MCP remoto, com o token atrelado a um usuário real (o escopo passa a vir da `Ability` dele).

## Consequências

- Toda consulta é feita sob um escopo explícito, e o envelope declara qual.
- A correção dos problemas de isolamento já existentes na API pública é pré-requisito (Fase 0), porque a credencial nova usa o mesmo Doorkeeper.
