"""
Orquestador principal del Bank Scraper.

Este módulo coordina la ejecución de todos los scrapers de bancos configurados.
Es el punto de entrada para ejecutar el scraping manualmente o desde el scheduler.

Responsabilidades:
    - Cargar configuración desde variables de entorno
    - Inicializar el WebDriver de Firefox/Geckodriver
    - Ejecutar dinámicamente cada módulo de banco
    - Agregar metadatos (logos) a los resultados
    - Guardar el resultado consolidado en JSON

Uso:
    python main.py

    Requiere que BANKS esté configurado en .env con los módulos a ejecutar.
    Ejemplo: BANKS=brou_personas,oca
"""
import json
import os
import importlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.firefox.options import Options as FirefoxOptions
from selenium.webdriver.firefox.service import Service as FirefoxService

from config import OUTPUT_JSON
from banks.common import now_iso


# =============================================================================
# CONFIGURACIÓN DE LOGGING
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)


# =============================================================================
# TIPOS DE DATOS
# =============================================================================

@dataclass(frozen=True)
class RunConfig:
    """
    Configuración de ejecución del scraper.
    
    Attributes:
        banks: Lista de módulos de banco a ejecutar.
        headless: Si True, ejecuta Firefox sin interfaz gráfica.
        output_json: Ruta del archivo JSON de salida.
        gecko_logs: Si True, habilita logs detallados de Geckodriver.
        mqtt_enabled: Si True, publica resultados via MQTT.
        mqtt_topic_prefix: Prefijo para los tópicos MQTT.
        mqtt_broker: IP/hostname del broker MQTT.
        mqtt_port: Puerto del broker MQTT.
        mqtt_user: Usuario para autenticación MQTT.
        mqtt_pass: Contraseña para autenticación MQTT.
    """
    banks: list[str]
    headless: bool
    output_json: str
    gecko_logs: bool
    mqtt_enabled: bool = False
    mqtt_topic_prefix: str = "banks"
    mqtt_broker: str = ""
    mqtt_port: int = 1883
    mqtt_user: str = ""
    mqtt_pass: str = ""


# =============================================================================
# CARGA DE CONFIGURACIÓN
# =============================================================================

def load_config() -> RunConfig:
    """
    Carga la configuración desde variables de entorno y archivo .env.
    
    Lee todas las variables necesarias para la ejecución del scraper,
    incluyendo bancos a procesar, configuración de Firefox y MQTT.
    
    Returns:
        RunConfig: Objeto con toda la configuración.
        
    Raises:
        SystemExit: Si BANKS no está configurado o está vacío.
    """
    load_dotenv()

    # Bancos a procesar (requerido)
    banks_raw = os.getenv("BANKS", "").strip()
    banks = [b.strip() for b in banks_raw.split(",") if b.strip()]
    if not banks:
        logger.error("La variable BANKS está vacía en el .env")
        raise SystemExit("Error: Configura BANKS en .env (ej: brou_personas,oca)")

    # Configuración de Firefox
    headless = os.getenv("HEADLESS", "1").strip() == "1"
    gecko_logs = os.getenv("GECKODRIVER_LOGS", "0").strip() == "1"

    # Configuración MQTT
    mqtt_enabled = os.getenv("MQTT_ENABLED", "false").lower() == "true"
    mqtt_topic_prefix = os.getenv("MQTT_TOPIC_PREFIX", "banks").strip()
    mqtt_broker = os.getenv("MQTT_BROKER", "").strip()
    mqtt_port = int(os.getenv("MQTT_PORT", "1883").strip())
    mqtt_user = os.getenv("MQTT_USER", "").strip()
    mqtt_pass = os.getenv("MQTT_PASS", "").strip()

    return RunConfig(
        banks=banks,
        headless=headless,
        output_json=OUTPUT_JSON,
        gecko_logs=gecko_logs,
        mqtt_enabled=mqtt_enabled,
        mqtt_topic_prefix=mqtt_topic_prefix,
        mqtt_broker=mqtt_broker,
        mqtt_port=mqtt_port,
        mqtt_user=mqtt_user,
        mqtt_pass=mqtt_pass
    )


# =============================================================================
# GESTIÓN DEL WEBDRIVER
# =============================================================================

def make_driver(headless: bool, gecko_logs: bool, gecko_log_path: str) -> webdriver.Firefox:
    """
    Configura e inicializa el WebDriver de Firefox.
    
    Crea una instancia de Firefox con las opciones necesarias para
    ejecutarse en un contenedor Docker (no-sandbox, disable-dev-shm-usage).
    
    Args:
        headless: Si True, ejecuta sin interfaz gráfica.
        gecko_logs: Si True, habilita logs detallados de Geckodriver.
        gecko_log_path: Ruta del archivo de log para Geckodriver.
        
    Returns:
        webdriver.Firefox: Instancia del driver lista para usar.
    """
    opts = FirefoxOptions()
    
    # Flags recomendados para ejecución en Docker
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    
    if headless:
        opts.add_argument("-headless")

    # Configuración del servicio Geckodriver
    service_kwargs = {}
    if gecko_logs:
        service_kwargs["log_output"] = gecko_log_path
        service_kwargs["service_args"] = ["--log", "trace"]
    else:
        service_kwargs["log_output"] = os.devnull

    service = FirefoxService(**service_kwargs)
    driver = webdriver.Firefox(options=opts, service=service)
    driver.set_page_load_timeout(60)
    
    return driver


# =============================================================================
# EJECUCIÓN DE SCRAPERS
# =============================================================================

def run_bank_scraper(bank_module: str, cfg: RunConfig) -> dict:
    """
    Importa y ejecuta dinámicamente el módulo de un banco.
    
    Cada banco tiene su propio módulo en banks/ con una función run().
    Esta función lo importa, ejecuta el scraping, y agrega metadatos
    como el logo a los resultados.
    
    Args:
        bank_module: Nombre del módulo en banks/ (sin extensión).
        cfg: Configuración de ejecución.
        
    Returns:
        dict: Resultado del scraping con formato:
            - updated_at: Timestamp de la extracción
            - accounts: Lista de cuentas extraídas
            - logo: Nombre del archivo de logo del banco
            
        En caso de error:
            - error: Mensaje de error descriptivo
    """
    module_path = f"banks.{bank_module}"
    driver: Optional[webdriver.Firefox] = None
    
    # Intentar importar el módulo
    try:
        mod = importlib.import_module(module_path)
    except Exception as e:
        msg = f"No se pudo importar el módulo {module_path}: {e}"
        logger.error(msg)
        return {"error": msg}

    try:
        # Configurar path de logs por banco
        log_dir = Path("./logs").resolve()
        log_dir.mkdir(parents=True, exist_ok=True)
        gecko_log_file = str(log_dir / f"geckodriver_{bank_module}.log")
        
        logger.info(f"Iniciando scraper para: {bank_module}")
        driver = make_driver(cfg.headless, cfg.gecko_logs, gecko_log_file)
        
        # Ejecutar el scraper del banco
        bank_data = mod.run(driver=driver, env=os.environ)
        
        # Agregar logo a nivel de banco
        bank_logo = getattr(mod, "BANK_LOGO", None)
        if bank_logo:
            bank_data["logo"] = bank_logo
        
        # Agregar logo a cada cuenta (si no tiene uno propio)
        if "accounts" in bank_data and isinstance(bank_data["accounts"], list):
            for acc in bank_data["accounts"]:
                acc_logo = acc.get("logo") or bank_logo
                if acc_logo:
                    acc["logo"] = acc_logo
        
        logger.info(f"Éxito: {bank_module} procesado correctamente")
        return bank_data

    except Exception as e:
        msg = f"Error durante la ejecución de {bank_module}: {e}"
        logger.exception(msg)
        return {"error": msg}
    finally:
        if driver:
            driver.quit()


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

def main() -> None:
    """
    Punto de entrada principal del orquestador.
    
    Carga la configuración, ejecuta todos los scrapers configurados
    en BANKS, y guarda el resultado consolidado en el archivo JSON.
    """
    cfg = load_config()

    # Asegurar que existe el directorio de salida
    out_path = Path(cfg.output_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Estructura del resultado final
    final_result: dict = {
        "updated_at": now_iso(),
        "banks": {}
    }

    # Ejecutar cada banco configurado
    for bank_id in cfg.banks:
        bank_result = run_bank_scraper(bank_id, cfg)
        final_result["banks"][bank_id] = bank_result

    # Guardar resultado en JSON
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
