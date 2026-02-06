"""
Scheduler para ejecución periódica del scraper.

Este módulo coordina la ejecución automática del scraper en horarios
configurados, maneja el servidor HTTP embebido, y gestiona la
publicación MQTT periódica.

Características:
    - Ejecución programada en horarios configurables
    - Jitter aleatorio para evitar patrones predecibles
    - Detección de ejecuciones perdidas (por reinicio del contenedor)
    - Servidor HTTP embebido en hilo separado
    - Republicación MQTT periódica (cada 60s si está habilitado)

Uso:
    python scheduler.py

    Este es el punto de entrada principal cuando se ejecuta en Docker.
    Corre indefinidamente, ejecutando el scraper en los horarios configurados.
    
Environment Variables:
    SCHEDULE_HOURS: Horarios de ejecución separados por coma (ej: "07:00,20:00")
    RANDOM_DELAY_MIN: Minutos máximos de delay aleatorio (default: 30)
    MQTT_ENABLED: Si "true", habilita publicación MQTT
"""
import schedule
import time
import random
import subprocess
import os
import sys
import threading
import logging
import json
from datetime import datetime, date

from config import OUTPUT_JSON


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
# IMPORTS LOCALES
# =============================================================================

from http_server import start_http_server
from mqtt_publisher import publish_to_mqtt


# =============================================================================
# CONFIGURACIÓN
# =============================================================================

SCHEDULE_HOURS_RAW = os.getenv("SCHEDULE_HOURS", "07:00,20:00")
"""Horarios de ejecución del scraper, separados por coma."""

SCHEDULE_HOURS = [h.strip() for h in SCHEDULE_HOURS_RAW.split(",") if h.strip()]
"""Lista de horarios parseados."""

RANDOM_DELAY_MIN = int(os.getenv("RANDOM_DELAY_MIN", "30"))
"""Minutos máximos de delay aleatorio (jitter)."""

STATE_FILE = "data/last_run.txt"
"""Archivo para persistir la última ejecución exitosa."""

MQTT_ENABLED = os.getenv("MQTT_ENABLED", "false").lower() == "true"
"""Flag para habilitar/deshabilitar MQTT."""


# =============================================================================
# FUNCIONES DE SCRAPING
# =============================================================================

def run_scraper() -> None:
    """
    Ejecuta el script principal de scraping.
    
    Invoca main.py como subproceso, publica a MQTT si está habilitado,
    y guarda el timestamp de la ejecución exitosa.
    """
    logger.info("Iniciando trabajo de scraping...")
    try:
        subprocess.run([sys.executable, "main.py"], check=True)
        
        # Publicar a MQTT si está habilitado
        if MQTT_ENABLED:
            publish_mqtt_task()

        # Guardar timestamp de última ejecución exitosa
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write(datetime.now().isoformat())
            
    except Exception as e:
        logger.error(f"Trabajo falló: {e}")


def publish_mqtt_task() -> None:
    """
    Tarea periódica para republicar datos a MQTT.
    
    Lee el JSON cacheado y lo publica al broker MQTT.
    Esto asegura que Home Assistant tenga datos actualizados
    incluso si se reinicia.
    """
    if not MQTT_ENABLED:
        return
    if not os.path.exists(OUTPUT_JSON):
        return
    
    try:
        with open(OUTPUT_JSON, "r", encoding="utf-8") as f:
            data = json.load(f)
        publish_to_mqtt(data)
    except Exception as e:
        logger.error(f"Error en publish_mqtt_task: {e}")


# =============================================================================
# WRAPPERS Y UTILIDADES
# =============================================================================

def job_wrapper() -> None:
    """
    Wrapper del trabajo con jitter aleatorio.
    
    Agrega un delay aleatorio entre 0 y RANDOM_DELAY_MIN minutos
    antes de ejecutar el scraper. Esto evita patrones predecibles
    que podrían ser detectados por los sitios bancarios.
    """
    delay_sec = random.randint(0, RANDOM_DELAY_MIN * 60)
    logger.info(f"Hora programada alcanzada. Esperando {delay_sec}s para aleatoriedad...")
    time.sleep(delay_sec)
    run_scraper()


def check_missed_runs() -> None:
    """
    Verifica si se perdieron ejecuciones por reinicio del contenedor.
    
    Si la última ejecución fue ayer y ya pasó algún horario programado
    de hoy, ejecuta inmediatamente para recuperar los datos.
    """
    if not os.path.exists(STATE_FILE):
        return
    
    try:
        with open(STATE_FILE, "r") as f:
            last_run_iso = f.read().strip()
        last_run = datetime.fromisoformat(last_run_iso)
        
        # Si la última ejecución fue antes de hoy
        if last_run.date() < date.today():
            now_str = datetime.now().strftime("%H:%M")
            # Y ya pasó algún horario programado
            if any(now_str > h for h in SCHEDULE_HOURS):
                logger.warning(f"Ejecución perdida detectada (Última: {last_run}). Corriendo ahora.")
                run_scraper()
                 
    except Exception as e:
        logger.error(f"Error verificando ejecuciones perdidas: {e}")


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

def main() -> None:
    """
    Punto de entrada principal del scheduler.
    
    Inicia el servidor HTTP en un hilo separado, configura los
    trabajos programados, y entra en el bucle principal que
    ejecuta los trabajos pendientes.
    """
    logger.info(f"Scheduler iniciado. Horas: {SCHEDULE_HOURS}, Jitter: +{RANDOM_DELAY_MIN}m")
    
    # Iniciar servidor HTTP en hilo daemon
    http_thread = threading.Thread(target=start_http_server, daemon=True)
    http_thread.start()
    
    # Programar trabajos para cada horario configurado
    for h_str in SCHEDULE_HOURS:
        try:
            datetime.strptime(h_str, "%H:%M")  # Validar formato
            logger.info(f"Programando trabajo para las {h_str} (+0-{RANDOM_DELAY_MIN}m espera)")
            schedule.every().day.at(h_str).do(job_wrapper)
        except ValueError as e:
            logger.error(f"Error con horario '{h_str}': {e}")
            
    # Verificar ejecuciones perdidas al iniciar
    check_missed_runs()
    
    # Publicar a MQTT al iniciar (si existe el JSON previo)
    if MQTT_ENABLED:
        publish_mqtt_task()
    
    # Bucle principal
    while True:
        try:
            n = schedule.idle_seconds()
            if n is None:
                time.sleep(60)
            elif n > 0:
                time.sleep(n)
            
            schedule.run_pending()
            
        except KeyboardInterrupt:
            logger.info("Scheduler detenido por usuario.")
            break
        except Exception as e:
            logger.error(f"Error en bucle principal: {e}")
            time.sleep(60)


if __name__ == "__main__":
    main()
