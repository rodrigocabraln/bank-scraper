"""
Template de scraper bancario.

Este archivo sirve como plantilla para implementar nuevos scrapers.
NO ES UN MÓDULO FUNCIONAL - es solo una guía de referencia.

Para crear un nuevo scraper:
    1. Copiar este archivo con el nombre del banco (ej: mi_banco.py)
    2. Implementar las constantes requeridas (BANK_KEY, CREDENTIAL_FIELDS, etc.)
    3. Configurar credenciales: python setup.py (seleccionar el nuevo banco)
    4. Implementar las funciones de scraping (login, extract_accounts)
    5. Asegurarse de que run() retorne el formato estándar
    6. Probar con: BANKS=mi_banco python main.py

Requisitos:
    - Cada módulo DEBE definir BANK_KEY y CREDENTIAL_FIELDS
    - Cada módulo DEBE implementar run(driver, env) -> dict
    - El diccionario retornado DEBE tener 'updated_at' y 'accounts'
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .common import (
    require_credential, 
    decrypt_fernet, 
    normalize_currency,
    parse_amount,
    now_iso,
)


# =============================================================================
# CONFIGURACIÓN DEL BANCO (REQUERIDO)
# =============================================================================

BANK_KEY = "mi_banco"
"""
Identificador único del banco.

Usado para:
- Nombre del archivo de credenciales ({BANK_KEY}_creds)
- Tópicos MQTT (homeassistant/sensor/{BANK_KEY}/...)
- Archivo de salida JSON ({BANK_KEY}.json)

Convenciones:
- Usar snake_case
- Evitar caracteres especiales
- Ser descriptivo (ej: brou_personas, oca, santander_uy)
"""

BANK_LOGO = "mi_banco.webp"
"""
Nombre del archivo de logo en bank-logos/.

Formatos soportados: .webp, .png, .jpg
Tamaño recomendado: 256x256 px
"""

CREDENTIAL_FIELDS = [
    # Campo no secreto (se muestra mientras el usuario escribe)
    {"name": "document", "prompt": "Documento", "secret": False},
    
    # Campo secreto (se oculta mientras el usuario escribe, usa getpass)
    {"name": "password", "prompt": "Contraseña", "secret": True},
    
    # Ejemplos de campos opcionales con validación:
    # {"name": "user_id", "prompt": "ID de Usuario", "secret": False, "pattern": r"^\d+$"},
    # {"name": "pin", "prompt": "PIN (4 dígitos)", "secret": True, "min_len": 4, "pattern": r"^\d{4}$"},
]
"""
Campos de credenciales que setup.py pedirá al usuario.

Cada campo es un diccionario con:
- name (str, requerido): Nombre de la clave en el JSON resultante
- prompt (str, requerido): Texto a mostrar al usuario
- secret (bool, requerido): True para ocultar input (contraseñas)
- pattern (str, opcional): Regex para validar formato
- min_len (int, opcional): Longitud mínima del valor
"""

# URL de login del portal
LOGIN_URL = "https://portal.mibanco.com/login"
"""URL de inicio de sesión del portal."""


# =============================================================================
# SELECTORES DOM (AJUSTAR SEGÚN EL SITIO)
# =============================================================================

# Login
SEL_USER_INPUT = (By.NAME, "username")
"""Campo de entrada del usuario/documento."""

SEL_PWD_INPUT = (By.NAME, "password")
"""Campo de entrada de la contraseña."""

SEL_SUBMIT_BTN = (By.CSS_SELECTOR, "button[type='submit']")
"""Botón de envío del formulario."""

# Dashboard / Cuentas
SEL_ACCOUNTS_CONTAINER = (By.ID, "accounts-container")
"""Contenedor principal de cuentas."""

SEL_ACCOUNT_ROWS = (By.CSS_SELECTOR, ".account-row")
"""Selector para cada fila/tarjeta de cuenta."""


# =============================================================================
# CONFIGURACIÓN INTERNA (NO MODIFICAR)
# =============================================================================

REQUIRED_CREDENTIALS = {
    "creds": f"{BANK_KEY}_creds",
}
"""Mapeo de nombres de credenciales. Auto-generado desde BANK_KEY."""


# =============================================================================
# TIPOS DE DATOS
# =============================================================================

@dataclass(frozen=True)
class MiBancoCreds:
    """
    Credenciales de acceso al portal.
    
    Ajustar campos según CREDENTIAL_FIELDS.
    Usar frozen=True para inmutabilidad.
    """
    document: str
    password: str


# =============================================================================
# FUNCIONES INTERNAS
# =============================================================================

def _get_creds() -> MiBancoCreds:
    """
    Obtiene y desencripta las credenciales almacenadas.
    
    Flujo:
        1. Lee archivo cifrado desde CREDENTIALS_DIRECTORY
        2. Desencripta con clave Fernet de CREDS_KEY
        3. Parsea JSON y valida campos requeridos
    
    Returns:
        MiBancoCreds: Objeto con las credenciales.
        
    Raises:
        RuntimeError: Si el archivo no existe, JSON inválido,
                      o faltan campos requeridos.
    """
    raw = require_credential(REQUIRED_CREDENTIALS["creds"])
    json_text = decrypt_fernet(raw)
    
    try:
        obj = json.loads(json_text)
    except Exception as e:
        raise RuntimeError(f"JSON inválido en {REQUIRED_CREDENTIALS['creds']}: {e}")

    # Extraer campos (ajustar según CREDENTIAL_FIELDS)
    doc = (obj.get("document") or "").strip()
    pwd = (obj.get("password") or "").strip()
    
    if not doc or not pwd:
        raise RuntimeError("Faltan campos document/password en las credenciales")
    
    return MiBancoCreds(document=doc, password=pwd)


# =============================================================================
# FUNCIONES DE SCRAPING
# =============================================================================

def login(driver: WebDriver, wait: WebDriverWait, creds: MiBancoCreds) -> None:
    """
    Realiza el proceso de autenticación.
    
    Pasos típicos:
        1. Navegar a la URL de login
        2. Esperar campos del formulario
        3. Completar credenciales
        4. Enviar formulario
        5. Esperar indicador de login exitoso
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        wait: WebDriverWait configurado con timeout.
        creds: Credenciales de acceso.
        
    Raises:
        TimeoutException: Si algún elemento no aparece a tiempo.
        NoSuchElementException: Si un selector está mal.
    """
    driver.get(LOGIN_URL)

    # Completar campo usuario/documento
    user_input = wait.until(EC.presence_of_element_located(SEL_USER_INPUT))
    user_input.clear()
    user_input.send_keys(creds.document)

    # Completar campo contraseña
    pwd_input = wait.until(EC.presence_of_element_located(SEL_PWD_INPUT))
    pwd_input.clear()
    pwd_input.send_keys(creds.password)

    # Enviar formulario
    submit_btn = wait.until(EC.element_to_be_clickable(SEL_SUBMIT_BTN))
    submit_btn.click()

    # IMPORTANTE: Esperar algún indicador de que el login fue exitoso
    # Ejemplos:
    #   wait.until(EC.presence_of_element_located((By.ID, "dashboard")))
    #   wait.until(EC.url_contains("/home"))
    #   wait.until(EC.invisibility_of_element_located((By.ID, "login-form")))
    pass


def extract_accounts(driver: WebDriver, wait: WebDriverWait) -> list[dict]:
    """
    Extrae información de cuentas.
    
    Pasos típicos:
        1. Esperar a que cargue el contenedor de cuentas
        2. Iterar sobre cada cuenta/tarjeta
        3. Extraer: número, moneda, saldo, disponible
        4. Normalizar datos con funciones de common.py
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        wait: WebDriverWait configurado con timeout.
        
    Returns:
        Lista de diccionarios con formato estándar:
        - type: "ACCOUNT" o "CREDIT_CARD"
        - currency: "UYU", "USD", "EUR", etc.
        - account_number: Identificador de la cuenta
        - balance: {"raw": str, "number": float|None}
        - available: {"raw": str|None, "number": float|None}
        - logo: Nombre del archivo de logo
    """
    accounts = []
    
    # Esperar contenedor
    container = wait.until(EC.presence_of_element_located(SEL_ACCOUNTS_CONTAINER))
    
    # Obtener filas de cuentas
    rows = container.find_elements(*SEL_ACCOUNT_ROWS)
    
    for row in rows:
        try:
            # EJEMPLO: Ajustar selectores según el sitio
            # acc_number = row.find_element(By.CLASS_NAME, "account-number").text
            # currency_text = row.find_element(By.CLASS_NAME, "currency").text
            # balance_text = row.find_element(By.CLASS_NAME, "balance").text
            
            # Datos de ejemplo (REEMPLAZAR)
            acc_number = "Cuenta 12345"
            currency_text = "Pesos"
            balance_text = "1.234,56"
            
            # Normalizar datos usando funciones de common.py
            balance_obj = parse_amount(balance_text)
            
            accounts.append({
                "type": "ACCOUNT",
                "currency": normalize_currency(currency_text),
                "account_number": acc_number,
                "balance": balance_obj,
                "available": balance_obj,  # O extraer por separado si aplica
                "logo": BANK_LOGO,
            })
        except Exception:
            # Loguear error pero continuar con otras cuentas
            continue
    
    return accounts


# =============================================================================
# PUNTO DE ENTRADA (REQUERIDO)
# =============================================================================

def run(driver: WebDriver, env: dict[str, str]) -> dict:
    """
    Punto de entrada principal del scraper.
    
    Esta función es llamada por main.py. DEBE seguir esta firma exacta.
    
    Args:
        driver: Instancia del WebDriver de Selenium (Firefox/Chrome).
        env: Variables de entorno del sistema (dict).
        
    Returns:
        Diccionario con formato estándar:
        {
            "updated_at": "2024-01-15T10:30:00-03:00",  # ISO 8601
            "accounts": [
                {
                    "type": "ACCOUNT",
                    "currency": "UYU",
                    "account_number": "CA 12345-001",
                    "balance": {"raw": "$ 1.234,56", "number": 1234.56},
                    "available": {"raw": "$ 1.234,56", "number": 1234.56},
                    "logo": "mi_banco.webp"
                },
                ...
            ]
        }
    """
    creds = _get_creds()
    wait = WebDriverWait(driver, 45)  # Timeout en segundos

    # 1. Autenticación
    login(driver, wait, creds)

    # 2. Extracción de datos
    accounts = extract_accounts(driver, wait)

    # 3. Retornar en formato estándar
    return {
        "updated_at": now_iso(),
        "accounts": accounts,
    }
