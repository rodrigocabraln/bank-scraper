# Bank Scraper

Herramienta automatizada para extraer saldos de cuentas bancarias y publicarlos vía MQTT para integración con Home Assistant.

---

## ⚠️ Disclaimer / Aviso Legal

> [!CAUTION]
> **Este proyecto NO opera con dinero ni realiza movimientos de ningún tipo.**
> 
> Bank Scraper es una herramienta de **solo lectura** que únicamente extrae y muestra saldos de cuentas bancarias. No tiene la capacidad de realizar transferencias, pagos, ni ninguna otra operación financiera.

> [!IMPORTANT]
> **Uso bajo tu propia responsabilidad.**
> 
> Este proyecto nació como una solución personal para centralizar la visualización de saldos en un dashboard. Si decides utilizarlo:
> - **Revisá y entendé el código** antes de ejecutarlo.
> - Ejecutalo bajo tu propia responsabilidad y riesgo.
> - No existe ninguna garantía implícita ni explícita sobre su funcionamiento.
> - El autor no se hace responsable por el uso que terceros hagan de este software.

> [!WARNING]
> **Privacidad y Seguridad**: Este proyecto maneja credenciales sensibles.
> - Las credenciales se almacenan de forma segura y cifradas localmente.
> - **NUNCA** compartas logs, capturas de pantalla o archivos de datos que contengan números de cuenta, saldos reales o contraseñas.

> [!NOTE]
> **Marcas Registradas**: Todas las marcas mencionadas son propiedad de sus respectivos titulares. Este software **no está afiliado, respaldado ni patrocinado** por ninguna entidad bancaria o financiera.

---

## Funcionalidades
- **Soporte Multi-banco**: Extracción de saldos para múltiples instituciones financieras.
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
| `ALLOWED_IPS` | IPs permitidas (vacío=todas) | *vacío* |

**Avanzado:**

| Variable | Descripción | Default |
| :--- | :--- | :--- |
| `CREDENTIALS_DIRECTORY` | Dir de credenciales (ver nota abajo) | `/dev/shm/creds` |
| `GECKODRIVER_LOGS` | Logs debug driver | `0` |
| `HEADLESS` | Sin interfaz gráfica | `1` |

> [!TIP]
> **`CREDENTIALS_DIRECTORY`** tiene dos opciones:
> - `/dev/shm/creds` (RAM): Las credenciales se borran al reiniciar el contenedor. Mayor seguridad.
> - `/app/data/creds` (persistente): Las credenciales persisten entre reinicios. Más conveniente.

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

### Paso 3: Copiar Logos a Home Assistant
Los logos de los bancos deben copiarse a la carpeta `www` de HA para que funcionen desde cualquier red:

```bash
# En tu servidor de Home Assistant
mkdir -p /config/www/bank-logos

# Copiar los logos (desde el repo clonado o el container)
cp bank-logos/*.webp /config/www/bank-logos/
```

Los logos quedarán accesibles en HA como `/local/bank-logos/xxx.webp`.

### Paso 4: Entidades Creadas
Una vez que el scraper corra, verás por cada banco:
- **Dispositivo** con el nombre del banco
- **Sensores** para cada cuenta con el saldo como estado
- **Binary Sensor** de estado (problema/ok) por banco

### Paso 5: Visualización Avanzada (Lovelace)

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
        {% set accounts = states.sensor 
          | selectattr('attributes.bank', 'defined')
          | selectattr('attributes.type', 'defined') 
          | selectattr('attributes.logo', 'defined')
          | list %}

        {% set ns = namespace(cards=[]) %}
        {% for acc in accounts %}
          {% set attrs = acc.attributes %}
          {% set is_cc = attrs.type == 'CREDIT_CARD' %}
          {% set avail_num = attrs.available_number | default(0) | float %}
          {% set avail_raw = attrs.available_raw | default('---') %}
          {% set status_color = "#f44336" if avail_num < 1000 else "#4caf50" %}
          {% set logo_url = '/local/bank-logos/' ~ attrs.logo %}
          
          {# Fecha formateada #}
          {% set raw_date = attrs.last_updated | default(none) %}
          {% set date_str = ((as_datetime(raw_date) | as_local).strftime('%d/%m/%Y %H:%M')) if raw_date else '---' %}
          
          {# Config por tipo #}
          {% if is_cc %}
            {% set grid_areas = '"i n bal avail" "i l bal avail"' %}
            {% set grid_cols = "45px 1fr 80px 80px" %}
            {% set bal_html = "<span>Consumos:</span><br>" ~ (attrs.balance_raw | default('0')) %}
          {% else %}
            {% set grid_areas = '"i n avail" "i l avail"' %}
            {% set grid_cols = "45px 1fr 100px" %}
            {% set bal_html = "" %}
          {% endif %}

          {% set ns.cards = ns.cards + [{
            "type": "custom:button-card",
            "entity": acc.entity_id,
            "name": attrs.bank | replace('_', ' ') | upper,
            "label": attrs.account_number ~ "<br><span style='font-size:10px;opacity:.7'>" ~ date_str ~ "</span>",
            "show_label": true,
            "show_entity_picture": true,
            "entity_picture": logo_url,
            "custom_fields": {
              "bal": bal_html,
              "avail": "<span>Disponible:</span><br><b>" ~ avail_raw ~ "</b>"
            },
            "styles": {
              "card": [{"padding": "10px"}, {"border-radius": "12px"}, {"border": "1px solid var(--divider-color)"}],
              "grid": [{"grid-template-areas": grid_areas}, {"grid-template-columns": grid_cols}],
              "entity_picture": [{"width": "32px"}, {"height": "32px"}, {"object-fit": "contain"}],
              "name": [{"justify-self": "start"}, {"font-weight": "bold"}, {"font-size": "13px"}, {"align-self": "end"}],
              "label": [{"justify-self": "start"}, {"font-size": "11px"}, {"align-self": "start"}, {"text-align": "left"}, {"line-height": "1.3"}],
              "custom_fields": {
                "bal": [{"text-align": "right"}, {"font-size": "11px"}, {"color": status_color if is_cc else "var(--primary-text-color)"}, {"display": "block" if is_cc else "none"}],
                "avail": [{"text-align": "right"}, {"font-size": "12px"}, {"font-weight": "bold"}, {"color": status_color}]
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
    "<BANK_KEY>": {
      "updated_at": "...",
      "accounts": [
        {
          "type": "CREDIT_CARD",
          "currency": "UYU",
          "account_number": "<ACCOUNT>",
          "balance": { "raw": "$ <AMOUNT>", "number": 5000.0 },
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
