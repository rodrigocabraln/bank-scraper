#!/usr/bin/env python3
"""
Utilidad de configuración de credenciales para Bank Scraper.

Este script permite configurar las credenciales de acceso a los bancos
de forma interactiva y segura. Las credenciales se cifran usando Fernet
(AES-128-CBC + HMAC) antes de guardarse.

Características:
    - Menú interactivo para seleccionar bancos
    - Cifrado Fernet de credenciales
    - Validación de campos (patrones, longitud mínima)
    - Soporte para instalación sin virtualenv (usa AST para leer metadatos)
    - Escritura con permisos seguros (600)

Uso:
    # Generar una nueva clave Fernet
    python setup.py --generate-key
    
    # Configurar credenciales de un banco
    python setup.py
    
    # En Docker
    docker compose exec bank-scraper python setup.py

Requisitos:
    - CREDS_KEY debe estar configurada en .env
    - CREDENTIALS_DIRECTORY define dónde se guardan las credenciales
"""
from __future__ import annotations

import ast
import getpass
import json
import os
import pkgutil
import re
import subprocess
import sys
from pathlib import Path

from cryptography.fernet import Fernet


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

PROJECT_ROOT = Path(__file__).resolve().parent
"""Directorio raíz del proyecto."""

BANKS_PKG = "banks"
"""Nombre del paquete que contiene los módulos de bancos."""

CREDSTORE_DIR = Path(os.getenv("CREDENTIALS_DIRECTORY", "/etc/credstore/bank_scraper"))
"""Directorio donde se guardan las credenciales cifradas."""


# =============================================================================
# UTILIDADES DE ENTORNO
# =============================================================================

def load_env_simple(env_path: Path) -> None:
    """
    Carga variables de entorno desde un archivo .env simple.
    
    Parser minimalista que no depende de python-dotenv.
    Solo establece variables que no existen en el entorno.
    
    Args:
        env_path: Ruta al archivo .env
    """
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def require_env(name: str) -> str:
    """
    Obtiene una variable de entorno requerida.
    
    Args:
        name: Nombre de la variable.
        
    Returns:
        str: Valor de la variable.
        
    Raises:
        SystemExit: Si la variable no existe o está vacía.
    """
    v = (os.environ.get(name) or "").strip()
    if not v:
        raise SystemExit(f"Falta {name} en .env")
    return v


# =============================================================================
# FUNCIONES DE CIFRADO FERNET
# =============================================================================

def generate_fernet_key() -> str:
    """
    Genera una nueva clave Fernet.
    
    La clave es URL-safe base64 de 32 bytes, compatible con
    el algoritmo AES-128-CBC.
    
    Returns:
        str: Clave Fernet como string.
    """
    return Fernet.generate_key().decode("utf-8")


def validate_fernet_key(key: str) -> bool:
    """
    Verifica si una clave es válida para Fernet.
    
    Args:
        key: Clave a validar.
        
    Returns:
        bool: True si la clave es válida, False si no.
    """
    try:
        Fernet(key.encode("utf-8"))
        return True
    except (ValueError, TypeError):
        return False


def encrypt_fernet(text: str, key: str) -> str:
    """
    Cifra texto usando Fernet (AES-128-CBC + HMAC).
    
    Args:
        text: Texto a cifrar.
        key: Clave Fernet.
        
    Returns:
        str: Texto cifrado como string URL-safe base64.
        
    Raises:
        SystemExit: Si la clave no es válida.
    """
    if not validate_fernet_key(key):
        raise SystemExit(
            "\n❌ ERROR: CREDS_KEY no es una clave Fernet válida.\n\n"
            "Las claves Fernet deben ser generadas con el comando:\n"
            "  python setup.py --generate-key\n\n"
            "Luego, copia la clave generada a tu archivo .env"
        )
    cipher = Fernet(key.encode("utf-8"))
    return cipher.encrypt(text.encode("utf-8")).decode("utf-8")


# =============================================================================
# DESCUBRIMIENTO DE BANCOS
# =============================================================================

def list_bank_modules() -> list[str]:
    """
    Lista los módulos de banco disponibles en banks/.
    
    Excluye módulos internos (common, __init__) y paquetes.
    
    Returns:
        list[str]: Lista ordenada de nombres de módulos.
        
    Raises:
        SystemExit: Si no existe la carpeta banks/.
    """
    pkg_path = PROJECT_ROOT / BANKS_PKG
    if not pkg_path.exists():
        raise SystemExit(f"No existe carpeta {BANKS_PKG}/ en {PROJECT_ROOT}")
    mods = []
    for m in pkgutil.iter_modules([str(pkg_path)]):
        if m.ispkg:
            continue
        if m.name.startswith("_") or m.name in ("common", "__init__", "bank_template"):
            continue
        mods.append(m.name)
    return sorted(mods)


def load_bank_metadata(bank_module: str) -> tuple[str, list[dict]]:
    """
    Lee BANK_KEY y CREDENTIAL_FIELDS desde un módulo de banco.
    
    Usa AST para parsear el archivo sin importarlo, evitando
    dependencias de selenium/venv.
    
    Args:
        bank_module: Nombre del módulo (sin extensión).
        
    Returns:
        tuple: (bank_key, credential_fields)
        
    Raises:
        SystemExit: Si el archivo no existe o no define CREDENTIAL_FIELDS.
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


# =============================================================================
# INTERFAZ DE USUARIO
# =============================================================================

def print_header() -> None:
    """Imprime la cabecera del programa."""
    print("\n" + "═" * 45)
    print("   🏦  BANK SCRAPER - Configuración de Credenciales")
    print("═" * 45)


def pick_bank(mods: list[str]) -> str | None:
    """
    Muestra menú de bancos y retorna el seleccionado.
    
    Args:
        mods: Lista de módulos de banco disponibles.
        
    Returns:
        str: Nombre del módulo seleccionado, o None para salir.
    """
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


def prompt_fields_from_metadata(bank_key: str, fields: list[dict]) -> dict:
    """
    Solicita al usuario los valores para cada campo de credencial.
    
    Valida patrones regex y longitud mínima si están definidos.
    Usa getpass para campos secretos.
    
    Args:
        bank_key: Identificador del banco (para mostrar en pantalla).
        fields: Lista de definiciones de campos con name, prompt, etc.
        
    Returns:
        dict: Diccionario con los valores ingresados.
    """
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


# =============================================================================
# ESCRITURA DE CREDENCIALES
# =============================================================================

def write_credstore_file(path: Path, content: str) -> None:
    """
    Escribe un archivo de credencial con permisos seguros.
    
    Intenta escritura directa primero. Si falla por permisos,
    usa sudo si está disponible.
    
    Args:
        path: Ruta donde guardar el archivo.
        content: Contenido cifrado a guardar.
        
    Raises:
        PermissionError: Si no hay permisos y sudo no está disponible.
    """
    # Intentar escritura directa
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        path.chmod(0o600)
        return
    except PermissionError:
        pass

    # Intentar con sudo
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
        raise PermissionError(
            f"No tengo permisos para escribir en {path} y 'sudo' no está instalado. "
            "Si estás en Docker, prueba correr con '--user 0'."
        )


# =============================================================================
# LÓGICA PRINCIPAL
# =============================================================================

def configure_bank(mods: list[str], key: str) -> bool:
    """
    Configura las credenciales de un banco.
    
    Muestra el menú, solicita credenciales, las cifra y guarda.
    
    Args:
        mods: Lista de módulos de banco disponibles.
        key: Clave Fernet para cifrado.
        
    Returns:
        bool: True si se configuró un banco, False si el usuario salió.
    """
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
    """
    Punto de entrada principal.
    
    Carga el entorno, valida CREDS_KEY, y entra en el loop
    del menú de configuración.
    """
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


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

if __name__ == "__main__":
    # Subcomando para generar clave
    if len(sys.argv) > 1 and sys.argv[1] == "--generate-key":
        print("\n🔑 Nueva CREDS_KEY generada:")
        print("─" * 45)
        print(generate_fernet_key())
        print("─" * 45)
        print("📋 Copia esta clave a tu archivo .env\n")
        sys.exit(0)
    
    main()
