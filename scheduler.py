import schedule
import time
import random
import subprocess
import os
import sys
import threading
from datetime import datetime, date

# Local imports
from http_server import start_http_server

# Configuración
SCHEDULE_HOURS_RAW = os.getenv("SCHEDULE_HOURS", "07:00,20:00")
SCHEDULE_HOURS = [h.strip() for h in SCHEDULE_HOURS_RAW.split(",") if h.strip()]
RANDOM_DELAY_MIN = int(os.getenv("RANDOM_DELAY_MIN", "30"))
STATE_FILE = "data/last_run.txt"


def run_scraper():
    """Ejecuta el script principal de scrapeo."""
    print(f"[{datetime.now()}] Iniciando trabajo de scraping...")
    try:
        # Llama a main.py usando el mismo intérprete de python
        subprocess.run([sys.executable, "main.py"], check=True)
        
        # Actualizar última ejecución
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            f.write(datetime.now().isoformat())
            
    except Exception as e:
        print(f"[{datetime.now()}] Trabajo falló: {e}")


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
    print(f"[{datetime.now()}] Scheduler iniciado. Horas: {SCHEDULE_HOURS}, Jitter: +{RANDOM_DELAY_MIN}m")
    
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
    
    # 4. Bucle principal
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
