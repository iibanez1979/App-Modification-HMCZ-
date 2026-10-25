"""Genera el hash bcrypt de una contraseña (para el administrador de emergencia).

    python scripts/hash_password.py
"""

from getpass import getpass

import bcrypt

pw = getpass("Contraseña: ")
if len(pw) < 8:
    raise SystemExit("La contraseña debe tener al menos 8 caracteres.")
if pw != getpass("Repite la contraseña: "):
    raise SystemExit("Las contraseñas no coinciden.")
print("\npassword_hash = \"" + bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=12)).decode() + "\"")
