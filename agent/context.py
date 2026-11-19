"""Contexto da skill para o agente local: indexação vetorial e recuperação por pergunta.

A skill do piloto (skills/solvis-survey-analysis-pilot) tem ~68 KB; o modelo local roda
com contexto pequeno. Cada seção (## título) dos arquivos de regra vira um trecho com
embedding (Ollama, nomic-embed-text) na tabela semantic.skill_chunks do ClickHouse.
Na pergunta, entram os trechos mais próximos dentro de um orçamento de caracteres.

Só conteúdo da skill é vetorizado aqui (nada de dado de cliente).

Indexar:  python3 agent/context.py index
Testar:   python3 agent/context.py search "qual o nosso CSAT?"
"""
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "solvis-survey-analysis-pilot"
OLLAMA = os.environ.get("OLLAMA_URL", "http://127.0.0.1:11434")
EMBED_MODEL = os.environ.get("AGENT_EMBED_MODEL", "nomic-embed-text")
CH_BIN = os.environ.get("CLICKHOUSE_BIN", str(Path.home() / ".local/clickhouse/clickhouse"))
BUDGET = int(os.environ.get("AGENT_CONTEXT_CHARS", "3000"))

# Arquivos de regra. cli.md e os YAML ficam fora: descrevem o motor de linha de comando,
# que este agente não usa (as ferramentas dele estão em agent.py).
SOURCES = ["SKILL.md", "references/invariants.md", "references/playbooks.md", "references/glossary.md",
           "references/limitations.md", "references/answer-format.md", "references/question-types.md"]
# Seções do SKILL.md que só valem para o motor local (credencial, download, cache).
SKIP_HEADINGS = ("Credencial", "Referências")

# Os trechos citam comandos do motor do piloto. O modelo recebe esta tradução.
CLI_NOTE = """Os trechos abaixo vêm da skill do motor de linha de comando. Neste ambiente, use só as ferramentas:
query --metric nps → nps; scale_mean → scale_mean; choice_share → choice_share; evaluation_count → evaluation_count;
--group-by unit → group_by="unit"; --group-by unit_property → group_by="<nome da propriedade>".
Ainda não disponíveis aqui (diga isso ao usuário se ele pedir): comparação de períodos (--compare-with), recorte
por mês/dia/hora, comentários, tags, weighted_sum, multi_response_share, choice_set_share, filtros de
canal/confiabilidade. Ignore comandos como scope, config, resolve, questionnaire, sync, explain e query_id."""


def chunks():
    out = []
    for rel in SOURCES:
        text = (SKILL / rel).read_text()
        text = re.sub(r"^---\n.*?\n---\n", "", text, flags=re.S)  # frontmatter
        parts = re.split(r"^(#{2,3} .+)$", text, flags=re.M)
        for i in range(1, len(parts), 2):
            heading = parts[i].lstrip("# ").strip()
            body = parts[i + 1].strip()
            if rel == "SKILL.md" and heading.startswith(SKIP_HEADINGS):
                continue
            if len(body) < 80:
                continue
            for j, piece in enumerate(_split(body, 1800)):
                out.append({"source": rel, "heading": heading + (f" ({j + 1})" if j else ""), "text": piece})
    return out


def _split(body, size):
    """Divide seções longas em parágrafos, sem cortar no meio de uma linha."""
    if len(body) <= size:
        return [body]
    pieces, cur = [], ""
    for line in body.split("\n"):
        if len(cur) + len(line) > size and cur:
            pieces.append(cur.strip())
            cur = ""
        cur += line + "\n"
    if cur.strip():
        pieces.append(cur.strip())
    return pieces


def embed(texts, kind):
    """nomic-embed-text usa prefixos de tarefa: search_document / search_query."""
    body = json.dumps({"model": EMBED_MODEL, "input": [f"{kind}: {t}" for t in texts]}).encode()
    req = urllib.request.Request(OLLAMA + "/api/embed", data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return json.loads(r.read())["embeddings"]


def index():
    cs = chunks()
    vecs = embed([f"{c['heading']}\n{c['text']}" for c in cs], "search_document")
    ddl = """CREATE TABLE IF NOT EXISTS semantic.skill_chunks
    (source String, heading String, text String, embedding Array(Float32))
    ENGINE = MergeTree ORDER BY (source, heading)"""
    subprocess.run([CH_BIN, "client", "-q", ddl], check=True)
    subprocess.run([CH_BIN, "client", "-q", "TRUNCATE TABLE semantic.skill_chunks"], check=True)
    rows = "\n".join(json.dumps({**c, "embedding": v}, ensure_ascii=False) for c, v in zip(cs, vecs))
    subprocess.run([CH_BIN, "client", "-q", "INSERT INTO semantic.skill_chunks FORMAT JSONEachRow"],
                   input=rows.encode(), check=True)
    print(f"{len(cs)} trechos indexados de {len(SOURCES)} arquivos ({sum(len(c['text']) for c in cs)} caracteres)")


def retrieve(question, ch, k=6, budget=BUDGET):
    """Trechos mais próximos da pergunta, até o orçamento de caracteres. ch = agent.ch."""
    v = embed([question], "search_query")[0]
    rows = ch("SELECT source, heading, text, cosineDistance(embedding, {v:Array(Float32)}) AS d "
              "FROM semantic.skill_chunks ORDER BY d LIMIT {k:UInt8}", {"v": "[" + ",".join(map(str, v)) + "]", "k": k})
    picked, used = [], 0
    for r in rows:
        if used + len(r["text"]) > budget:
            continue
        picked.append(r)
        used += len(r["text"])
    return picked


def render(picked):
    if not picked:
        return ""
    body = "\n\n".join(f"[{r['source']} · {r['heading']}]\n{r['text']}" for r in picked)
    return f"\n\n## Regras da skill relevantes para esta pergunta\n{CLI_NOTE}\n\n{body}"


if __name__ == "__main__":
    if sys.argv[1:2] == ["index"]:
        index()
    elif sys.argv[1:2] == ["search"]:
        sys.path.insert(0, str(Path(__file__).parent))
        import agent
        for r in retrieve(" ".join(sys.argv[2:]), agent.ch):
            print(f"{float(r['d']):.3f}  {r['source']} · {r['heading']}  ({len(r['text'])} car.)")
    else:
        print(__doc__)
