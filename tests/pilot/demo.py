"""Roda comandos do motor contra a API falsa e imprime a saída. Uso:

    python tests/pilot/demo.py query --metric nps --survey 56 --question 812 --period month:2026-10 --group-by unit
"""

import contextlib
import io
import os
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-survey-analysis-pilot", "scripts"))

import fixture  # noqa: E402
from solvis_pilot import cli  # noqa: E402

if __name__ == "__main__":
    fake = fixture.build()
    os.environ.update({
        "SOLVIS_API_BASE_URL": fake.start(),
        "SOLVIS_API_USERNAME": fake.username,
        "SOLVIS_API_PASSWORD": fake.password,
        "SOLVIS_CACHE_DIR": os.environ.get("SOLVIS_CACHE_DIR") or tempfile.mkdtemp(),
        "SOLVIS_TODAY": "2026-11-17",
    })
    try:
        with contextlib.redirect_stdout(io.StringIO()):  # mês inicial para a demonstração
            cli.main(["config", "--start-month", os.environ.get("DEMO_START_MONTH", "2025-01")])
        code = cli.main(sys.argv[1:])
    finally:
        fake.stop()
    sys.exit(code)
