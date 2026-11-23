# Solvis Videns

> **Veja o que seus clientes dizem. Decida com evidência.**

Skill de análise de resultados de pesquisas de satisfação da plataforma [Solvis](https://sistema.solvis.net.br), para o cliente usar no agente de IA que já tem (Claude Code, Codex, Cursor, Gemini CLI e outros hosts que leem [Agent Skills](https://agentskills.io)). Ela lê as pesquisas pela API pública da Solvis, calcula cada número num motor local e confere o que escreveu antes de entregar.

## Por que Videns

*Videns* é latim e quer dizer "aquele que vê". Vem do verbo *videre*, a mesma raiz de "visionária", o "Vis" de Soluções Visionárias. A mesma raiz explica o que o produto entrega:

- **Evidência** (*e-videns*, "o que se vê claramente"): todo número vem do motor de análise e é conferido antes de o relatório sair. Nada é inventado.
- **Providência** (*pro-videns*, "que vê antes"): o resultado não é um gráfico, é um plano de ação para agir antes que o problema cresça.

Em uma frase: o Solvis Videns é a visão da Solvis transformada em produto. Ele lê as pesquisas, mostra o que os clientes estão dizendo e entrega o que fazer a seguir.

## O que ela faz

- NPS, médias de escala, soma ponderada, distribuição de alternativas, volume de avaliações, comentários e tags, por pesquisa, unidade, período, regional, canal, dia da semana, horário e grupo NPS.
- Comparações entre períodos, rankings, evolução e diagnóstico de quedas, com teste de significância e checagem de composição.
- Relatórios e decks com a cara do cliente (perfil de marca) e com cada afirmação validada por recálculo independente antes da entrega.
- A LLM nunca calcula: todo número sai do motor `scripts/solvis.py`, que aplica as fórmulas das telas de resultados e devolve n, período, filtros, políticas, frescor e um `query_id` para auditoria.

## Instalação

**Pré-requisitos:** um host que leia Agent Skills e execute comandos; Python 3.9 ou mais novo (`python3 --version`; no Windows, `py --version`), sem pacotes extras; acesso de rede a `https://sistema.solvis.net.br`; uma credencial da API Solvis (Arquivo > Cliente > Lista de credenciais da API).

**IMPORTANTE! essa skill funciona somente em agentes de código, como o Claude Code, e não em chats de LLMs.**

**1. Peça para o seu agente de IA instalar pra você.** Digite no prompt do seu agente (Claude Code, Kiro, etc):

```prompt
Instale a Skill solvis-videns do repositório https://github.com/eduardo-peters/solvis-videns.git e me conduza na preparação do ambiente.
```


**2. Baixe a skill do GitHub.** Com git (atualizar depois é só `git pull`):

```bash
git clone https://github.com/eduardo-peters/solvis-videns.git ~/solvis-videns
```

Sem git: baixe o [zip de `main`](https://github.com/eduardo-peters/solvis-videns/archive/refs/heads/main.zip) e descompacte. Para fixar uma versão, use uma tag (`git checkout v0.2.0`).

**3. Aponte o host para a pasta `skills/solvis-videns`.** A pasta precisa manter esse nome. No Claude Code, por exemplo:

```bash
mkdir -p ~/.claude/skills
ln -s ~/solvis-videns/skills/solvis-videns ~/.claude/skills/solvis-videns
```

No Windows, copie a pasta em vez de linkar: `Copy-Item -Recurse ~\solvis-videns\skills\solvis-videns ~\.claude\skills\solvis-videns`.

| Host | Pasta de skills |
|---|---|
| Claude Code | `~/.claude/skills/` (todas as sessões) ou `.claude/skills/` do projeto |
| Hosts que leem `.agents/skills/` | `.agents/skills/` do projeto |
| Outros | ver a documentação do host para "Agent Skills" |

**3. Primeiro uso.** Crie uma pasta para o cliente (por exemplo `~/clientes/rede-exemplo`), abra o host nela e pergunte algo sobre as pesquisas (ou digite `/ajuda`). A skill conduz o resto: pede usuário e senha da API (testa o login e grava num `.env` só do usuário), o mês inicial da análise, a decisão sobre guardar texto de perguntas protegidas por LGPD e uma descrição do cliente. Tudo fica em `.solvis-videns/` dentro dessa pasta de trabalho (credencial, contexto, marca e cache, com `.gitignore` próprio), e os relatórios gerados também ficam nela. **Um cliente por pasta:** quem atende vários clientes abre o host numa pasta diferente para cada um; a skill recusa trocar o cliente de uma pasta sem pedido explícito. Para testar o motor direto no terminal:

```bash
python3 ~/solvis-videns/skills/solvis-videns/scripts/solvis.py scope
```

Erros comuns do motor: `missing_credentials` (rode o primeiro uso), `auth_failed` (usuário ou senha errados, ou credencial resetada), `api_unreachable` (rede ou proxy até `sistema.solvis.net.br`), `client_mismatch` (a pasta já é de outro cliente: abra o host em outra pasta).

Para apagar os dados locais de uma pasta: `python3 .../scripts/solvis.py purge --yes` (cache) e remover `.solvis-videns/` (credencial, contexto e marca). Ao encerrar o uso, revogue a credencial na Solvis.

## Estrutura do repositório

| Caminho | Conteúdo |
|---|---|
| `skills/solvis-videns/` | A skill: `SKILL.md`, `references/` (modelo semântico, regras, playbooks, formato de resposta, protocolo de validação) e o motor `scripts/solvis.py` (API pública V1, Python 3.9+, sem dependências) |
| `tests/pilot/` | Testes do motor com uma API V1 falsa (`cd tests/pilot && python3 -m unittest discover`) |

```
Agente de IA do cliente
  └─ Solvis Videns (skills/solvis-videns)     instruções, modelo semântico, playbooks, formato de resposta
       └─ scripts/solvis.py                   motor local: cache, fórmulas das telas, validação
            └─ API pública V1 da Solvis       somente leitura, com a credencial do cliente
```

## Para quem for alterar a skill

1. [skills/solvis-videns/SKILL.md](skills/solvis-videns/SKILL.md): as regras e o fluxo que a LLM segue.
2. [skills/solvis-videns/references/cli.md](skills/solvis-videns/references/cli.md): comandos e envelope do motor.
3. [tests/pilot/README.md](tests/pilot/README.md): os testes com a API falsa.
4. [CHANGELOG.md](CHANGELOG.md).

Validador de referência do padrão Agent Skills ([skills-ref](https://github.com/agentskills/agentskills/tree/main/skills-ref)):

```bash
git clone --depth 1 https://github.com/agentskills/agentskills /tmp/agentskills
cd /tmp/agentskills/skills-ref && uv sync && . .venv/bin/activate
skills-ref validate <pasta deste repositório>/skills/solvis-videns
```

## Licença

Conteúdo proprietário da Solvis (`license: Proprietary` no `SKILL.md`), para uso pelos clientes da plataforma Solvis.

---

Solvis Videns · com tecnologia Claude, da Anthropic.
