from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .common import require_credential, decrypt_fernet, UY_TZ, normalize_currency

# --- Configuración y Selectores ---
BANK_KEY = "oca"
BANK_LOGO = "oca.webp"

CREDENTIAL_FIELDS = [
    {"name": "document", "prompt": "Documento", "secret": False, "pattern": r"^\d+$"},
    {"name": "password", "prompt": "Contraseña", "secret": True},
]

OCA_LOGIN_URL = "https://micuentanuevo.oca.com.uy/trx/login"

# Selectores de Login
SEL_DOC_INPUT = (By.NAME, "nro_documento")
SEL_PWD_INPUT = (By.NAME, "pass")
SEL_LOGIN_BTN = (By.ID, "buttonlogin")
SEL_MODAL_CLOSE = (By.ID, "nps-close-button-nps-custom")

# Selectores OCA Blue
# XPath provided: /html/body/div[1]/div[12]/div/div[4]/div[2]/div[1] -> div.col-custom-4 section#cajasDeAhorro
SEL_BLUE_CONTAINER = (By.ID, "cajasDeAhorro")
SEL_BLUE_CARDS = (By.CSS_SELECTOR, "a.card-home-tarjetas")

# Selectores Tarjetas Crédito
# Using data-function="parseTarjetasCredito" to find the section
SEL_CREDIT_SECTION = (By.CSS_SELECTOR, "section[data-function='parseTarjetasCredito']")
SEL_CREDIT_CARDS = (By.CSS_SELECTOR, "a.card-home-tarjetas")

# Selectores Detalle Tarjeta (Available Balance)
# XPath: /html/body/div/div[7]/div[2]/div[2]/div/div[3]/div/div[3]/div/div[1]/div[2]/div
# We'll try to use a more robust CSS selector if possible, or fall back to XPath.
# Given the complexity, let's stick to the user provided XPath for the specific value, but might be risky.
# Let's try to identify it by context if possible. But user gave specific XPath.
SEL_DETAIL_AVAILABLE = (By.XPATH, "/html/body/div/div[7]/div[2]/div[2]/div/div[3]/div/div[3]/div/div[1]/div[2]/div")


REQUIRED_CREDENTIALS = {
    "creds": f"{BANK_KEY}_creds",
}


@dataclass(frozen=True)
class OcaCreds:
    document: str
    password: str


def _get_creds() -> OcaCreds:
    raw = require_credential(REQUIRED_CREDENTIALS["creds"])
    json_text = decrypt_fernet(raw)
    try:
        obj = json.loads(json_text)
    except Exception as e:
        raise RuntimeError(f"JSON inválido en {REQUIRED_CREDENTIALS['creds']}: {e}")

    doc = (obj.get("document") or "").strip()
    pwd = (obj.get("password") or "").strip()
    if not doc or not pwd:
        raise RuntimeError("Faltan campos document/password")
    return OcaCreds(document=doc, password=pwd)


def _parse_money(raw: str) -> dict[str, Any]:
    """
    Parsea importes como "$ 5,40", "US$ 1.234,56".
    """
    s = (raw or "").strip()
    if not s:
        return {"raw": raw, "number": None}

    # Remover símbolos de moneda y espacios
    clean = s.replace("$", "").replace("US", "").strip()
    # Formato español: punto miles, coma decimal
    # 1.234,56 -> 1234.56
    normalized = clean.replace(".", "").replace(",", ".")
    
    try:
        val = float(normalized)
    except ValueError:
        val = None

    return {"raw": raw, "number": val}


def login(driver: WebDriver, wait: WebDriverWait, creds: OcaCreds) -> None:
    driver.get(OCA_LOGIN_URL)

    # 1. Documento
    doc_in = wait.until(EC.element_to_be_clickable(SEL_DOC_INPUT))
    doc_in.clear()
    doc_in.send_keys(creds.document)

    # 2. Contraseña
    pwd_in = wait.until(EC.element_to_be_clickable(SEL_PWD_INPUT))
    pwd_in.clear()
    pwd_in.send_keys(creds.password)

    # 3. Modal (Optional check before click? Or just try click)
    # User says "si aparece modal, cerrar". Usually appears after login or before?
    # Assuming before/during interaction. Let's check briefly.
    try:
        modal_btn = driver.find_element(*SEL_MODAL_CLOSE)
        if modal_btn.is_displayed():
            modal_btn.click()
    except Exception:
        pass

    # 4. Click Ingresar
    login_btn = wait.until(EC.element_to_be_clickable(SEL_LOGIN_BTN))
    login_btn.click()

    # Esperar a que cargue el dashboard (por ejemplo, que aparezca la sección de tarjetas o blue)
    # A simple indicator is the presence of one of the main sections
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "card-dashboard")))


def clean_raw_money(raw_val: str) -> str:
    """Limpia strings de dinero usando Regex para dejar solo el importe."""
    if not raw_val: return raw_val
    import re
    # Busca patrón: (US$|$)? + espacios + digitos/puntos/comas
    # Ej: "Disponible\n$ 5.000" -> "$ 5.000"
    match = re.search(r"(?:US\$|\$)\s*[\d.,]+", raw_val)
    if match:
        return match.group(0).strip()
    return raw_val

def _safe_text(elem) -> str:
    """Intenta obtener texto de forma robusta (textContent) para evitar vacíos en headless."""
    try:
        # textContent trae todo el texto incluso si está oculto/css raro
        return (elem.get_attribute("textContent") or "").strip()
    except Exception:
        return ""

def extract_blue(driver: WebDriver) -> list[dict]:
    """Extrae cuentas OCA Blue (Débito/Cuenta)."""
    accounts = []
    try:
        container = driver.find_element(*SEL_BLUE_CONTAINER)
        # Buscar elementos frescos
        cards = container.find_elements(*SEL_BLUE_CARDS)
    except Exception:
        return []

    for card in cards:
        try:
            currency_lbl = _safe_text(card.find_element(By.CLASS_NAME, "moneda-card"))
            acc_num = _safe_text(card.find_element(By.CLASS_NAME, "cuenta-numero"))
            balance_dirty = _safe_text(card.find_element(By.CLASS_NAME, "saldo-valor"))
            
            balance_raw = clean_raw_money(balance_dirty)

            currency = "USD" if "Dólares" in currency_lbl else "UYU"
            saldo = _parse_money(balance_raw)

            accounts.append({
                "type": "ACCOUNT",
                "currency": normalize_currency(currency),
                "account_number": f"OCA Blue {acc_num}",
                "balance": saldo,
                "available": saldo,
                "logo": "ocablue.webp"
            })
        except Exception:
            continue
            
    return accounts


def extract_credit_cards(driver: WebDriver, wait: WebDriverWait) -> list[dict]:
    """Extrae tarjetas de crédito, incluyendo navegación al detalle."""
    try:
        section = driver.find_element(*SEL_CREDIT_SECTION)
        card_links = section.find_elements(*SEL_CREDIT_CARDS)
    except Exception:
        return []

    # 1. Extraer Info del Dashboard (Consumos)
    to_process = []
    for link in card_links:
        try:
            card_id = link.get_attribute("id")
            brand_text = _safe_text(link.find_element(By.CLASS_NAME, "marca-tarjeta-card"))
            
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
    
    # 2. Navegar al detalle para Disponible
    for item in to_process:
        url = f"https://micuentanuevo.oca.com.uy/trx/tarjetas/credito/{item['id']}"
        driver.get(url)
        
        try:
            avail_elem = wait.until(EC.presence_of_element_located(SEL_DETAIL_AVAILABLE))
            # Usar textContent aquí también
            avail_raw_dirty = _safe_text(avail_elem)
            avail_raw = clean_raw_money(avail_raw_dirty)
            
            avail_parsed = _parse_money(avail_raw)
            avail_currency = "USD" if "US" in avail_raw else "UYU"
            
        except Exception:
            avail_parsed = {"raw": None, "number": None}
            avail_currency = "UYU"

        # Procesar los consumos (siempre hay consumo, aunque sea 0, o saldos a fvor)
        # Si la lista está vacía, quizas es tarjeta nueva sin consumo?
        if not item['consumos_raw']:
             # Caso borde
             pass

        for raw_cons in item['consumos_raw']:
            clean_cons = clean_raw_money(raw_cons)
            cons_parsed = _parse_money(clean_cons)
            
            currency = "USD" if "US" in clean_cons else "UYU"
            
            my_avail = {"raw": None, "number": None}
            # Asignar disponible si coincide moneda
            if currency == avail_currency:
                my_avail = avail_parsed.copy()
            # Si no coincide (ej: consumo en USD, pero disponible en UYU), available queda null/0?
            # User pidió available.number = 0 si es null? o raw "$ 0,00".
            # El "null" en available suele ser correcto si no aplica (ej: disponible en USD para tarjeta UYU only?) 
            # Pero en OCA el límite suele ser único en pesos. 
            # Dejaremos la lógica actual: si currency != avail_currency, available = null.

            # Formatear el número de cuenta: "OCA **** 1234 (abcd)" -> "OCA 1234"
            acc_num_clean = item['name']
            if "****" in acc_num_clean:
                try:
                    import re
                    match_num = re.search(r"OCA.*?(\d{4})", acc_num_clean)
                    if match_num:
                        acc_num_clean = f"{match_num.group(1)}"
                except:
                    pass
            
            final_cards.append({
                "type": "CREDIT_CARD",
                "currency": normalize_currency(currency),
                "account_number": f"OCA Credito {acc_num_clean}", 
                "balance": cons_parsed,
                "available": my_avail,
                "logo": "oca.webp"
            })

    return final_cards


def run(driver: WebDriver, env: dict[str, str]) -> dict:
    creds = _get_creds()
    wait = WebDriverWait(driver, 45)

    login(driver, wait, creds)

    data_blue = extract_blue(driver)
    data_cred = extract_credit_cards(driver, wait)

    return {
        "updated_at": datetime.now(UY_TZ).isoformat(timespec="seconds"),
        "accounts": data_blue + data_cred,
    }
