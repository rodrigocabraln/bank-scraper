from __future__ import annotations

import os
from datetime import timezone, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

UY_TZ = timezone(timedelta(hours=-3))


def read_credential(name: str) -> str:
    """Intenta leer un secreto inyectado (Docker/Variable de Entorno)."""
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if not cred_dir:
        return ""
    p = Path(cred_dir) / name
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def require_credential(name: str) -> str:
    """Lee un secreto o lanza un error si no existe."""
    v = read_credential(name)
    if not v:
        raise RuntimeError(f"Falta el credential requerido: {name}")
    return v


def decrypt_fernet(encrypted_data: str, *, env_key_name: str = "CREDS_KEY") -> str:
    """
    Descifra credenciales usando Fernet (AES-128-CBC + HMAC).
    
    Args:
        encrypted_data: Datos cifrados en formato Fernet (URL-safe base64).
        env_key_name: Variable de entorno con la clave Fernet.
    
    Returns:
        Texto descifrado.
    
    Raises:
        RuntimeError: Si falta la clave o el descifrado falla.
    """
    key = (os.environ.get(env_key_name) or "").encode("utf-8")
    if not key:
        raise RuntimeError(f"Falta la clave {env_key_name} en el archivo .env")

    try:
        cipher = Fernet(key)
        return cipher.decrypt(encrypted_data.encode("utf-8")).decode("utf-8")
    except ValueError:
        raise RuntimeError(
            "CREDS_KEY no es una clave Fernet válida. "
            "Genera una nueva con: python setup.py --generate-key"
        )
    except InvalidToken:
        raise RuntimeError(
            f"No se pudo descifrar el credential. Verificar que CREDS_KEY sea correcta "
            f"y que el credential esté cifrado con la misma clave."
        )
    except Exception as e:
        raise RuntimeError(f"Error al descifrar: {e}")


def normalize_currency(raw: str) -> str:
    """Normaliza los textos de moneda a los símbolos estándar $ y U$S."""
    s = (raw or "").upper()
    # Casos para Dólares
    if any(x in s for x in ["USD", "U$S", "DÓLARES", "DOLARES", "US$"]):
        return "U$S"
    # Por defecto asumimos pesos si tiene $ o menciona UYU o Pesos
    if any(x in s for x in ["UYU", "$", "PESOS"]):
        return "$"
    # Si no coincide nada, retornamos el original o pesos por ser lo más común
    return raw if raw else "$"

