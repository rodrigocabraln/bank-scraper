import schedule
import time
import random
import subprocess
import os
import sys
import threading
import logging
from datetime import datetime, date

# Configuración de Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger(__name__)

# Local imports
from http_server import start_http_server
from mqtt_publisher import publish_to_mqtt
import json

# Configuración
SCHEDULE_HOURS_RAW = os.getenv("SCHEDULE_HOURS", "07:00,20:00")
SCHEDULE_HOURS = [h.strip() for h in SCHEDULE_HOURS_RAW.split(",") if h.strip()]
RANDOM_DELAY_MIN = int(os.getenv("RANDOM_DELAY_MIN", "30"))
STATE_FILE = "data/last_run.txt"
OUTPUT_JSON = "/app/data/accounts.json"
MQTT_ENABLED = os.getenv("MQTT_ENABLED", "false").lower() == "true"


def run_scraper():
    """Ejecuta el script principal de scrapeo."""
    logger.info("Iniciando trabajo de scraping...")
    try:
        # Llama a main.py usando el mismo intérprete de python
        subprocess.run([sys.executable, "main.py"], check=True)
        
        # Republicar inmediatamente después de un scrape exitoso si MQTT está activo
        if MQTT_ENABLED:
            publish_mqtt_task()

        # Actualizar última ejecución
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write(datetime.now().isoformat())
            
    except Exception as e:
        logger.error(f"Trabajo falló: {e}")


def publish_mqtt_task():
    """Tarea periódica para republicar datos a MQTT leyendo el JSON cacheado."""
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


def job_wrapper():
    """
    Envoltorio del trabajo para agregar jitter (retraso aleatorio).
    Se ejecuta a la hora programada + un delay aleatorio.
    """
    delay_sec = random.randint(0, RANDOM_DELAY_MIN * 60)
    print(f"[{datetime.now()}] Hora programada alcanzada. Esperando {delay_sec}s para aleatoriedad...")
    time.sleep(delay_sec)
    run_scraper()


def check_missed_runs():
    """
    Chequeo simple: si no hemos corrido hoy, y ya pasó alguna hora programada, correr ahora.
    """
    if not os.path.exists(STATE_FILE):
        return # Primera ejecución, esperamos al cronograma.
    
    try:
        with open(STATE_FILE, "r") as f:
            last_run_iso = f.read().strip()
        last_run = datetime.fromisoformat(last_run_iso)
        
        # Si la última ejecución fue antes de hoy...
        if last_run.date() < date.today():
             # Verificar si ya pasamos al menos una hora programada
             now_str = datetime.now().strftime("%H:%M")
             if any(now_str > h for h in SCHEDULE_HOURS):
                 print(f"[{datetime.now()}] Ejecución perdida detectada (Última: {last_run}). Corriendo ahora.")
                 run_scraper()
                 
    except Exception as e:
        print(f"Error verificando ejecuciones perdidas: {e}")


def main():
    logger.info(f"Scheduler iniciado. Horas: {SCHEDULE_HOURS}, Jitter: +{RANDOM_DELAY_MIN}m")
    
    # 1. Iniciar servidor HTTP en hilo separado
    # El threading.Thread nos permite correr el servidor sin bloquear el scheduler
    t = threading.Thread(target=start_http_server, daemon=True)
    t.start()
    
    # 2. Programar Trabajos
    for h_str in SCHEDULE_HOURS:
        try:
            # Validamos formato básico
            datetime.strptime(h_str, "%H:%M")
            print(f"Programando trabajo para las {h_str} (+0-{RANDOM_DELAY_MIN}m espera)")
            schedule.every().day.at(h_str).do(job_wrapper)
        except ValueError as e:
            print(f"Error con horario '{h_str}': {e}")
            
    # 3. Chequear ejecuciones perdidas (Robustez)
    check_missed_runs()
    
    # 4. Programar republicación MQTT (cada 60s) si está activo
    if MQTT_ENABLED:
        schedule.every(60).seconds.do(publish_mqtt_task)
        # Ejecución inicial para asegurar que los sensores aparezcan rápido al arrancar
        publish_mqtt_task()
    
    # 5. Bucle principal
    while True:
        try:
            n = schedule.idle_seconds()
            if n is None:
                # No hay trabajos, dormimos un poco y chequeamos de nuevo (raro caso)
                time.sleep(60)
            elif n > 0:
                # Dormir hasta la próxima tarea
                time.sleep(n)
            
            schedule.run_pending()
            
        except KeyboardInterrupt:
            print("\nScheduler detenido por usuario.")
            break
        except Exception as e:
            print(f"[{datetime.now()}] Error en bucle principal: {e}")
            time.sleep(60)

if __name__ == "__main__":
    main()
