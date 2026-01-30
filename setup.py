#!/usr/bin/env python3
from __future__ import annotations

import getpass
import importlib
import json
import os
import pkgutil
import subprocess
import sys
from pathlib import Path
import re
import ast

from cryptography.fernet import Fernet


PROJECT_ROOT = Path(__file__).resolve().parent
BANKS_PKG = "banks"
CREDSTORE_DIR = Path(os.getenv("CREDENTIALS_DIRECTORY", "/etc/credstore/bank_scraper"))


def load_env_simple(env_path: Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def require_env(name: str) -> str:
    v = (os.environ.get(name) or "").strip()
    if not v:
        raise SystemExit(f"Falta {name} en .env")
    return v


def generate_fernet_key() -> str:
    """Genera una nueva clave Fernet (URL-safe base64, 32 bytes)."""
    return Fernet.generate_key().decode("utf-8")


def validate_fernet_key(key: str) -> bool:
    """Verifica si una clave es válida para Fernet."""
    try:
        Fernet(key.encode("utf-8"))
        return True
    except (ValueError, TypeError):
        return False


def encrypt_fernet(text: str, key: str) -> str:
    """Cifra texto usando Fernet (AES-128-CBC + HMAC)."""
    if not validate_fernet_key(key):
        raise SystemExit(
            "\n❌ ERROR: CREDS_KEY no es una clave Fernet válida.\n\n"
            "Las claves Fernet deben ser generadas con el comando:\n"
            "  python setup.py --generate-key\n\n"
            "Luego, copia la clave generada a tu archivo .env"
        )
    cipher = Fernet(key.encode("utf-8"))
    return cipher.encrypt(text.encode("utf-8")).decode("utf-8")


def list_bank_modules() -> list[str]:
    pkg_path = PROJECT_ROOT / BANKS_PKG
    if not pkg_path.exists():
        raise SystemExit(f"No existe carpeta {BANKS_PKG}/ en {PROJECT_ROOT}")
    mods = []
    for m in pkgutil.iter_modules([str(pkg_path)]):
        if m.ispkg:
            continue
        if m.name.startswith("_") or m.name in ("common", "__init__"):
            continue
        mods.append(m.name)
    return sorted(mods)


def pick_bank(mods: list[str]) -> str | None:
    """Muestra menú de bancos y retorna el seleccionado o None para salir."""
    print("\n┌─────────────────────────────────────┐")
    print("│       📋 BANCOS DISPONIBLES         │")
    print("├─────────────────────────────────────┤")
    for i, m in enumerate(mods, start=1):
        print(f"│   {i}) {m:<30} │")
    print("├─────────────────────────────────────┤")
    print("│   0) Salir                          │")
    print("└─────────────────────────────────────┘")
    
    while True:
        choice = input("\n👉 Seleccione una opción: ").strip()
        if not choice.isdigit():
            print("   ⚠️  Ingrese un número válido")
            continue
        idx = int(choice)
        if idx == 0:
            return None
        if 1 <= idx <= len(mods):
            return mods[idx - 1]
        print(f"   ⚠️  Opción fuera de rango (1-{len(mods)} o 0 para salir)")


def load_bank_metadata(bank_module: str) -> tuple[str, list[dict]]:
    """
    Lee BANK_KEY y CREDENTIAL_FIELDS desde banks/<bank_module>.py sin importarlo.
    Evita depender de selenium/venv.
    """
    path = PROJECT_ROOT / BANKS_PKG / f"{bank_module}.py"
    if not path.exists():
        raise SystemExit(f"No existe: {path}")

    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))

    bank_key = None
    cred_fields = None

    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
            if name == "BANK_KEY":
                bank_key = ast.literal_eval(node.value)
            elif name == "CREDENTIAL_FIELDS":
                cred_fields = ast.literal_eval(node.value)

    if not bank_key:
        bank_key = bank_module
    if not cred_fields:
        raise SystemExit(f"{bank_module}.py no define CREDENTIAL_FIELDS")

    return bank_key, cred_fields


def prompt_fields_from_metadata(bank_key: str, fields: list[dict]) -> dict:
    out: dict = {}
    print(f"\n📝 Configurando: {bank_key}")
    print("─" * 40)
    
    for f in fields:
        name = f["name"]
        prompt = f.get("prompt", name)
        secret = bool(f.get("secret", False))
        pattern = f.get("pattern")
        min_len = f.get("min_len")

        while True:
            if secret:
                val = getpass.getpass(f"   🔒 {prompt}: ").strip()
            else:
                val = input(f"   📄 {prompt}: ").strip()

            if min_len is not None and len(val) < int(min_len):
                print(f"      ⚠️  Valor demasiado corto (mínimo {min_len})")
                continue

            if pattern and not re.match(pattern, val):
                print("      ⚠️  Formato inválido")
                continue

            if not val:
                print("      ⚠️  No puede ser vacío")
                continue

            out[name] = val
            break

    return out

def write_credstore_file(path: Path, content: str) -> None:
    # Intentar escritura directa (si corre como root)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        return
    except PermissionError:
        pass

    # Si no hay permisos, intentamos sudo si existe, sino fallamos con mensaje claro
    import shutil
    if shutil.which("sudo"):
        tmp = Path("/tmp") / f"{path.name}.tmp"
        tmp.write_text(content, encoding="utf-8")
        try:
            subprocess.run(["sudo", "install", "-d", "-m", "700", str(path.parent)], check=True)
            subprocess.run(["sudo", "install", "-m", "600", str(tmp), str(path)], check=True)
        finally:
            try:
                tmp.unlink()
            except Exception:
                pass
    else:
        raise PermissionError(f"No tengo permisos para escribir en {path} y 'sudo' no está instalado. "
                              "Si estás en Docker, prueba correr con '--user 0'.")


def print_header() -> None:
    """Imprime cabecera del programa."""
    print("\n" + "═" * 45)
    print("   🏦  BANK SCRAPER - Configuración de Credenciales")
    print("═" * 45)


def configure_bank(mods: list[str], key: str) -> bool:
    """Configura un banco. Retorna True si se configuró, False si salió."""
    bank_module = pick_bank(mods)
    if bank_module is None:
        return False
    
    bank_key, cred_fields = load_bank_metadata(bank_module)
    payload_obj = prompt_fields_from_metadata(bank_key, cred_fields)

    json_text = json.dumps(payload_obj, separators=(",", ":"))
    encrypted = encrypt_fernet(json_text, key)

    cred_name = f"{bank_key}_creds"
    dest = CREDSTORE_DIR / cred_name

    write_credstore_file(dest, encrypted)
    print(f"\n   ✅ Credential guardado: {dest}")
    
    return True


def main() -> None:
    load_env_simple(PROJECT_ROOT / ".env")
    key = require_env("CREDS_KEY")

    mods = list_bank_modules()
    if not mods:
        raise SystemExit("No hay módulos en banks/ para configurar")

    print_header()
    
    # Loop principal del menú
    while True:
        if not configure_bank(mods, key):
            break
        
        print("\n" + "─" * 45)
    
    print("\n👋 ¡Hasta luego!")
    print("═" * 45 + "\n")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--generate-key":
        print("\n🔑 Nueva CREDS_KEY generada:")
        print("─" * 45)
        print(generate_fernet_key())
        print("─" * 45)
        print("📋 Copia esta clave a tu archivo .env\n")
        sys.exit(0)
    main()

