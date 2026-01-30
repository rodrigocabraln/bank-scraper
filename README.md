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

## 🏠 Integración con Home Assistant (MQTT)

Esta herramienta utiliza **MQTT Auto Discovery**, lo que permite que Home Assistant detecte y cree automáticamente sensores individuales para cada cuenta bancaria sin configuración manual en YAML.

### Paso 1: Configurar Mosquitto Broker en HA
1. Ve a **Settings** -> **Add-ons** -> **Add-on Store**.
2. Busca e instala **Mosquitto broker**.
3. Inicia el add-on y asegúrate de que **Watchdog** esté activado.
4. Ve a **Settings** -> **Devices & Services** y confirma que la integración **MQTT** esté configurada (HA debería detectarla automáticamente).

### Paso 2: Configurar el Scraper
Edita tu archivo `.env` con los datos de tu broker:
```env
MQTT_ENABLED=true      # Habilitar/Deshabilitar MQTT
MQTT_TOPIC_PREFIX=banks # Prefijo de los tópicos (opcional)
MQTT_BROKER=10.1.1.51  # IP de tu Home Assistant
MQTT_PORT=1883
MQTT_USER=tu_usuario_mqtt
MQTT_PASS=tu_password_mqtt
```

### Paso 3: Visualización
Una vez que el scraper corra, verás un nuevo **Dispositivo** llamado **Bank Scraper** por cada banco, con entidades para cada cuenta.

Para una visualización avanzada (opcional), se recomienda instalar vía **HACS**:
- [lovelace-auto-entities](https://github.com/thomasloven/lovelace-auto-entities)
- [custom-button-card](https://github.com/custom-cards/button-card)

#### Ejemplo de Card (Lovelace)
```yaml
type: vertical-stack
cards:
  - type: tile
    entity: sensor.bank_scraper_last_update # Tópico general
    name: Última Sincronización
    icon: mdi:cloud-sync
  - type: custom:auto-entities
    card:
      type: grid
      columns: 1
      square: false
    card_param: cards
    filter:
      include:
        - domain: sensor
          attributes:
            bank: "*"
      template: >
        {% set ns = namespace(cards=[]) %}
        {% for state in (states.sensor | selectattr('attributes.bank', 'defined') | list) %}
          {# Evitar duplicados si hay sensores de balance #}
          {% if not state.entity_id.endswith('_balance') %}
            {% set acc = state.attributes %}
            {% set ns.cards = ns.cards + [{
              "type": "custom:button-card",
              "entity": state.entity_id,
              "name": acc.bank | replace('_', ' ') | upper,
              "label": acc.account_number,
              "show_label": true,
              "show_entity_picture": true,
              "entity_picture": acc.logo,
              "custom_fields": {
                "bal": "<span>Movimientos:</span><br>" ~ acc.balance_raw if acc.is_credit_card else "",
                "avail": "<span>Saldo Disp:</span><br><b>" ~ acc.available_raw ~ "</b>"
              },
              "styles": {
                "card": [{"padding": "10px"}, {"border-radius": "12px"}, {"border": "1px solid var(--divider-color)"}],
                "grid": [
                  {"grid-template-areas": '"i n bal avail" "i l bal avail"' if acc.is_credit_card else '"i n avail" "i l avail"'},
                  {"grid-template-columns": "45px 1fr 80px 80px" if acc.is_credit_card else "45px 1fr 100px"}
                ],
                "entity_picture": [{"width": "32px"}, {"height": "32px"}, {"object-fit": "contain"}],
                "name": [{"justify-self": "start"}, {"font-weight": "bold"}, {"font-size": "13px"}, {"align-self": "end"}],
                "label": [{"justify-self": "start"}, {"font-size": "10px"}, {"opacity": "0.6"}, {"align-self": "start"}],
                "custom_fields": {
                  "bal": [{"text-align": "right"}, {"font-size": "11px"}, {"display": "block" if acc.is_credit_card else "none"}],
                  "avail": [{"text-align": "right"}, {"font-size": "12px"}, {"font-weight": "bold"}]
                }
              }
            }] %}
          {% endif %}
        {% endfor %}
        {{ ns.cards }}
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

