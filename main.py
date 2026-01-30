import json
import os
import importlib
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

UY_TZ = timezone(timedelta(hours=-3))


@dataclass(frozen=True)
class RunConfig:
    banks: list[str]
    headless: bool
    output_json: str
    gecko_logs: bool


def now_iso_uy() -> str:
    """Retorna la fecha y hora actual en formato ISO para la zona horaria de Uruguay."""
    return datetime.now(UY_TZ).isoformat(timespec="seconds")


def load_config() -> RunConfig:
    """Carga la configuración desde el entorno y el archivo .env."""
    load_dotenv()

    banks_raw = os.getenv("BANKS", "").strip()
    banks = [b.strip() for b in banks_raw.split(",") if b.strip()]
    if not banks:
        logger.error("La variable BANKS está vacía en el .env")
        raise SystemExit("Error: Configura BANKS en .env (ej: BROU_PERSONAS)")

    headless = os.getenv("HEADLESS", "1").strip() == "1"
    output_json = os.getenv("OUTPUT_JSON", "./data/accounts.json").strip()
    # Flag para habilitar/deshabilitar logs de geckodriver (default: 0/desactivado para Docker)
    gecko_logs = os.getenv("GECKODRIVER_LOGS", "0").strip() == "1"

    # Ejemplo de placeholder en log si fuera necesario loguear algo sensible:
    # logger.debug("Cargando configuración para usuario <USER>")

    return RunConfig(
        banks=banks,
        headless=headless,
        output_json=output_json,
        gecko_logs=gecko_logs
    )


def make_driver(headless: bool, gecko_logs: bool, gecko_log_path: str) -> webdriver.Firefox:
    """Configura e inicializa el driver de Firefox (Geckodriver)."""
    opts = FirefoxOptions()
    # Flags recomendados para correr en Docker/Contenedor
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    
    if headless:
        opts.add_argument("-headless")

    service_kwargs = {}
    if gecko_logs:
        # Usar el path proporcionado para los logs de geckodriver
        service_kwargs["log_output"] = gecko_log_path
        service_kwargs["service_args"] = ["--log", "trace"]
    else:
        service_kwargs["log_output"] = os.devnull

    service = FirefoxService(**service_kwargs)
    driver = webdriver.Firefox(options=opts, service=service)
    driver.set_page_load_timeout(60)
    
    return driver


def run_bank_scraper(bank_module: str, cfg: RunConfig) -> dict:
    """Importa y ejecuta dinámicamente el módulo de un banco concreto."""
    module_path = f"banks.{bank_module}"
    driver: Optional[webdriver.Firefox] = None
    
    try:
        mod = importlib.import_module(module_path)
    except Exception as e:
        msg = f"No se pudo importar el módulo {module_path}: {e}"
        logger.error(msg)
        return {"error": msg}

    try:
        # Configuración de logs de geckodriver por banco
        log_dir = Path("./logs").resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        gecko_log_file = str(log_dir / f"geckodriver_{bank_module}.log")
        
        logger.info(f"Iniciando scraper para: {bank_module}")
        driver = make_driver(cfg.headless, cfg.gecko_logs, gecko_log_file)
        
        # Ejecución del scraper
        bank_data = mod.run(driver=driver, env=os.environ)
        
        # Obtener host/puerto para URLs
        http_host = os.getenv("HTTP_HOST", "localhost")
        http_port = os.getenv("HTTP_PORT", "8000")
        base_url = f"http://{http_host}:{http_port}"

        # 1. Agregar URL completa del logo a nivel de banco (como fallback)
        bank_logo = getattr(mod, "BANK_LOGO", None)
        if bank_logo:
            bank_data["logo"] = f"{base_url}/logos/{bank_logo}"
        
        # 2. Agregar URL completa a cada cuenta
        if "accounts" in bank_data and isinstance(bank_data["accounts"], list):
            for acc in bank_data["accounts"]:
                # Si la cuenta ya trae su propio logo (ej. ocablue.webp), lo usamos
                # Si no, usamos el logo por defecto del banco
                acc_logo = acc.get("logo") or bank_logo
                if acc_logo:
                    acc["logo"] = f"{base_url}/logos/{acc_logo}"
        
        logger.info(f"Éxito: {bank_module} procesado correctamente")
        return bank_data

    except Exception as e:
        msg = f"Error durante la ejecución de {bank_module}: {e}"
        logger.exception(msg)
        return {"error": msg}
    finally:
        if driver:
            driver.quit()


def main() -> None:
    cfg = load_config()

    out_path = Path(cfg.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    final_result: dict = {
        "updated_at": now_iso_uy(),
        "banks": {}
    }

    for bank_id in cfg.banks:
        bank_result = run_bank_scraper(bank_id, cfg)
        final_result["banks"][bank_id] = bank_result

    # Escritura del resultado final
    try:
        out_path.write_text(
            json.dumps(final_result, ensure_ascii=False, indent=2), 
            encoding="utf-8"
        )
        logger.info(f"Proceso finalizado. Resultado guardado en: {out_path}")
    except Exception as e:
        logger.error(f"No se pudo escribir el archivo de salida: {e}")


if __name__ == "__main__":
    main()
