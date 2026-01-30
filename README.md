# Bank Scraper

Herramienta automatizada para extraer saldos de cuentas bancarias (BROU, OCA, etc.) y publicarlos vía MQTT para integración con Home Assistant.

> [!IMPORTANT]
> **Este software es para uso personal. Úsalo bajo tu propia responsabilidad.**
> 
> Este proyecto fue creado como experimento con [Antigravity](https://github.com/google-gemini/antigravity) y agentes de IA, aunque no fue "vibecodeado" (el código fue revisado, entendido y ajustado manualmente).

> [!WARNING]
> **Privacidad y Seguridad**: Este proyecto maneja credenciales sensibles.
> * Las credenciales se almacenan de forma segura y cifrada localmente.
> * **NUNCA** compartas logs, capturas de pantalla o archivos de datos que contengan números de cuenta, saldos reales o contraseñas.

## Funcionalidades
- **Soporte Multi-banco**: Extracción de saldos para BROU (Personas) y OCA (Blue y Tarjetas).
- **Seguridad Robusta**: Credenciales cifradas con Fernet (AES-128-CBC + HMAC).
- **MQTT Auto Discovery**: Integración automática con Home Assistant vía MQTT.
- **Evasión de Bloqueos**: Navegación con "jitter" (retrasos aleatorios) para simular comportamiento humano.
- **Docker Ready**: Contenedor optimizado con Firefox y Geckodriver.
- **Servidor HTTP**: API simple interna para consultar el JSON de saldos.

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

**Variables de Entorno:**

| Variable | Descripción | Default |
| :--- | :--- | :--- |
| `BANKS` | Bancos a procesar (módulos en `banks/`) | *requerido* |
| `CREDS_KEY` | Clave Fernet (ver paso 4) | *requerido* |
| `SCHEDULE_HOURS` | Horarios de ejecución HH:MM | `07:00,20:00` |
| `RANDOM_DELAY_MIN` | Jitter en minutos | `30` |
| `TZ` | Zona horaria | `America/Montevideo` |

**MQTT (Home Assistant):**

| Variable | Descripción | Default |
| :--- | :--- | :--- |
| `MQTT_ENABLED` | Activar MQTT | `false` |
| `MQTT_BROKER` | IP del broker | *requerido si enabled* |
| `MQTT_PORT` | Puerto | `1883` |
| `MQTT_USER` / `MQTT_PASS` | Credenciales (opcional) | *vacío* |
| `MQTT_TOPIC_PREFIX` | Prefijo de tópicos | `banks` |

**HTTP Server (alternativo):**

| Variable | Descripción | Default |
| :--- | :--- | :--- |
| `HTTP_PORT` | Puerto del servidor | `8000` |
| `HTTP_HOST` | Host para URLs de logos | `localhost` |
| `ALLOWED_IPS` | IPs permitidas (vacío=todas) | *vacío* |

**Avanzado:**

| Variable | Descripción | Default |
| :--- | :--- | :--- |
| `CREDENTIALS_DIRECTORY` | Dir de credenciales | `/dev/shm/creds` |
| `GECKODRIVER_LOGS` | Logs debug driver | `0` |
| `HEADLESS` | Sin interfaz gráfica | `1` |

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

## 🏠 Integración con Home Assistant

Esta herramienta utiliza **MQTT Auto Discovery**, lo que permite que Home Assistant detecte y cree automáticamente sensores individuales para cada cuenta bancaria sin configuración manual en YAML.

### Requisitos
- **Broker MQTT**: Necesitás tener un broker MQTT corriendo (ej: [Mosquitto](https://mosquitto.org/)).
- **Integración MQTT en HA**: La integración MQTT debe estar configurada en Home Assistant.

### Paso 1: Configurar Broker MQTT / Integración
> [!NOTE]
> Si utilizas **Home Assistant OS**, puedes instalar el broker como un Add-on. Si ya tienes un broker externo, asegúrate de configurar la integración MQTT.

1. **Home Assistant OS**: Ve a **Settings** -> **Add-ons** -> **Add-on Store**, instala **Mosquitto broker** y asegúrate de que esté iniciado.
2. Ve a **Settings** -> **Devices & Services** y confirma que la integración **MQTT** esté configurada y conectada al broker.

### Paso 2: Configurar el Scraper
Edita tu archivo `.env` con los datos de tu broker:
```env
MQTT_ENABLED=true
MQTT_BROKER=192.168.1.50  # IP de tu Broker MQTT
MQTT_PORT=1883
MQTT_USER=tu_usuario_mqtt
MQTT_PASS=tu_password_mqtt
```

### Paso 3: Entidades Creadas
Una vez que el scraper corra, verás por cada banco:
- **Dispositivo** con el nombre del banco (ej: "Brou Personas", "Oca")
- **Sensores** para cada cuenta con el saldo como estado
- **Binary Sensor** de estado (problema/ok) por banco

### Paso 4: Visualización Avanzada (Lovelace)

Para una visualización mejorada: (disponible en HACS)
- [lovelace-auto-entities](https://github.com/thomasloven/lovelace-auto-entities)
- [custom-button-card](https://github.com/custom-cards/button-card)

#### Template Lovelace Recomendado
```yaml
type: vertical-stack
cards:
  - type: custom:auto-entities
    card:
      type: grid
      columns: 1
      square: false
    card_param: cards
    filter:
      template: |
        {# 1. FILTRO DE SENSORES #} 
        {% set accounts = states.sensor 
          | selectattr('attributes.bank', 'defined')
          | selectattr('attributes.type', 'defined') 
          | list %}

        {% set ns = namespace(cards=[]) %}
        {% for acc in accounts %}
          {% set attrs = acc.attributes %}
          
          {# --- 2. EXTRACCIÓN Y FORMATEO DE FECHA (DD/MM/AAAA HH:MM) --- #}
          {% set raw_date = attrs['Last updated'] if attrs['Last updated'] is defined else attrs.last_updated %}
          {% if raw_date %}
            {# Convertimos a datetime, ajustamos a zona horaria local y formateamos #}
            {% set date_obj = as_datetime(raw_date) %}
            {% set date_str = (date_obj | as_local).strftime('%d/%m/%Y %H:%M') if date_obj else raw_date %}
          {% else %}
            {% set date_str = '---' %}
          {% endif %}
          
          {# --- 3. LÓGICA DE SALDOS Y TIPO --- #}
          {% set is_cc = attrs.type == 'CREDIT_CARD' %}
          
          {% set bal_obj = attrs.balance if attrs.balance is defined else none %}
          {% set avail_obj = attrs.available if attrs.available is defined else bal_obj %}
          
          {% set avail_num = avail_obj.number if avail_obj and avail_obj.number is not none else 0 %}
          {% set avail_raw = avail_obj.raw if avail_obj and avail_obj.raw else "---" %}
          
          {% set status_color = "#f44336" if avail_num < 1000 else "#4caf50" %}
          {% set logo_url = attrs.logo | default('/local/icons/bank_default.png') %}

          {# --- 4. CONFIGURACIÓN DE GRILLA --- #}
          {% if is_cc %}
            {% set grid_areas = '"i n bal avail" "i l bal avail"' %}
            {% set grid_cols = "45px 1fr 80px 80px" %}
            {% set bal_raw = bal_obj.raw if bal_obj and bal_obj.raw else "0" %}
            {% set bal_html = "<span>Movimientos:</span><br>" ~ bal_raw %}
          {% else %}
            {% set grid_areas = '"i n avail" "i l avail"' %}
            {% set grid_cols = "45px 1fr 100px" %}
            {% set bal_html = "" %}
          {% endif %}

          {# --- 5. GENERACIÓN DE LA TARJETA --- #}
          {% set ns.cards = ns.cards + [{
            "type": "custom:button-card",
            "entity": acc.entity_id,
            "name": attrs.bank | replace('_', ' ') | upper,
            
            "label": attrs.account_number ~ "<br><span style='font-size: 10px; opacity: 0.7; font-weight: normal;'>" ~ date_str ~ "</span>",
            "show_label": true,
            
            "show_entity_picture": true,
            "entity_picture": logo_url,
            "custom_fields": {
              "bal": bal_html,
              "avail": "<span>Saldo Disp:</span><br><b>" ~ avail_raw ~ "</b>"
            },
            "styles": {
              "card": [
                {"padding": "10px"},
                {"border-radius": "12px"},
                {"border": "1px solid var(--divider-color)"}
              ],
              "grid": [
                {"grid-template-areas": grid_areas},
                {"grid-template-columns": grid_cols}
              ],
              "entity_picture": [
                {"width": "32px"},
                {"height": "32px"},
                {"object-fit": "contain"} 
              ],
              "name": [
                {"justify-self": "start"},
                {"font-weight": "bold"},
                {"font-size": "13px"},
                {"align-self": "end"}
              ],
              "label": [
                {"justify-self": "start"},
                {"font-size": "11px"},
                {"align-self": "start"},
                {"text-align": "left"},
                {"line-height": "1.3"}
              ],
              "custom_fields": {
                "bal": [
                  {"text-align": "right"},
                  {"font-size": "11px"},
                  {"color": status_color if is_cc else "var(--primary-text-color)"},
                  {"display": "block" if is_cc else "none"}
                ],
                "avail": [
                  {"text-align": "right"},
                  {"font-size": "12px"},
                  {"font-weight": "bold"},
                  {"color": status_color}
                ]
              }
            }
          }] %}
        {% endfor %}
        {{ ns.cards }}

```

---

## API HTTP (Alternativa)

El servicio también expone un servidor HTTP (puerto por defecto: `8000`) para consultar el JSON directamente.

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

---

## Estructura del Proyecto
* `main.py`: Lógica principal de scraping y orquestación.
* `scheduler.py`: Manejador de tareas programadas y demonio del servidor HTTP.
* `http_server.py`: Implementación del servidor web simple.
* `mqtt_publisher.py`: Publicación de datos a MQTT con Auto Discovery.
* `config.py`: Constantes centralizadas del proyecto.
* `setup.py`: Utilidad para cifrado y guardado seguro de credenciales.
* `banks/`: Módulos específicos para cada institución financiera.
  * `common.py`: Funciones compartidas (parseo, timezone, etc).
* `data/`: Almacenamiento de resultados (JSON) y estado de ejecución.
* `logs/`: Logs de ejecución y de Geckodriver (ignorados por git).

## Desarrollo y Contribución
Para agregar un nuevo banco:
1. Crea un archivo en `banks/mi_banco.py`.
2. Define `BANK_KEY`, `CREDENTIAL_FIELDS` y la función `run(driver, env)`.
3. Asegúrate de no incluir datos reales en tus pruebas o commits.
