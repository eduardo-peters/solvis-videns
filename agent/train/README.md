# Treino LoRA do modelo local

Documentação completa: [docs/training.md](../../docs/training.md) · Log: [ops/logs/training.log](../../ops/logs/training.log)

| Arquivo | O que faz |
|---|---|
| `build_dataset.py` | Gera os dados de cada versão a partir das regras da skill (dados fictícios). `--version v1` reproduz a v1 byte a byte |
| `download_base.py` | Baixa o modelo base MLX (~1 GB, fora do repositório) |
| `train.py` | Treina o LoRA de uma versão e grava os eventos relevantes no log |
| `evaluate.py` | Compara o base e o adapter (dev e holdout) no mesmo backend e grava o veredito |

## Versões

| Versão | Dados | Estado | Manifesto |
|---|---|---|---|
| v1 | 352 conversas · 567/62 exemplos · `7a69986bcd10` | Treinada; holdout de 25% para 62,5% no MLX; não adotada | [ops/training/v1/manifest.json](../../ops/training/v1/manifest.json) |
| v2 | 482 conversas · 804/85 exemplos · `45271be1ac26` | Dados prontos; treino pendente | [ops/training/v2/manifest.json](../../ops/training/v2/manifest.json) |

Cada versão fica em `ops/training/<versão>/` (dados + manifesto). Os adapters ficam em `~/.local/mlx-adapters/`, fora do repositório.

## Treinar a v2

```bash
python3 -m venv ~/.local/mlx-venv && ~/.local/mlx-venv/bin/pip install mlx-lm   # uma vez
~/.local/mlx-venv/bin/python agent/train/download_base.py                        # uma vez
python3 agent/train/build_dataset.py --version v2                                # confere o hash do manifesto
python3 agent/train/train.py --version v2 --iters 400                            # libere a memória do Ollama antes
AGENT_TODAY=2026-11-18 python3 agent/train/evaluate.py --adapter ~/.local/mlx-adapters/solvis-analyst-v2
```

Antes de treinar com mais força, revise:
- **Iterações:** a v1 viu só 0,35 época e a perda de validação ainda caía.
- **Máquina:** o M1 de 8 GB derrubou o ClickHouse durante a v1. Uma máquina maior evita isso.
- **Comparação:** compare também com o agente no Ollama, que hoje é o melhor (holdout 75%).
