#!/usr/bin/env python3
"""Ponto de entrada do motor da skill. Uso: python scripts/solvis.py <comando> [opções]

Requer Python 3.9+ e nenhuma dependência externa. Veja references/cli.md.
"""

import os
import sys

if sys.version_info < (3, 9):
    sys.stdout.write('{"error": {"code": "python_too_old", "message": "O motor exige Python 3.9 ou mais novo."}}\n')
    sys.exit(2)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from solvis_pilot.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
