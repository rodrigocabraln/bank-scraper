"""
Configuración centralizada del proyecto Bank Scraper.

Este módulo contiene constantes y configuración compartida por todos los módulos.
"""

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

# --- Paths ---
OUTPUT_JSON = "/app/data/accounts.json"
LOGS_DIR = Path("./logs")

# --- Logging Configuration ---
# Máximo 5MB por archivo de log, mantener 3 backups (total ~20MB máximo)
LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB
LOG_BACKUP_COUNT = 3
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(name: str = __name__, log_to_file: bool = True) -> logging.Logger:
    """
    Configura y retorna un logger con formato consistente.
    
    Args:
        name: Nombre del logger (típicamente __name__).
        log_to_file: Si True, también escribe logs a archivo con rotación.
    
    Returns:
        Logger configurado.
    """
    logger = logging.getLogger(name)
    
    # Evitar configurar múltiples veces
    if logger.handlers:
        return logger
    
    logger.setLevel(logging.INFO)
    
    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
    logger.addHandler(console_handler)
    
    # Handler para archivo con rotación (evita saturar el SSD)
    if log_to_file:
        try:
            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            log_file = LOGS_DIR / "bank_scraper.log"
            file_handler = RotatingFileHandler(
                log_file,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding="utf-8"
            )
            file_handler.setFormatter(logging.Formatter(LOG_FORMAT, LOG_DATE_FORMAT))
            logger.addHandler(file_handler)
        except Exception as e:
            logger.warning(f"No se pudo configurar logging a archivo: {e}")
    
    return logger
