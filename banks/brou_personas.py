"""
Scraper para BROU Personas (Banco República Oriental del Uruguay).

Este módulo extrae saldos de cuentas desde el portal de e-Banking de BROU.
Soporta cuentas en pesos (UYU) y dólares (USD).

Uso:
    Este módulo es llamado dinámicamente por main.py. No se ejecuta directamente.
    Las credenciales deben configurarse previamente con setup.py.
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
# CONFIGURACIÓN DEL BANCO
# =============================================================================

BANK_KEY = "brou_personas"
"""Identificador único del banco, usado para nombres de archivos y tópicos MQTT."""

BANK_LOGO = "brou.webp"
"""Nombre del archivo de logo (debe existir en bank-logos/)."""

CREDENTIAL_FIELDS = [
    {"name": "document", "prompt": "Documento", "secret": False},
    {"name": "password", "prompt": "Contraseña", "secret": True},
]
"""Campos requeridos por setup.py para configurar las credenciales."""

BROU_URL = "https://ebanking.brou.com.uy/frontend/"
"""URL de inicio de sesión del portal e-Banking."""

# =============================================================================
# SELECTORES DOM
# =============================================================================

SEL_DOC_INPUT = (By.NAME, "document")
"""Campo de entrada del documento de identidad."""

SEL_PWD_INPUT = (By.NAME, "password")
"""Campo de entrada de la contraseña."""

SEL_SUBMIT_BTN = (By.CSS_SELECTOR, "button[type='submit']")
"""Botón de envío del formulario de login."""

SEL_TABLE_CONTAINER = (By.XPATH, "/html/body/div[1]/div[1]/div/div/div/div/div/main/div[1]/div/div/div[2]/section/div/div/div/div/div/div[2]/div[2]")
"""Contenedor principal de la tabla de saldos."""

SEL_TABLE_ROWS = (By.CSS_SELECTOR, "div.table-body a.table-row")
"""Filas de la tabla (cada fila es una cuenta)."""

SEL_TABLE_CELLS = (By.CSS_SELECTOR, "div.table-data")
"""Celdas dentro de cada fila (cuenta, moneda, saldo)."""

REQUIRED_CREDENTIALS = {
    "creds": f"{BANK_KEY}_creds",
}
"""Mapeo de nombres de credenciales requeridas."""


# =============================================================================
# TIPOS DE DATOS
# =============================================================================

@dataclass(frozen=True)
class BrouCreds:
    """Credenciales de acceso al portal BROU."""
    document: str
    password: str


# =============================================================================
# FUNCIONES INTERNAS
# =============================================================================

def _get_creds() -> BrouCreds:
    """
    Obtiene y desencripta las credenciales almacenadas.
    
    Lee el archivo de credenciales cifrado desde CREDENTIALS_DIRECTORY,
    lo desencripta usando la clave Fernet de CREDS_KEY, y parsea el JSON.
    
    Returns:
        BrouCreds: Objeto con documento y contraseña.
        
    Raises:
        RuntimeError: Si el archivo no existe, no es JSON válido,
                      o faltan campos requeridos.
    """
    raw = require_credential(REQUIRED_CREDENTIALS["creds"])
    json_text = decrypt_fernet(raw)

    try:
        obj = json.loads(json_text)
    except Exception as e:
        raise RuntimeError(f"El credential {REQUIRED_CREDENTIALS['creds']} no es un JSON válido: {e}")

    doc = (obj.get("document") or "").strip()
    pwd = (obj.get("password") or "").strip()

    if not doc or not pwd:
        raise RuntimeError(f"El credential {REQUIRED_CREDENTIALS['creds']} debe incluir 'document' y 'password'")

    return BrouCreds(document=doc, password=pwd)


# =============================================================================
# FUNCIONES DE SCRAPING
# =============================================================================

def login(driver: WebDriver, wait: WebDriverWait, creds: BrouCreds) -> None:
    """
    Realiza el proceso de autenticación en el portal BROU.
    
    Navega a la página de login, completa el formulario con las
    credenciales proporcionadas y envía el formulario.
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        wait: WebDriverWait configurado con timeout.
        creds: Credenciales de acceso.
    """
    driver.get(BROU_URL)

    # Esperar y completar campo documento
    doc_input = wait.until(EC.presence_of_element_located(SEL_DOC_INPUT))
    doc_input.clear()
    doc_input.send_keys(creds.document)

    # Esperar y completar campo contraseña
    pwd_input = wait.until(EC.presence_of_element_located(SEL_PWD_INPUT))
    pwd_input.clear()
    pwd_input.send_keys(creds.password)

    # Enviar formulario
    submit_btn = wait.until(EC.element_to_be_clickable(SEL_SUBMIT_BTN))
    submit_btn.click()


def extract_accounts(wait: WebDriverWait) -> list[dict]:
    """
    Extrae información de cuentas desde la tabla de saldos.
    
    Espera a que la tabla de saldos esté visible y cargada,
    luego itera sobre cada fila extrayendo: número de cuenta,
    moneda y saldo disponible.
    
    Args:
        wait: WebDriverWait configurado con timeout.
        
    Returns:
        Lista de diccionarios con la información de cada cuenta:
        - type: Tipo de cuenta ("ACCOUNT")
        - currency: Símbolo de moneda normalizado
        - account_number: Identificador de la cuenta
        - balance: Saldo como objeto {raw, number}
        - available: Disponible como objeto {raw, number}
        - logo: Nombre del archivo de logo
    """
    # Esperar contenedor de tabla
    table_container = wait.until(EC.presence_of_element_located(SEL_TABLE_CONTAINER))
    
    # Esperar a que haya al menos una fila cargada
    wait.until(lambda d: len(table_container.find_elements(*SEL_TABLE_ROWS)) > 0)
    
    rows = table_container.find_elements(*SEL_TABLE_ROWS)
    accounts = []

    for row in rows:
        cells = row.find_elements(*SEL_TABLE_CELLS)
        
        # Validar que la fila tenga las 3 columnas esperadas
        if len(cells) < 3:
            continue

        cuenta_text = cells[0].text.strip()   # Ej: "CA (001234567-00001)"
        moneda_text = cells[1].text.strip()   # Ej: "Pesos" o "Dólares"
        saldo_text = cells[2].text.strip()    # Ej: "1.234,56"

        # En BROU, el saldo mostrado es el disponible
        balance_obj = parse_amount(saldo_text)
        
        accounts.append({
            "type": "ACCOUNT",
            "currency": normalize_currency(moneda_text),
            "account_number": cuenta_text,
            "balance": balance_obj,
            "available": balance_obj,
            "logo": BANK_LOGO,
        })
    
    return accounts


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

def run(driver: WebDriver, env: dict[str, str]) -> dict:
    """
    Punto de entrada principal del scraper.
    
    Esta función es llamada por main.py para ejecutar el scraping completo.
    Realiza login, extrae los saldos de las cuentas y retorna los datos
    en el formato esperado por el sistema.
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        env: Variables de entorno (no usado actualmente, reservado).
        
    Returns:
        Diccionario con:
        - updated_at: Timestamp ISO de la extracción
        - accounts: Lista de cuentas extraídas
    """
    creds = _get_creds()
    wait = WebDriverWait(driver, 60)

    # 1. Autenticación
    login(driver, wait, creds)

    # 2. Extracción de saldos
    accounts = extract_accounts(wait)

    return {
        "updated_at": now_iso(),
        "accounts": accounts,
    }
