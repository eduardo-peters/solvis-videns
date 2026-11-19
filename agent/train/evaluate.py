#!/usr/bin/env python3
"""Avalia o modelo treinado (adapter LoRA) contra o base, nos casos dev e holdout.

Sobe o mlx_lm.server em 127.0.0.1:8090 com o base ou com o adapter, roda agent/eval_baseline.py
com AGENT_BACKEND=mlx e grava o resumo em ops/logs/training.log. Mesmo backend para os dois,
para a comparação medir só o efeito do treino.

  python3 agent/train/evaluate.py --adapter ~/.local/mlx-adapters/solvis-analyst-v1
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from train import BASE, PY, RAW, ROOT, log  # noqa: E402

PORT = 8090


def serve(adapter):
    cmd = [PY, "-m", "mlx_lm", "server", "--model", str(BASE), "--host", "127.0.0.1", "--port", str(PORT)]
    if adapter:
        cmd += ["--adapter-path", str(adapter)]
    p = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         env={**os.environ, "PYTHONWARNINGS": "ignore"})
    for _ in range(120):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{PORT}/v1/models", timeout=2)
            return p
        except Exception:
            time.sleep(1)
    p.kill()
    raise SystemExit("mlx_lm.server não subiu")


def run(label, adapter, case_set, runs):
    p = serve(adapter)
    try:
        out = RAW / f"train-eval-{label}-{case_set}.json"
        env = {**os.environ, "AGENT_BACKEND": "mlx", "AGENT_CONTEXT": "0", "AUDIT_DISABLED": "1",
               "AGENT_MODEL": f"mlx:{label}", "AGENT_TODAY": os.environ.get("AGENT_TODAY", "2026-11-18")}
        t0 = time.time()
        subprocess.run([sys.executable, str(ROOT / "agent/eval_baseline.py"), "--set", case_set, "--runs", str(runs),
                        "--out", str(out)], env=env, capture_output=True, check=True)
        res = json.loads(out.read_text())
    finally:
        p.terminate()
        p.wait()
    passed = sum(r["pass"] for r in res)
    summary = {"model": label, "set": case_set, "passed": passed, "cases": len(res),
               "pass_rate": round(passed / len(res), 3), "mean_secs": round(sum(r["secs"] for r in res) / len(res), 1),
               "failed": sorted({r["id"] for r in res if not r["pass"]}), "wall_min": round((time.time() - t0) / 60, 1)}
    log("eval", **summary)
    for r in res:
        if not r["pass"]:
            log("eval_failure", model=label, case=r["id"], calls=r.get("calls"), answer=(r.get("answer") or "")[:200])
    return summary


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--adapter", required=True)
    ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--skip-base", action="store_true")
    a = ap.parse_args()
    adapter = Path(a.adapter).expanduser()
    res = {}
    for label, ad in ([] if a.skip_base else [("base", None)]) + [(adapter.name, adapter)]:
        for s in ("dev", "holdout"):
            res[(label, s)] = run(label, ad, s, a.runs)
    if not a.skip_base:
        d = {s: round(res[(adapter.name, s)]["pass_rate"] - res[("base", s)]["pass_rate"], 3) for s in ("dev", "holdout")}
        verdict = ("adotar" if d["holdout"] > 0 and d["dev"] >= 0 else
                   "não adotar" if d["holdout"] < 0 or d["dev"] < 0 else "empate: manter o base")
        log("compare", adapter=adapter.name, delta_pass_rate=d, verdict=verdict,
            note="mesmo backend (mlx_lm.server, chamadas em texto) para base e treinado")


if __name__ == "__main__":
    main()
