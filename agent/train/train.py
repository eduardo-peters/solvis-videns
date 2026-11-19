#!/usr/bin/env python3
"""Treino LoRA do modelo local com MLX e registro dos outputs relevantes.

Roda o mlx_lm (venv ~/.local/mlx-venv) sobre ops/training/<versão>/data, salva o adapter fora do
repositório (~/.local/mlx-adapters/<nome>) e grava em ops/logs/training.log só o que importa:
configuração, tamanho dos dados, loss de treino a cada relatório, loss de validação, memória
de pico, tempo e onde ficou o adapter. A saída completa vai para agent/results (fora do git).

  python3 agent/train/train.py                 treina com a configuração padrão
  python3 agent/train/train.py --iters 50      teste rápido
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PY = os.environ.get("MLX_PYTHON", str(Path.home() / ".local/mlx-venv/bin/python"))
BASE = Path(os.environ.get("TRAIN_BASE", Path.home() / ".local/mlx-models/Qwen3-1.7B-4bit"))
LOG = ROOT / "ops" / "logs" / "training.log"
RAW = ROOT / "agent" / "results"


def log(event, **data):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    line = f"{dt.datetime.now().isoformat(timespec='seconds')} {event:<14} " + json.dumps(data, ensure_ascii=False)
    with LOG.open("a") as f:
        f.write(line + "\n")
    print(line, flush=True)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--version", default="v2", help="pasta ops/training/<versão>/data")
    ap.add_argument("--name", help="nome do adapter (padrão solvis-analyst-<versão>)")
    ap.add_argument("--iters", type=int, default=200)
    ap.add_argument("--lr", type=float, default=1e-4)
    ap.add_argument("--layers", type=int, default=8)
    ap.add_argument("--batch", type=int, default=1)
    ap.add_argument("--max-seq", type=int, default=2048)
    a = ap.parse_args()
    a.name = a.name or f"solvis-analyst-{a.version}"
    DATA = ROOT / "ops" / "training" / a.version / "data"
    adapter = Path.home() / ".local/mlx-adapters" / a.name
    adapter.mkdir(parents=True, exist_ok=True)
    n_train = sum(1 for _ in (DATA / "train.jsonl").open())
    n_valid = sum(1 for _ in (DATA / "valid.jsonl").open())
    cfg = {"name": a.name, "version": a.version, "base": BASE.name, "method": "LoRA (QLoRA sobre 4 bits)", "iters": a.iters,
           "learning_rate": a.lr, "lora_layers": a.layers, "batch_size": a.batch, "max_seq_length": a.max_seq,
           "mask_prompt": True, "grad_checkpoint": True, "train_examples": n_train, "valid_examples": n_valid,
           "epochs_approx": round(a.iters * a.batch / n_train, 2), "data_sha": sha(DATA / "train.jsonl"),
           "generator": "agent/train/build_dataset.py", "adapter_path": str(adapter)}
    log("train_start", **cfg)
    cmd = [PY, "-u", "-m", "mlx_lm", "lora", "--model", str(BASE), "--train", "--data", str(DATA),
           "--adapter-path", str(adapter), "--fine-tune-type", "lora", "--iters", str(a.iters),
           "--learning-rate", str(a.lr), "--num-layers", str(a.layers), "--batch-size", str(a.batch),
           "--max-seq-length", str(a.max_seq), "--mask-prompt", "--grad-checkpoint",
           "--steps-per-report", "25", "--steps-per-eval", "100", "--val-batches", "25",
           "--save-every", "100", "--seed", "20261119"]
    raw = RAW / f"train-{a.name}-{dt.datetime.now():%Y%m%d-%H%M%S}.out"
    RAW.mkdir(parents=True, exist_ok=True)
    t0, peak, last_train, vals = time.time(), 0.0, None, []
    with raw.open("w") as out, subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                                env={**os.environ, "PYTHONWARNINGS": "ignore"}) as p:
        for line in p.stdout:
            out.write(line)
            m = re.search(r"Iter (\d+): Val loss ([\d.]+)", line)
            if m:
                vals.append(float(m.group(2)))
                log("val", iter=int(m.group(1)), val_loss=float(m.group(2)))
                continue
            m = re.search(r"Iter (\d+): Train loss ([\d.]+).*?It/sec ([\d.]+).*?Peak mem ([\d.]+) GB", line)
            if m:
                last_train = float(m.group(2))
                peak = max(peak, float(m.group(4)))
                log("train", iter=int(m.group(1)), train_loss=last_train, it_per_sec=float(m.group(3)),
                    peak_mem_gb=float(m.group(4)))
            elif re.search(r"Error|Traceback|out of memory", line, re.I):
                log("error", line=line.strip()[:300])
        p.wait()
    if p.returncode:
        log("train_failed", returncode=p.returncode, raw_output=str(raw.relative_to(ROOT)))
        sys.exit(1)
    log("train_done", minutes=round((time.time() - t0) / 60, 1), final_train_loss=last_train,
        val_loss_first=vals[0] if vals else None, val_loss_last=vals[-1] if vals else None, peak_mem_gb=peak,
        adapter_mb=round(sum(f.stat().st_size for f in adapter.glob("*.safetensors")) / 1e6, 1),
        adapter_path=str(adapter), raw_output=str(raw.relative_to(ROOT)), weights_of_base_changed=False)


if __name__ == "__main__":
    main()
