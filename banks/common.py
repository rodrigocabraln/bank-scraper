"""
Utilidades compartidas para los scrapers de bancos.

Este módulo contiene funciones comunes utilizadas por todos los módulos
de scraping, incluyendo:
- Manejo de timezone y fechas
- Lectura y desencriptación de credenciales
- Normalización de monedas
- Parseo de montos en formato uruguayo

Todas las funciones están diseñadas para ser importadas por los módulos
específicos de cada banco (brou_personas.py, oca.py, etc.).
"""
from __future__ import annotations

import os
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from cryptography.fernet import Fernet, InvalidToken


# =============================================================================
# CONFIGURACIÓN DE TIMEZONE
# =============================================================================

DEFAULT_TIMEZONE = "America/Montevideo"
"""Timezone por defecto si no se especifica TZ en el entorno."""

# Constante legacy para compatibilidad (usar get_timezone() para nuevo código)
UY_TZ = timezone(timedelta(hours=-3))


def get_timezone() -> timezone:
    """
    Obtiene el timezone configurado desde la variable de entorno TZ.
    
    Intenta usar ZoneInfo para soporte completo de DST (horario de verano).
    Si el timezone no es válido, retorna UTC-3 como fallback.
    
    Returns:
        timezone: Objeto timezone para usar con datetime.
        
    Example:
        >>> tz = get_timezone()
        >>> datetime.now(tz).isoformat()
        '2026-01-30T22:30:00-03:00'
    """
    tz_name = os.environ.get("TZ", DEFAULT_TIMEZONE)
    try:
        return ZoneInfo(tz_name)
    except Exception:
        # Fallback a UTC-3 si el timezone no es válido
        return timezone(timedelta(hours=-3))


def now_iso() -> str:
    """
    Retorna la fecha/hora actual en formato ISO 8601 con timezone.
    
    Usa el timezone configurado en la variable de entorno TZ.
    El formato incluye segundos pero no microsegundos.
    
    Returns:
        str: Timestamp en formato ISO (ej: "2026-01-30T22:30:00-03:00")
    """
    return datetime.now(get_timezone()).isoformat(timespec="seconds")


# =============================================================================
# MANEJO DE CREDENCIALES
# =============================================================================

def read_credential(name: str) -> str:
    """
    Lee un secreto desde el directorio de credenciales.
    
    Busca un archivo con el nombre especificado en el directorio
    definido por la variable de entorno CREDENTIALS_DIRECTORY.
    
    Args:
        name: Nombre del archivo de credencial a leer.
        
    Returns:
        str: Contenido del archivo, o cadena vacía si no existe.
        
    Note:
        Esta función no lanza excepciones si el archivo no existe.
        Para requerir que exista, usar require_credential().
    """
    cred_dir = os.environ.get("CREDENTIALS_DIRECTORY")
    if not cred_dir:
        return ""
    p = Path(cred_dir) / name
    if not p.exists():
        return ""
    return p.read_text(encoding="utf-8").strip()


def require_credential(name: str) -> str:
    """
    Lee un secreto o lanza error si no existe.
    
    Wrapper de read_credential() que garantiza que la credencial existe.
    
    Args:
        name: Nombre del archivo de credencial a leer.
        
    Returns:
        str: Contenido del archivo de credencial.
        
    Raises:
        RuntimeError: Si el archivo no existe o está vacío.
    """
    v = read_credential(name)
    if not v:
        raise RuntimeError(f"Falta el credential requerido: {name}")
    return v


def decrypt_fernet(encrypted_data: str, *, env_key_name: str = "CREDS_KEY") -> str:
    """
    Descifra credenciales usando Fernet (AES-128-CBC + HMAC).
    
    Fernet proporciona cifrado autenticado, garantizando tanto
    confidencialidad como integridad de los datos.
    
    Args:
        encrypted_data: Datos cifrados en formato Fernet (URL-safe base64).
        env_key_name: Nombre de la variable de entorno con la clave.
                      Por defecto "CREDS_KEY".
    
    Returns:
        str: Texto descifrado (típicamente JSON con credenciales).
    
    Raises:
        RuntimeError: Si falta la clave, es inválida, o el descifrado falla.
        
    Example:
        >>> raw = require_credential("brou_personas_creds")
        >>> json_text = decrypt_fernet(raw)
        >>> creds = json.loads(json_text)
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


# =============================================================================
# NORMALIZACIÓN DE DATOS
# =============================================================================

def normalize_currency(
    raw: str, 
    output_format: Literal["symbol", "code"] = "symbol"
) -> str:
    """
    Normaliza textos de moneda a un formato estándar.
    
    Soporta múltiples formatos de entrada para las monedas más comunes
    en Uruguay (UYU, USD) y las convierte a un formato consistente.
    
    Args:
        raw: Texto de moneda en cualquier formato.
             Ejemplos: "USD", "U$S", "$", "Pesos", "Dólares", "€"
        output_format: Formato de salida deseado.
            - "symbol": Retorna símbolos ($, U$S, €)
            - "code": Retorna códigos en minúscula (uyu, usd, eur)
    
    Returns:
        str: Moneda normalizada según el formato especificado.
        
    Examples:
        >>> normalize_currency("Dólares")
        'U$S'
        >>> normalize_currency("USD", output_format="code")
        'usd'
        >>> normalize_currency("Pesos")
        '$'
    """
    s = (raw or "").upper().strip()
    
    # Mapeo de patrones a (lista_patrones, símbolo, código)
    currency_mapping = {
        "usd": (["USD", "U$S", "US$", "DÓLARES", "DOLARES"], "U$S", "usd"),
        "uyu": (["UYU", "$", "PESOS"], "$", "uyu"),
        "eur": (["EUR", "€", "EUROS"], "€", "eur"),
    }
    
    for patterns, symbol, code in currency_mapping.values():
        if any(p in s for p in patterns):
            return code if output_format == "code" else symbol
    
    # Default: pesos uruguayos (moneda más común en los bancos soportados)
    if not s:
        return "uyu" if output_format == "code" else "$"
    
    # Si no matchea ningún patrón conocido, retornar el original
    return raw.lower() if output_format == "code" else raw


def parse_amount(raw: str) -> dict[str, Any]:
    """
    Parsea montos monetarios a un diccionario con valor raw y numérico.
    
    Soporta el formato uruguayo (1.234,56) donde el punto es separador
    de miles y la coma es separador decimal. También detecta y maneja
    el formato americano (1,234.56) automáticamente.
    
    Args:
        raw: String con el monto en cualquier formato.
             Ejemplos: "1.234,56", "$ 5,40", "US$ 100,00", "1234.56"
    
    Returns:
        dict: Diccionario con dos claves:
            - "raw": String original sin modificar
            - "number": Valor numérico como float, o None si no se pudo parsear
    
    Examples:
        >>> parse_amount("$ 1.234,56")
        {'raw': '$ 1.234,56', 'number': 1234.56}
        
        >>> parse_amount("US$ 100,00")
        {'raw': 'US$ 100,00', 'number': 100.0}
        
        >>> parse_amount("")
        {'raw': '', 'number': None}
    """
    s = (raw or "").strip()
    if not s:
        return {"raw": raw, "number": None}
    
    try:
        # Extraer solo dígitos, puntos y comas usando regex
        match = re.search(r"[\d.,]+", s)
        if not match:
            return {"raw": raw, "number": None}
        
        num_str = match.group()
        
        # Detectar formato basándose en la posición de coma vs punto
        if "," in num_str and "." in num_str:
            # Ambos separadores presentes: determinar cuál es el decimal
            if num_str.rfind(",") > num_str.rfind("."):
                # Coma después del punto → formato uruguayo (1.234,56)
                num_str = num_str.replace(".", "").replace(",", ".")
            else:
                # Punto después de la coma → formato americano (1,234.56)
                num_str = num_str.replace(",", "")
        elif "," in num_str:
            # Solo coma: asumimos formato uruguayo (coma = decimal)
            num_str = num_str.replace(",", ".")
        # Si solo tiene punto, se interpreta como decimal directamente
        
        return {"raw": raw, "number": float(num_str)}
    except Exception:
        return {"raw": raw, "number": None}
