"""
Servidor HTTP embebido para exponer datos de saldos.

Proporciona un endpoint REST simple para consultar el JSON de saldos
generado por el scraper. Diseñado para ser usado por Home Assistant
u otros sistemas de automatización.

Características:
    - Endpoint único: GET /accounts.json
    - Filtro de IPs permitidas (configurable via ALLOWED_IPS)
    - Sin logs HTTP para evitar saturación
    - Timeout de conexión para evitar conexiones colgadas

Uso:
    Este módulo es iniciado automáticamente por scheduler.py en un hilo separado.
    No se ejecuta directamente.
"""
import http.server
import socketserver
import os
import logging

from config import OUTPUT_JSON

logger = logging.getLogger(__name__)


# =============================================================================
# HANDLER HTTP
# =============================================================================

class JSONRequestHandler(http.server.SimpleHTTPRequestHandler):
    """
    Handler HTTP personalizado para servir el JSON de saldos.
    
    Solo responde a GET /accounts.json. Cualquier otra ruta retorna 404.
    Implementa filtrado de IPs y manejo robusto de errores.
    
    Attributes:
        timeout: Segundos antes de cerrar conexiones inactivas.
    """
    
    timeout = 5  # Evitar conexiones colgadas
    
    def log_message(self, format, *args):
        """Silencia los logs HTTP estándar para no saturar la consola."""
        pass

    def do_GET(self):
        """
        Maneja solicitudes GET.
        
        Flujo:
            1. Verificar IP del cliente contra ALLOWED_IPS
            2. Validar que la ruta sea /accounts.json
            3. Leer y servir el archivo JSON
        """
        try:
            # Verificar filtro de IPs
            allowed_ips_str = os.getenv("ALLOWED_IPS", "").strip()
            if allowed_ips_str:
                client_ip = self.client_address[0]
                allowed_list = [ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()]
                if allowed_list and client_ip not in allowed_list:
                    self.send_error(403, "Forbidden")
                    return

            # Solo permitir la ruta del JSON
            if self.path != "/accounts.json":
                self.send_error(404, "Not Found")
                return

            # Verificar que el archivo existe
            if not os.path.exists(OUTPUT_JSON):
                self.send_error(404, "File not found yet")
                return

            # Leer y servir el JSON
            with open(OUTPUT_JSON, "rb") as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
            
        except BrokenPipeError:
            # Cliente cerró la conexión, ignorar
            pass
        except Exception as e:
            logger.error(f"Error sirviendo JSON: {e}")
            try:
                self.send_error(500, "Internal Server Error")
            except Exception:
                pass


# =============================================================================
# SERVIDOR
# =============================================================================

def start_http_server() -> None:
    """
    Inicia el servidor HTTP en el puerto configurado.
    
    Lee HTTP_PORT del entorno (default: 8000) e inicia un servidor
    ThreadingTCPServer que puede manejar múltiples conexiones simultáneas.
    
    Esta función bloquea indefinidamente (serve_forever).
    Debe ser llamada en un hilo separado.
    
    Environment Variables:
        HTTP_PORT: Puerto en el que escuchar (default: 8000)
    """
    port_str = os.getenv("HTTP_PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"HTTP_PORT inválido ({port_str}), usando 8000 por defecto.")
        port = 8000

    # Permitir reutilizar el puerto inmediatamente después de cerrar
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    
    try:
        server = socketserver.ThreadingTCPServer(("0.0.0.0", port), JSONRequestHandler)
        logger.info(f"Servidor HTTP iniciado en puerto {port}")
        server.serve_forever()
    except OSError as e:
        logger.error(f"Error iniciando servidor HTTP en puerto {port}: {e}")
