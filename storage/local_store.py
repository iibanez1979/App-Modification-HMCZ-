"""Almacenamiento en una carpeta local (modo de prueba, sin token).

Usa la misma estructura de carpetas que la rama `data` de GitHub, así que lo
que funciona aquí funciona igual en la nube.
"""

from __future__ import annotations

from pathlib import Path

from storage.base import StorageError, Store


class LocalStore(Store):
    def __init__(self, root: Path) -> None:
        super().__init__()
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @property
    def label(self) -> str:
        return f"Local · {self.root.name}/"

    def read_all(self) -> dict[str, bytes]:
        return {
            p.relative_to(self.root).as_posix(): p.read_bytes()
            for p in self.root.rglob("*")
            if p.is_file() and not p.name.startswith(".")
        }

    def _write(self, path: str, content: bytes, message: str) -> None:
        target = (self.root / path).resolve()
        if self.root.resolve() not in target.parents:
            raise StorageError(f"Ruta no permitida: {path}")
        target.parent.mkdir(parents=True, exist_ok=True)
        tmp = target.with_suffix(target.suffix + ".tmp")
        tmp.write_bytes(content)
        tmp.replace(target)
