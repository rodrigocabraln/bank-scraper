import http.server
import socketserver
import os
import logging
import mimetypes
from pathlib import Path

from config import OUTPUT_JSON

logger = logging.getLogger(__name__)

# Directorio de logos (relativo al script)
LOGOS_DIR = Path(__file__).parent / "banks" / "logos"


class JSONRequestHandler(http.server.SimpleHTTPRequestHandler):
    timeout = 5  # Timeout de 5 segundos para evitar conexiones colgadas
    
    def log_message(self, format, *args):
        # Silenciar logs HTTP para no saturar
        pass

    def do_GET(self):
        try:
            # 1. Seguridad: IP Filter
            allowed_ips_str = os.getenv("ALLOWED_IPS", "").strip()
            if allowed_ips_str:
                client_ip = self.client_address[0]
                allowed_list = [ip.strip() for ip in allowed_ips_str.split(",") if ip.strip()]
                if allowed_list and client_ip not in allowed_list:
                    self.send_error(403, "Forbidden")
                    return

            # 2. Rutas para logos estáticos
            if self.path.startswith("/logos/"):
                self._serve_logo()
                return

            # 3. Rutas permitidas para JSON
            if self.path != "/accounts.json":
                self.send_error(404, "Not Found")
                return

            # 4. Servir el JSON
            if not os.path.exists(OUTPUT_JSON):
                self.send_error(404, "File not found yet")
                return

            with open(OUTPUT_JSON, "rb") as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(content)
            
        except BrokenPipeError:
            pass
        except Exception as e:
            logger.error(f"Error sirviendo JSON: {e}")
            try:
                self.send_error(500, "Internal Server Error")
            except:
                pass

    def _serve_logo(self):
        """Sirve archivos de logo desde el directorio de logos."""
        filename = self.path.replace("/logos/", "", 1)
        
        # Prevenir path traversal
        if ".." in filename or "/" in filename or "\\" in filename:
            self.send_error(403, "Forbidden")
            return
        
        logo_path = LOGOS_DIR / filename
        
        if not logo_path.exists() or not logo_path.is_file():
            self.send_error(404, "Logo not found")
            return
        
        mime_type, _ = mimetypes.guess_type(str(logo_path))
        if not mime_type:
            mime_type = "application/octet-stream"
        
        try:
            with open(logo_path, "rb") as f:
                content = f.read()
            
            self.send_response(200)
            self.send_header("Content-Type", mime_type)
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(content)
        except Exception as e:
            logger.error(f"Error sirviendo logo {filename}: {e}")
            self.send_error(500, "Internal Server Error")


def start_http_server():
    port_str = os.getenv("HTTP_PORT", "8000")
    try:
        port = int(port_str)
    except ValueError:
        logger.warning(f"HTTP_PORT inválido ({port_str}), usando 8000 por defecto.")
        port = 8000

    socketserver.ThreadingTCPServer.allow_reuse_address = True
    
    try:
        server = socketserver.ThreadingTCPServer(("0.0.0.0", port), JSONRequestHandler)
        logger.info(f"Servidor HTTP iniciado en puerto {port}")
        server.serve_forever()
    except OSError as e:
        logger.error(f"Error iniciando servidor HTTP en puerto {port}: {e}")

