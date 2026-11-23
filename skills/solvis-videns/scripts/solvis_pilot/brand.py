"""Perfil de marca do cliente: guarda, na pasta de trabalho, o que a skill aprendeu dos materiais de referência
(manual da marca, site, logo, modelos de relatório) para que relatórios e decks saiam com a cara do cliente.

O perfil é um JSON livre escrito pela skill a partir do que o usuário forneceu; o motor só guarda e devolve.
Nenhum número passa por aqui. Os arquivos (logo, fontes, modelos) são copiados para a mesma pasta.
"""

from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, List

from .config import data_dir, ensure_data_dir, _private_dir
from .errors import EngineError
from .store import now_utc

PROFILE_NAME = "profile.json"
MAX_PROFILE_BYTES = 256 * 1024
MAX_ASSET_BYTES = 25 * 1024 * 1024
# chaves que a skill costuma preencher; outras são aceitas
SUGGESTED_KEYS = ("client_name", "sources", "colors", "fonts", "logo", "tone", "terms", "templates", "notes")


def brand_dir() -> Path:
    custom = os.environ.get("SOLVIS_BRAND_DIR")
    return Path(custom) if custom else data_dir() / "brand"


def _profile_path() -> Path:
    return brand_dir() / PROFILE_NAME


def _read_profile() -> Dict[str, Any]:
    try:
        data = json.loads(_profile_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _ensure_dir() -> Path:
    if brand_dir().parent == data_dir():
        ensure_data_dir()
    return _private_dir(brand_dir())


def _write_profile(profile: Dict[str, Any]) -> None:
    _ensure_dir()
    profile["updated_at"] = now_utc()
    _profile_path().write_text(json.dumps(profile, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _assets() -> List[Dict[str, Any]]:
    root = brand_dir()
    if not root.is_dir():
        return []
    return sorted(
        ({"file": p.name, "path": str(p), "bytes": p.stat().st_size}
         for p in root.iterdir() if p.is_file() and p.name != PROFILE_NAME),
        key=lambda a: a["file"],
    )


def status() -> Dict[str, Any]:
    """Resumo para `setup`/`scope`: `configured` (há perfil), `none` (o usuário disse não ter materiais), `not_asked`."""
    profile = _read_profile()
    if profile.get("none"):
        st = "none"
    elif profile:
        st = "configured"
    else:
        st = "not_asked"
    return {"status": st, "file": str(_profile_path())}


def cmd_brand(args, _ctx) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    if args.clear:
        root = brand_dir()
        if root.exists():
            shutil.rmtree(root)
        out["cleared"] = True
    if args.none:
        _write_profile({"none": True, "note": "O usuário disse não ter materiais de referência; use o estilo neutro."})
        out["saved"] = True
    if args.file:
        raw = sys.stdin.read() if args.file == "-" else Path(args.file).read_text(encoding="utf-8")
        if len(raw.encode("utf-8")) > MAX_PROFILE_BYTES:
            raise EngineError("invalid_argument", "Perfil de marca acima de 256 KB.")
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise EngineError("invalid_argument", f"Perfil de marca não é JSON válido: {exc}")
        if not isinstance(data, dict):
            raise EngineError("invalid_argument", "O perfil de marca precisa ser um objeto JSON.")
        data.pop("none", None)
        current = _read_profile()
        if current.get("none"):      # "sem materiais" deixa de valer quando chega um perfil
            current = {}
        current.update(data)
        _write_profile(current)
        out["saved"] = True
    for src in args.asset or []:
        path = Path(src)
        if not path.is_file():
            raise EngineError("invalid_argument", f"Arquivo não encontrado: {src}")
        if path.stat().st_size > MAX_ASSET_BYTES:
            raise EngineError("invalid_argument", f"Arquivo acima de 25 MB: {src}")
        _ensure_dir()
        dest = brand_dir() / path.name
        if dest.resolve() != path.resolve():
            shutil.copy2(path, dest)
        profile = _read_profile()
        profile.pop("none", None)
        assets = profile.setdefault("assets", [])
        if path.name not in assets:
            assets.append(path.name)
        _write_profile(profile)
        out.setdefault("copied", []).append(str(dest))
    out.update(status())
    out["profile"] = _read_profile()
    out["assets"] = _assets()
    out["suggested_keys"] = list(SUGGESTED_KEYS)
    return out
