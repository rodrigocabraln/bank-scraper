"""
Scraper para OCA (Organización de Crédito Automotor).

Este módulo extrae saldos de cuentas OCA Blue (débito) y tarjetas de crédito
desde el portal Mi Cuenta OCA. Soporta múltiples tarjetas y monedas (UYU/USD).

Características:
    - Extracción de cuentas OCA Blue (débito) en pesos y dólares
    - Extracción de tarjetas de crédito con consumos y disponible
    - Navegación automática al detalle de cada tarjeta para obtener disponible
    - Manejo de modales emergentes (encuestas NPS)

Uso:
    Este módulo es llamado dinámicamente por main.py. No se ejecuta directamente.
    Las credenciales deben configurarse previamente con setup.py.
"""
from __future__ import annotations

import json
import re
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

BANK_KEY = "oca"
"""Identificador único del banco, usado para nombres de archivos y tópicos MQTT."""

BANK_LOGO = "oca.webp"
"""Logo por defecto para tarjetas de crédito OCA."""

OCA_BLUE_LOGO = "ocablue.webp"
"""Logo específico para cuentas OCA Blue (débito)."""

CREDENTIAL_FIELDS = [
    {"name": "document", "prompt": "Documento", "secret": False, "pattern": r"^\d+$"},
    {"name": "password", "prompt": "Contraseña", "secret": True},
]
"""Campos requeridos por setup.py para configurar las credenciales."""

OCA_LOGIN_URL = "https://micuentanuevo.oca.com.uy/trx/login"
"""URL de inicio de sesión del portal Mi Cuenta OCA."""


# =============================================================================
# SELECTORES DOM - LOGIN
# =============================================================================

SEL_DOC_INPUT = (By.NAME, "nro_documento")
"""Campo de entrada del número de documento."""

SEL_PWD_INPUT = (By.NAME, "pass")
"""Campo de entrada de la contraseña."""

SEL_LOGIN_BTN = (By.ID, "buttonlogin")
"""Botón de inicio de sesión."""

SEL_MODAL_CLOSE = (By.ID, "nps-close-button-nps-custom")
"""Botón para cerrar modal de encuesta NPS (si aparece)."""


# =============================================================================
# SELECTORES DOM - OCA BLUE (DÉBITO)
# =============================================================================

SEL_BLUE_CONTAINER = (By.ID, "cajasDeAhorro")
"""Contenedor de la sección de cuentas OCA Blue."""

SEL_BLUE_CARDS = (By.CSS_SELECTOR, "a.card-home-tarjetas")
"""Tarjetas individuales de cuentas Blue."""


# =============================================================================
# SELECTORES DOM - TARJETAS DE CRÉDITO
# =============================================================================

SEL_CREDIT_SECTION = (By.CSS_SELECTOR, "section[data-function='parseTarjetasCredito']")
"""Sección de tarjetas de crédito en el dashboard."""

SEL_CREDIT_CARDS = (By.CSS_SELECTOR, "a.card-home-tarjetas")
"""Tarjetas individuales de crédito (links al detalle)."""

SEL_DETAIL_AVAILABLE = (By.XPATH, "/html/body/div/div[7]/div[2]/div[2]/div/div[3]/div/div[3]/div/div[1]/div[2]/div")
"""Elemento con el saldo disponible en la página de detalle de tarjeta.
   Nota: XPath absoluto, puede romperse si cambia el DOM."""


# =============================================================================
# CONFIGURACIÓN INTERNA
# =============================================================================

REQUIRED_CREDENTIALS = {
    "creds": f"{BANK_KEY}_creds",
}
"""Mapeo de nombres de credenciales requeridas."""


# =============================================================================
# TIPOS DE DATOS
# =============================================================================

@dataclass(frozen=True)
class OcaCreds:
    """Credenciales de acceso al portal OCA."""
    document: str
    password: str


# =============================================================================
# FUNCIONES INTERNAS
# =============================================================================

def _get_creds() -> OcaCreds:
    """
    Obtiene y desencripta las credenciales almacenadas.
    
    Lee el archivo de credenciales cifrado desde CREDENTIALS_DIRECTORY,
    lo desencripta usando la clave Fernet de CREDS_KEY, y parsea el JSON.
    
    Returns:
        OcaCreds: Objeto con documento y contraseña.
        
    Raises:
        RuntimeError: Si el archivo no existe, no es JSON válido,
                      o faltan campos requeridos.
    """
    raw = require_credential(REQUIRED_CREDENTIALS["creds"])
    json_text = decrypt_fernet(raw)
    
    try:
        obj = json.loads(json_text)
    except Exception as e:
        raise RuntimeError(f"JSON inválido en {REQUIRED_CREDENTIALS['creds']}: {e}")

    doc = (obj.get("document") or "").strip()
    pwd = (obj.get("password") or "").strip()
    
    if not doc or not pwd:
        raise RuntimeError("Faltan campos document/password en las credenciales")
    
    return OcaCreds(document=doc, password=pwd)


def _safe_text(elem) -> str:
    """
    Extrae texto de un elemento web de forma robusta.
    
    Usa textContent en lugar de .text para obtener el contenido
    incluso si el elemento está oculto o tiene estilos CSS especiales.
    Esto es especialmente útil en modo headless.
    
    Args:
        elem: Elemento WebElement de Selenium.
        
    Returns:
        str: Texto del elemento, o cadena vacía si falla.
    """
    try:
        return (elem.get_attribute("textContent") or "").strip()
    except Exception:
        return ""


def _clean_raw_money(raw_val: str) -> str:
    """
    Limpia strings de dinero extrayendo solo el importe con símbolo.
    
    Busca patrones como "$ 1.234,56" o "US$ 100,00" y los extrae,
    eliminando texto adicional que pueda rodear el monto.
    
    Args:
        raw_val: String con el monto posiblemente con texto extra.
        
    Returns:
        str: Monto limpio con símbolo de moneda (ej: "$ 5,40").
    """
    if not raw_val:
        return raw_val
    # Busca patrón: símbolo de moneda + espacios + dígitos/puntos/comas
    match = re.search(r"(?:US\$|\$)\s*[\d.,]+", raw_val)
    if match:
        return match.group(0).strip()
    return raw_val


def _extract_card_number(brand_text: str) -> str:
    """
    Extrae los últimos 4 dígitos del número de tarjeta.
    
    Convierte formatos como "OCA **** 1234 (abc)" a solo "1234".
    
    Args:
        brand_text: Texto de la marca/número de tarjeta.
        
    Returns:
        str: Solo los últimos 4 dígitos, o el texto original si no matchea.
    """
    if "****" in brand_text:
        try:
            match = re.search(r"OCA.*?(\d{4})", brand_text)
            if match:
                return match.group(1)
        except Exception:
            pass
    return brand_text


# =============================================================================
# FUNCIONES DE SCRAPING
# =============================================================================

def login(driver: WebDriver, wait: WebDriverWait, creds: OcaCreds) -> None:
    """
    Realiza el proceso de autenticación en el portal OCA.
    
    Navega a la página de login, completa el formulario con las
    credenciales y maneja modales de encuesta NPS si aparecen.
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        wait: WebDriverWait configurado con timeout.
        creds: Credenciales de acceso.
    """
    driver.get(OCA_LOGIN_URL)

    # Completar campo documento
    doc_in = wait.until(EC.element_to_be_clickable(SEL_DOC_INPUT))
    doc_in.clear()
    doc_in.send_keys(creds.document)

    # Completar campo contraseña
    pwd_in = wait.until(EC.element_to_be_clickable(SEL_PWD_INPUT))
    pwd_in.clear()
    pwd_in.send_keys(creds.password)

    # Cerrar modal NPS si está visible (no bloquea si no existe)
    try:
        modal_btn = driver.find_element(*SEL_MODAL_CLOSE)
        if modal_btn.is_displayed():
            modal_btn.click()
    except Exception:
        pass

    # Enviar formulario
    login_btn = wait.until(EC.element_to_be_clickable(SEL_LOGIN_BTN))
    login_btn.click()

    # Esperar carga del dashboard
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "card-dashboard")))


def extract_blue(driver: WebDriver, wait: WebDriverWait) -> list[dict]:
    """
    Extrae información de cuentas OCA Blue (débito).
    
    Busca la sección de "Cajas de Ahorro" y extrae cada cuenta
    con su moneda, número y saldo.
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        wait: WebDriverWait configurado con timeout.
        
    Returns:
        Lista de diccionarios con la información de cada cuenta Blue:
        - type: "ACCOUNT"
        - currency: Símbolo de moneda normalizado
        - account_number: "OCA Blue <número>"
        - balance: Saldo como objeto {raw, number}
        - available: Igual a balance (en Blue es lo mismo)
        - logo: Logo específico de OCA Blue
    """
    accounts = []
    
    try:
        # Esperar a que el contenedor exista
        container = wait.until(EC.presence_of_element_located(SEL_BLUE_CONTAINER))
        
        # Intentar esperar a que aparezcan tarjetas dentro del contenedor.
        # Usamos un timeout corto específico para esto, ya que podría no haber cuentas.
        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, "#cajasDeAhorro a.card-home-tarjetas"))
            )
        except Exception:
            # Si no aparecen en 5s, asumimos que no hay o que ya cargó vacío
            pass

        cards = container.find_elements(*SEL_BLUE_CARDS)
    except Exception:
        return []

    for card in cards:
        try:
            # Extraer datos de la tarjeta
            currency_lbl = _safe_text(card.find_element(By.CLASS_NAME, "moneda-card"))
            acc_num = _safe_text(card.find_element(By.CLASS_NAME, "cuenta-numero"))
            balance_dirty = _safe_text(card.find_element(By.CLASS_NAME, "saldo-valor"))
            
            balance_raw = _clean_raw_money(balance_dirty)
            currency = "USD" if "Dólares" in currency_lbl else "UYU"
            saldo = parse_amount(balance_raw)

            accounts.append({
                "type": "ACCOUNT",
                "currency": normalize_currency(currency),
                "account_number": f"OCA Blue {acc_num}",
                "balance": saldo,
                "available": saldo,  # En cuentas Blue, balance = disponible
                "logo": OCA_BLUE_LOGO,
            })
        except Exception:
            continue
            
    return accounts


def extract_credit_cards(driver: WebDriver, wait: WebDriverWait) -> list[dict]:
    """
    Extrae información de tarjetas de crédito.
    
    Este proceso es más complejo porque requiere:
    1. Extraer info básica del dashboard (consumos por moneda)
    2. Navegar al detalle de cada tarjeta para obtener el disponible
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        wait: WebDriverWait configurado con timeout.
        
    Returns:
        Lista de diccionarios con la información de cada tarjeta:
        - type: "CREDIT_CARD"
        - currency: Símbolo de moneda normalizado
        - account_number: "OCA Credito <últimos 4 dígitos>"
        - balance: Consumos como objeto {raw, number}
        - available: Disponible como objeto {raw, number} o null si no aplica
        - logo: Logo de OCA
        
    Note:
        Una tarjeta puede generar múltiples entradas si tiene consumos
        en diferentes monedas (UYU y USD).
    """
    try:
        section = driver.find_element(*SEL_CREDIT_SECTION)
        card_links = section.find_elements(*SEL_CREDIT_CARDS)
    except Exception:
        return []

    # Fase 1: Extraer info básica del dashboard
    to_process = []
    for link in card_links:
        try:
            card_id = link.get_attribute("id")
            brand_text = _safe_text(link.find_element(By.CLASS_NAME, "marca-tarjeta-card"))
            
            # Puede haber múltiples saldos (UYU y USD)
            saldos_elems = link.find_elements(By.CLASS_NAME, "saldo-valor")
            vals = [_safe_text(s) for s in saldos_elems]
            
            to_process.append({
                "id": card_id,
                "name": brand_text,
                "consumos_raw": vals
            })
        except Exception:
            continue

    final_cards = []
    
    # Fase 2: Navegar al detalle de cada tarjeta para obtener disponible
    for item in to_process:
        url = f"https://micuentanuevo.oca.com.uy/trx/tarjetas/credito/{item['id']}"
        driver.get(url)
        
        # Intentar obtener el disponible
        try:
            avail_elem = wait.until(EC.presence_of_element_located(SEL_DETAIL_AVAILABLE))
            avail_raw_dirty = _safe_text(avail_elem)
            avail_raw = _clean_raw_money(avail_raw_dirty)
            
            avail_parsed = parse_amount(avail_raw)
            avail_currency = "USD" if "US" in avail_raw else "UYU"
        except Exception:
            avail_parsed = {"raw": None, "number": None}
            avail_currency = "UYU"

        # Procesar cada consumo (puede haber varios: UYU, USD, saldo a favor)
        for raw_cons in item['consumos_raw']:
            clean_cons = _clean_raw_money(raw_cons)
            cons_parsed = parse_amount(clean_cons)
            
            currency = "USD" if "US" in clean_cons else "UYU"
            
            # Asignar disponible solo si coincide la moneda
            # (el disponible suele estar en UYU para tarjetas uruguayas)
            my_avail = avail_parsed.copy() if currency == avail_currency else {"raw": None, "number": None}
            
            # Limpiar número de tarjeta: "OCA **** 1234" → "1234"
            acc_num_clean = _extract_card_number(item['name'])
            
            final_cards.append({
                "type": "CREDIT_CARD",
                "currency": normalize_currency(currency),
                "account_number": f"OCA Credito {acc_num_clean}", 
                "balance": cons_parsed,
                "available": my_avail,
                "logo": BANK_LOGO,
            })

    return final_cards


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

def run(driver: WebDriver, env: dict[str, str]) -> dict:
    """
    Punto de entrada principal del scraper.
    
    Esta función es llamada por main.py para ejecutar el scraping completo.
    Realiza login, extrae cuentas Blue y tarjetas de crédito, y retorna
    todos los datos combinados.
    
    Args:
        driver: Instancia del WebDriver de Selenium.
        env: Variables de entorno (no usado actualmente, reservado).
        
    Returns:
        Diccionario con:
        - updated_at: Timestamp ISO de la extracción
        - accounts: Lista combinada de cuentas Blue + tarjetas de crédito
    """
    creds = _get_creds()
    wait = WebDriverWait(driver, 45)

    # Autenticación
    login(driver, wait, creds)

    # Extracción de datos
    data_blue = extract_blue(driver, wait)
    data_cred = extract_credit_cards(driver, wait)

    return {
        "updated_at": now_iso(),
        "accounts": data_blue + data_cred,
    }
