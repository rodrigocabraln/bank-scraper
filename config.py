"""
Configuración centralizada del proyecto Bank Scraper.

Este módulo contiene constantes, paths y configuración de logging
compartida por todos los módulos del proyecto.

Uso:
    from config import OUTPUT_JSON, setup_logging
"""
import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path


# =============================================================================
# PATHS
# =============================================================================

OUTPUT_JSON = "/app/data/accounts.json"
"""Ruta del archivo JSON de salida con los saldos."""

LOGS_DIR = Path("./logs")
"""Directorio para archivos de log."""


# =============================================================================
# CONFIGURACIÓN DE LOGGING
# =============================================================================

LOG_MAX_BYTES = 5 * 1024 * 1024  # 5MB
"""Tamaño máximo de cada archivo de log antes de rotar."""

LOG_BACKUP_COUNT = 3
"""Número de archivos de backup a mantener (total ~20MB máximo)."""

LOG_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
"""Formato de los mensajes de log."""

LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
"""Formato de fecha/hora en los logs."""


def setup_logging(name: str = __name__, log_to_file: bool = True) -> logging.Logger:
    """
    Configura y retorna un logger con formato consistente.
    
    Crea un logger con handlers para consola y opcionalmente archivo.
    El handler de archivo usa RotatingFileHandler para evitar
    crecimiento ilimitado.
    
    Args:
        name: Nombre del logger (típicamente __name__).
        log_to_file: Si True, también escribe logs a archivo con rotación.
    
    Returns:
        logging.Logger: Logger configurado y listo para usar.
        
    Example:
        >>> logger = setup_logging(__name__)
        >>> logger.info("Mensaje de prueba")
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
    
    # Handler para archivo con rotación
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
