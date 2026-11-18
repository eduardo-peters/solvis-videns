# Instalação no cliente (piloto)

Acompanhe a instalação com o cliente. Leva cerca de 15 minutos.

## Pré-requisitos

- Um host que leia Agent Skills e execute comandos: Claude Code, Codex, Cursor, VS Code com Copilot em modo agente, Gemini CLI, Kiro ou similar.
- Python 3.9 ou mais novo na máquina (`python3 --version`; no Windows, `py --version`). Nenhum pacote extra.
- Acesso de rede da máquina a `https://sistema.solvis.net.br`.

## 1. Credencial

1. Na Solvis: Arquivo > Cliente > Lista de credenciais da API > Nova credencial. Use o e-mail de quem vai usar a skill e a descrição "Piloto skill LLM". Uma credencial por cliente do piloto, para os logs separarem o uso.
2. O e-mail traz `username` e `password`.
3. Na máquina do usuário, crie o arquivo de credencial (não use arquivo dentro de projetos versionados):
   - macOS/Linux: `~/.config/solvis-survey-analysis/credentials.json`, depois `chmod 600` no arquivo.
   - Windows: `%APPDATA%\solvis-survey-analysis\credentials.json`.

   ```json
   {"username": "<username do e-mail>", "password": "<password do e-mail>"}
   ```

   Alternativa: variáveis de ambiente `SOLVIS_API_USERNAME` e `SOLVIS_API_PASSWORD` no host.

Nunca cole a senha no chat da LLM.

## 2. Skill

Descompacte `solvis-survey-analysis-pilot-0.2.0.zip` na pasta de skills do host. A pasta precisa se chamar `solvis-survey-analysis-pilot` e conter `SKILL.md`, `scripts/` e `references/`. Locais comuns:

| Host | Pasta |
|---|---|
| Claude Code | `~/.claude/skills/` (todas as sessões) ou `.claude/skills/` do projeto |
| Hosts que leem `.agents/skills/` | `.agents/skills/` do projeto |
| Outros | ver a documentação do host para "Agent Skills" |

Para gerar o zip a partir deste repositório:

```bash
cd skills && zip -r ../dist/solvis-survey-analysis-pilot-0.2.0.zip solvis-survey-analysis-pilot -x '*/__pycache__/*'
```

## 3. Teste

No terminal, a partir da pasta da skill:

```bash
python3 scripts/solvis.py scope
```

Deve listar as pesquisas ativas. Erros comuns: `missing_credentials` (arquivo no lugar errado), `auth_failed` (senha errada ou credencial resetada), `api_unreachable` (rede ou proxy).

No host, peça: "Quais pesquisas tivemos nos últimos 90 dias e qual o NPS da principal?". A LLM deve rodar `scope`, `questionnaire` e `query`, e terminar a resposta com `Fontes: q_...`.

## 4. Durante o piloto

- Resposta suspeita: o usuário copia o `query_id` da linha de fontes e roda `python3 scripts/solvis.py explain --query-id <id>`; o JSON vai para a Solvis.
- Para apagar os dados locais: `python3 scripts/solvis.py purge --yes`.
- No fim do piloto, revogue ou resete a credencial.
