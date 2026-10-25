"""Selección del almacenamiento.

- Si `.streamlit/secrets.toml` (o los secretos de Streamlit Cloud) tienen una
  sección [github] con token y repo → GitHub (rama `data`).
- Si no → carpeta local `local_data/` (modo de prueba).
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from core.config import ROOT
from storage.base import StorageError, Store



def local_dir() -> Path:
    """Carpeta del modo local (se puede cambiar con la variable HMCZ_LOCAL_DIR)."""
    return Path(os.environ.get("HMCZ_LOCAL_DIR", ROOT / "local_data"))


def make_store(secrets: Mapping | None) -> Store:
    gh = secrets.get("github") if secrets else None
    if gh and gh.get("token") and gh.get("repo"):
        from storage.github_store import GitHubStore

        return GitHubStore(gh["token"], gh["repo"], gh.get("branch", "data"))
    from storage.local_store import LocalStore

    return LocalStore(local_dir())


__all__ = ["Store", "StorageError", "make_store", "local_dir"]
