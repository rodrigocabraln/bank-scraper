from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Any

from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from .common import require_credential, decrypt_fernet, normalize_currency

# --- Configuración y Selectores ---
BANK_KEY = "brou_personas"
BANK_LOGO = "brou.webp"

# Campos que requiere el setup para este banco
CREDENTIAL_FIELDS = [
    {"name": "document", "prompt": "Documento", "secret": False},
    {"name": "password", "prompt": "Contraseña", "secret": True},
]

BROU_URL = "https://ebanking.brou.com.uy/frontend/"
UY_TZ = timezone(timedelta(hours=-3))

# Selectores
SEL_DOC_INPUT = (By.NAME, "document")
SEL_PWD_INPUT = (By.NAME, "password")
SEL_SUBMIT_BTN = (By.CSS_SELECTOR, "button[type='submit']")
SEL_TABLE_CONTAINER = (By.XPATH, "/html/body/div[1]/div[1]/div/div/div/div/div/main/div[1]/div/div/div[2]/section/div/div/div/div/div/div[2]/div[2]")
SEL_TABLE_ROWS = (By.CSS_SELECTOR, "div.table-body a.table-row")
SEL_TABLE_CELLS = (By.CSS_SELECTOR, "div.table-data")

REQUIRED_CREDENTIALS = {
    "creds": f"{BANK_KEY}_creds",
}


@dataclass(frozen=True)
class BrouCreds:
    document: str
    password: str


def _get_creds() -> BrouCreds:
    """Extrae y desencripta las credenciales del sistema."""
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


def _normalize_amount(raw: str) -> dict[str, Any]:
    """Convierte el formato de moneda uruguayo (1.234,56) a un float numérico."""
    s = (raw or "").strip()
    if not s:
        return {"raw": raw, "number": None}
    try:
        # Reemplaza separador de miles y cambia coma decimal por punto
        normalized = s.replace(".", "").replace(",", ".")
        return {"raw": raw, "number": float(normalized)}
    except Exception:
        return {"raw": raw, "number": None}


def login(driver: WebDriver, wait: WebDriverWait, creds: BrouCreds) -> None:
    """Realiza el proceso de login en la web del BROU."""
    driver.get(BROU_URL)

    doc_input = wait.until(EC.presence_of_element_located(SEL_DOC_INPUT))
    pwd_input = wait.until(EC.presence_of_element_located(SEL_PWD_INPUT))

    doc_input.clear()
    doc_input.send_keys(creds.document)

    pwd_input.clear()
    pwd_input.send_keys(creds.password)

    submit_btn = wait.until(EC.element_to_be_clickable(SEL_SUBMIT_BTN))
    submit_btn.click()
    

def extract_accounts(wait: WebDriverWait) -> list[dict]:
    """Extrae la información de las cuentas desde la tabla principal de saldos."""
    table_container = wait.until(EC.presence_of_element_located(SEL_TABLE_CONTAINER))
    
    # Esperar a que la tabla cargue contenido (filas)
    wait.until(lambda d: len(table_container.find_elements(*SEL_TABLE_ROWS)) > 0)
    
    rows = table_container.find_elements(*SEL_TABLE_ROWS)
    accounts = []

    for row in rows:
        cells = row.find_elements(*SEL_TABLE_CELLS)
        if len(cells) < 3:
            continue

        cuenta_text = cells[0].text.strip()
        moneda_text = cells[1].text.strip()
        saldo_text = cells[2].text.strip()

        # BROU accounts are typically standard accounts/savings
        # The scraped saldo is the available balance.
        
        balance_obj = _normalize_amount(saldo_text)
        
        accounts.append({
            "type": "ACCOUNT",
            "currency": normalize_currency(moneda_text),
            "account_number": cuenta_text,
            "balance": balance_obj,
            "available": balance_obj,
            "logo": "brou.webp"
        })
    
    return accounts


def run(driver: WebDriver, env: dict[str, str]) -> dict:
    """Función principal ejecutada por el orquestador."""
    creds = _get_creds()
    wait = WebDriverWait(driver, 60)

    # 1. Login
    login(driver, wait, creds)

    # 2. Extracción de datos
    accounts = extract_accounts(wait)

    return {
        "updated_at": datetime.now(UY_TZ).isoformat(timespec="seconds"),
        "accounts": accounts,
    }
