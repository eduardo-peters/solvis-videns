"""Mede extração + consulta com volume alto na API falsa. Uso: python tests/pilot/bench.py [avaliações_por_dia] [dias]"""

import datetime as dt
import os
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "solvis-survey-analysis-pilot", "scripts"))

import fixture  # noqa: E402
from solvis_pilot import cli  # noqa: E402

per_day = int(sys.argv[1]) if len(sys.argv) > 1 else 500
days = int(sys.argv[2]) if len(sys.argv) > 2 else 30
f = fixture.build()
for d in range(days):
    for k in range(per_day):
        ts = dt.datetime(2026, 9, 1, 7) + dt.timedelta(days=d, seconds=k * 40)
        unit = 101 + k % 4
        f.add_eval(56, unit, ts, [(fixture.NPS, None, k % 11, None), (fixture.ATEND, fixture.OTIMO + k % 6, None, None),
                                  (fixture.COMENT, None, None, f"comentário {k}")], tags=[(fixture.COMENT, fixture.FILA)])
os.environ.update({"SOLVIS_API_BASE_URL": f.start(), "SOLVIS_API_USERNAME": f.username,
                   "SOLVIS_API_PASSWORD": f.password, "SOLVIS_CACHE_DIR": tempfile.mkdtemp(), "SOLVIS_TODAY": "2026-11-17"})
args = ["query", "--metric", "nps", "--survey", "56", "--question", str(fixture.NPS), "--start", "2026-09-01",
        "--end", (dt.date(2026, 9, 1) + dt.timedelta(days=days - 1)).isoformat(), "--group-by", "unit",
        "--budget", "600"]
cli.main(["config", "--start-month", "2026-09"])
t0 = time.time()
cli.main(args)
t1 = time.time()
cli.main(args + ["--group-by", "week"])
t2 = time.time()
print(f"\n{per_day * days} avaliações: extração+consulta {t1 - t0:.1f}s; consulta em cache {t2 - t1:.2f}s; "
      f"chamadas à API {len(f.evaluation_requests())}", file=sys.stderr)
f.stop()
