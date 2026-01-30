# Bank Scraper

Herramienta automatizada para extraer saldos de cuentas bancarias (BROU, OCA, etc.) y exportarlos en formato JSON. Diseñada para ser integrable con sistemas como Home Assistant.

> [!IMPORTANT]
> **Este software es para uso personal. Úsalo bajo tu propia responsabilidad.**

> [!WARNING]
> **Privacidad y Seguridad**: Este proyecto maneja credenciales sensibles.
> * Las credenciales se almacenan de forma segura y cifrada localmente.
> * **NUNCA** compartas logs, capturas de pantalla o archivos de datos que contengan números de cuenta, saldos reales o contraseñas.

## Funcionalidades
- **Soporte Multi-banco**: Extracción de saldos para BROU (Personas) y OCA (Blue y Tarjetas).
- **Seguridad Robusta**: Credenciales cifradas con Fernet (AES-128-CBC + HMAC).
- **Evasión de Bloqueos**: Navegación con "jitter" (retrasos aleatorios) para simular comportamiento humano.
- **Docker Ready**: Contenedor optimizado con Firefox y Geckodriver.
- **Servidor HTTP**: API simple interna para conectar con Home Assistant.

---

## 🚀 Guía de Instalación

### 1. Preparación del Entorno
Crea los directorios para persistencia:
```bash
mkdir -p data logs
```

### 2. Configuración
Copia el ejemplo de variables de entorno y edítalo:
```bash
cp .env.example .env
```

**Variables Clave:**
| Variable | Descripción | Ejemplo |
| :--- | :--- | :--- |
| `BANKS` | Lista de bancos a procesar (módulos en `banks/`) | `brou_personas,oca` |
| `CREDS_KEY` | Clave Fernet (ver paso 3) | *(clave generada)* |
| `SCHEDULE_HOURS` | Horarios de ejecución (HH:MM) | `07:00, 20:00` |
| `RANDOM_DELAY_MIN` | Minutos de aleatoriedad añadidos al horario | `30` |
| `ALLOWED_IPS` | Lista de IPs permitidas para la API HTTP | `192.168.1.10, 192.168.1.20` |

### 3. Ejecución con Docker
Construye y levanta el servicio:
```bash
docker compose build
docker compose up -d
```

### 4. Generar Clave de Cifrado
Las credenciales se cifran con Fernet (AES-128). Genera la clave dentro del contenedor:
```bash
docker compose exec bank-scraper python setup.py --generate-key
```
Copia la clave generada a tu `.env`:
```
CREDS_KEY=<CLAVE_GENERADA>
```
Reinicia para aplicar:
```bash
docker compose down && docker compose up -d
```

### 5. Carga de Credenciales
Ejecuta el asistente interactivo para cada banco:
```bash
docker compose exec -it bank-scraper python setup.py
```
*Sigue los pasos en pantalla para cada banco configurado.*

### 6. Ejecución Manual
Para verificar la configuración y realizar un scraping inmediato:
```bash
docker compose exec bank-scraper python main.py
```

---

## Uso de la API HTTP
El servicio expone un servidor HTTP ligero (puerto por defecto: `8000`) para consultar el último estado JSON.

**Endpoint:** `GET /accounts.json`

**Ejemplo de respuesta:**
```json
{
  "updated_at": "2026-01-29T10:30:00-03:00",
  "banks": {
    "oca": {
      "updated_at": "...",
      "accounts": [
        {
          "type": "CREDIT_CARD",
          "currency": "UYU",
          "account_number": "OCA 1234",
          "balance": { "raw": "$ 5.000", "number": 5000.0 },
          "available": { "raw": "$ 20.000", "number": 20000.0 }
        }
      ]
    }
  }
}
```

## Estructura del Proyecto
* `main.py`: Lógica principal de scraping y orquestación.
* `scheduler.py`: Manejador de tareas programadas y demonio del servidor HTTP.
* `http_server.py`: Implementación del servidor web simple.
* `setup.py`: Utilidad para cifrado y guardado seguro de credenciales.
* `banks/`: Módulos específicos para cada institución financiera.
* `data/`: Almacenamiento de resultados (JSON) y estado de ejecución.
* `logs/`: Logs de ejecución y de Geckodriver (ignorados por git).

## Desarrollo y Contribución
Para agregar un nuevo banco:
1. Crea un archivo en `banks/mi_banco.py`.
2. Define `BANK_KEY`, `CREDENTIAL_FIELDS` y la función `run(driver, env)`.
3. Asegúrate de no incluir datos reales en tus pruebas o commits.

