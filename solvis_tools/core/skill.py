"""Leitura estruturada da skill do piloto (fonte única: os arquivos da skill, lidos na hora)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "skills" / "solvis-survey-analysis-pilot"


def _question_types():
    """Tabela de question-types.md: answer_type -> {what, metrics, notes}."""
    out = {}
    for line in (SKILL / "references/question-types.md").read_text().splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].startswith("`") and cells[0] != "`answer_type`":
            for t in re.findall(r"`([^`]+)`", cells[0]):
                out[t] = {"what": cells[1], "metrics": re.findall(r"`([a-z_]+)`", cells[2]), "notes": cells[3]}
    return out


def _metric_block(metric_id):
    """Bloco do metrics.yaml de uma métrica (texto, sem depender de PyYAML)."""
    text = (SKILL / "references/metrics.yaml").read_text()
    m = re.search(r"^  - id: %s\n(.*?)(?=^  - id: |\Z)" % re.escape(metric_id), text, re.S | re.M)
    return m.group(0).rstrip() if m else None


def _metric_ids():
    return re.findall(r"^  - id: ([a-z_]+)", (SKILL / "references/metrics.yaml").read_text(), re.M)


def _invariants():
    text = (SKILL / "references/invariants.md").read_text()
    return {m.group(1): m.group(2).strip().rstrip(".") for m in re.finditer(r"\[(INV-\d+)\]\s*(.+?)\*\*", text)}
