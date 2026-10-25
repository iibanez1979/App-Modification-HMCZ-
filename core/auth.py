"""Usuarios de la app.

- Se guardan en `users/users.json` (rama `data`) con la contraseña cifrada con
  bcrypt: nadie, ni siquiera quien vea el archivo, puede leer las contraseñas.
- Los usuarios los crea y modifica el dueño de la app con
  `scripts/users.py` (desde la terminal); la app no tiene gestión de usuarios.
- Un usuario que deja el proyecto se desactiva (no se borra) para conservar su
  historial.
- Usuario maestro: definido en los secretos del servidor (fuera del
  repositorio). Puede usar las vistas de administrador y de supervisor.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import datetime, timezone

import bcrypt

USERS_PATH = "users/users.json"
MIN_PASSWORD = 8
USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,30}$")
MASTER_ROLE = "master"


@dataclass
class User:
    username: str
    name: str
    role: str  # "admin" | "supervisor" | "master" (solo el usuario maestro de los secretos)
    hash: str = ""
    active: bool = True
    updated: str = ""

    @property
    def is_admin(self) -> bool:
        return self.role == "admin"

    @property
    def is_master(self) -> bool:
        return self.role == MASTER_ROLE


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def check_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), hashed.encode())
    except (ValueError, TypeError):
        return False


def validate_new(username: str, password: str, existing: dict[str, User] | None = None) -> str | None:
    """Devuelve una clave de error de i18n, o None si todo está bien."""
    if not USERNAME_RE.match(username):
        return "err_username"
    if existing is not None and username in existing:
        return "err_user_exists"
    if len(password) < MIN_PASSWORD:
        return "err_password_short"
    return None


def load_users(snapshot: Mapping[str, bytes]) -> dict[str, User]:
    raw = snapshot.get(USERS_PATH)
    if not raw:
        return {}
    data = json.loads(raw)
    return {u["username"]: User(**u) for u in data.get("users", [])}


def dump_users(users: dict[str, User]) -> bytes:
    payload = {"users": [asdict(u) for u in sorted(users.values(), key=lambda u: u.username)]}
    return json.dumps(payload, ensure_ascii=False, indent=2).encode()


def stamp(user: User) -> User:
    user.updated = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return user


def master_account(secrets: Mapping | None) -> User | None:
    """Usuario maestro definido en la sección [master] de los secretos, si existe."""
    sec = secrets.get("master") if secrets else None
    if sec and sec.get("username") and sec.get("password_hash"):
        username = str(sec["username"]).strip().lower()
        return User(username, str(sec.get("name") or username), MASTER_ROLE, str(sec["password_hash"]))
    return None


def authenticate(users: dict[str, User], username: str, password: str, master: User | None = None) -> User | None:
    username = username.strip().lower()
    if master and username == master.username:  # el maestro nunca se toma del archivo de usuarios
        return master if check_password(password, master.hash) else None
    user = users.get(username)
    if user and user.active and check_password(password, user.hash):
        return user
    return None
