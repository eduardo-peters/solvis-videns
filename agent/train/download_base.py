"""Baixa o modelo base em MLX (4 bits) para o treino LoRA. Roda no venv do MLX.

~/.local/mlx-venv/bin/python agent/train/download_base.py
"""
import os
from pathlib import Path

from huggingface_hub import snapshot_download

REPO = os.environ.get("TRAIN_BASE_REPO", "mlx-community/Qwen3-1.7B-4bit")
DEST = Path.home() / ".local/mlx-models" / REPO.split("/")[1]
print(snapshot_download(REPO, local_dir=str(DEST)))
