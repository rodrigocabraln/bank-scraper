from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken

# --- Timezone ---
DEFAULT_TIMEZONE = "America/Montevideo"


def get_timezone() -> timezone:
    """
    Obtiene el timezone configurado desde la variable de entorno TZ.
    
    Returns:
        timezone object para usar con datetime.
    """
    tz_name = os.environ.get("TZ", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(tz_name)
    except Exception:
        # Fallback a UTC-3 si el timezone no es válido
        return timezone(timedelta(hours=-3))


def now_iso() -> str:
    """Retorna la fecha/hora actual en formato ISO con el timezone configurado."""
    return datetime.now(get_timezone()).isoformat(timespec="seconds")


# Constante legacy para compatibilidad (usar get_timezone() para nuevo código)
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


def normalize_currency(
    raw: str, 
    output_format: Literal["symbol", "code"] = "symbol"
) -> str:
    """
    Normaliza textos de moneda a un formato estándar.
    
    Args:
        raw: Texto de moneda (ej: "USD", "U$S", "$", "Pesos").
        output_format: 
            - "symbol": Retorna símbolos ($, U$S, €)
            - "code": Retorna códigos en minúscula (uyu, usd, eur)
    
    Returns:
        Moneda normalizada según el formato especificado.
    """
    s = (raw or "").upper().strip()
    
    # Mapeo de patrones a (símbolo, código)
    currency_mapping = {
        "usd": (["USD", "U$S", "US$", "DÓLARES", "DOLARES"], "U$S", "usd"),
        "uyu": (["UYU", "$", "PESOS"], "$", "uyu"),
        "eur": (["EUR", "€", "EUROS"], "€", "eur"),
    }
    
    for patterns, symbol, code in currency_mapping.values():
        if any(p in s for p in patterns):
            return code if output_format == "code" else symbol
    
    # Default: pesos uruguayos (moneda más común)
    if not s:
        return "uyu" if output_format == "code" else "$"
    
    # Si no matchea, retornar el original en el formato apropiado
    return raw.lower() if output_format == "code" else raw


def parse_amount(raw: str) -> dict[str, Any]:
    """
    Parsea montos en formato uruguayo (1.234,56) a un diccionario con raw y number.
    
    También soporta formatos como "$ 5,40" o "US$ 1.234,56", extrayendo solo el número.
    
    Args:
        raw: String con el monto (ej: "1.234,56", "$ 5,40", "US$ 100,00").
    
    Returns:
        Dict con {"raw": str_original, "number": float_o_None}
    """
    s = (raw or "").strip()
    if not s:
        return {"raw": raw, "number": None}
    
    try:
        # Extraer solo el número usando regex (quita prefijos de moneda)
        # Matches: 1.234,56 or 1234,56 or 1234.56 or plain numbers
        match = re.search(r"[\d.,]+", s)
        if not match:
            return {"raw": raw, "number": None}
        
        num_str = match.group()
        
        # Detectar formato: si tiene coma como decimal (uruguayo) o punto (americano)
        # Formato uruguayo: 1.234,56 (punto = miles, coma = decimal)
        # Formato americano: 1,234.56 (coma = miles, punto = decimal)
        
        if "," in num_str and "." in num_str:
            # Ambos presentes: determinar cuál es el decimal
            if num_str.rfind(",") > num_str.rfind("."):
                # Coma después del punto: formato uruguayo (1.234,56)
                num_str = num_str.replace(".", "").replace(",", ".")
            else:
                # Punto después de la coma: formato americano (1,234.56)
                num_str = num_str.replace(",", "")
        elif "," in num_str:
            # Solo coma: asumimos formato uruguayo (coma = decimal)
            num_str = num_str.replace(",", ".")
        # Si solo tiene punto, se usa directamente
        
        return {"raw": raw, "number": float(num_str)}
    except Exception:
        return {"raw": raw, "number": None}
