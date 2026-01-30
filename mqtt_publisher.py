import json
import logging
import os
import time
from datetime import datetime
import paho.mqtt.client as mqtt

logger = logging.getLogger(__name__)

def _normalize_currency(currency: str) -> str:
    """
    Normaliza símbolos de moneda a códigos estándar para usar en IDs.
    Ej: '$' -> 'uyu', 'U$S' -> 'usd', 'US$' -> 'usd'
    """
    currency = currency.strip().upper()
    mapping = {
        "$": "uyu",
        "UYU": "uyu",
        "U$S": "usd",
        "US$": "usd",
        "USD": "usd",
        "€": "eur",
        "EUR": "eur",
    }
    return mapping.get(currency, currency.lower())

def _remove_consecutive_duplicates(text: str, separator: str = "_") -> str:
    """
    Elimina palabras consecutivas duplicadas en un texto separado por un delimitador.
    Ej: 'foo_foo_bar_123' -> 'foo_bar_123'
        'bank_bank_bank_test' -> 'bank_test'
    """
    if not text:
        return text
    parts = text.split(separator)
    result = [parts[0]] if parts else []
    for part in parts[1:]:
        if part != result[-1]:
            result.append(part)
    return separator.join(result)

def publish_to_mqtt(data):
    """
    Publica la data del scraper a MQTT con Home Assistant Discovery.
    Utiliza un bucle de eventos para asegurar que los mensajes se envíen antes de desconectar.
    """
    mqtt_broker = os.getenv("MQTT_BROKER")
    if not mqtt_broker:
        logger.info("MQTT_BROKER no configurado. Saltando publicación MQTT.")
        return

    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_user = os.getenv("MQTT_USER")
    mqtt_pass = os.getenv("MQTT_PASS")

    # Usar la nueva API de paho-mqtt v2 si está disponible
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()

    if mqtt_user and mqtt_pass:
        client.username_pw_set(mqtt_user, mqtt_pass)

    try:
        # Conectar de forma asíncrona
        client.connect(mqtt_broker, mqtt_port, 60)
        
        # Iniciar el bucle en segundo plano
        client.loop_start()
        
        # Esperar un poco a que la conexión se establezca (opcional pero recomendado)
        time.sleep(1)

        # Publicar timestamp general
        client.publish(
            "bank_scraper/last_update",
            data.get("updated_at", ""),
            retain=True,
            qos=1
        )

        for bank_name, bank_data in data.get("banks", {}).items():
            # Siempre publicamos el estado del banco
            _publish_bank_status(client, bank_name, bank_data)
            
            # Si es un diccionario y no tiene error, publicamos las cuentas
            if isinstance(bank_data, dict) and "error" not in bank_data:
                accounts = bank_data.get("accounts", [])
                for idx, account in enumerate(accounts):
                    _publish_account(client, bank_name, account, idx)
            elif isinstance(bank_data, dict) and "error" in bank_data:
                logger.warning(f"Banco {bank_name} reportó error: {bank_data['error']}. Publicando solo estado.")

        # Dar tiempo a que los mensajes se publiquen
        time.sleep(2)
        
        client.loop_stop()
        client.disconnect()
        logger.info("Publicación MQTT completada con éxito.")
    except Exception as e:
        logger.error(f"Error publicando en MQTT: {e}")

def _publish_bank_status(client, bank_name, bank_data):
    """Publica el estado general del banco (OK o Error) como un binary_sensor de problema."""
    prefix = os.getenv("MQTT_TOPIC_PREFIX", "banks").strip()
    safe_bank_id = f"{bank_name}_status".lower().replace(" ", "_")
    base_topic = f"homeassistant/binary_sensor/{prefix}/{safe_bank_id}"
    
    # Manejar el caso donde bank_data podría no ser un dict (aunque el scraper lo asegura)
    is_error = isinstance(bank_data, dict) and "error" in bank_data
    
    config = {
        "name": f"{bank_name.replace('_', ' ').title()} Status",
        "unique_id": safe_bank_id,
        "state_topic": f"{base_topic}/state",
        "device_class": "problem",
        "json_attributes_topic": f"{base_topic}/attributes",
        "device": {
            "identifiers": [f"bank_{bank_name}"],
            "name": bank_name.replace('_', ' ').title(),
            "manufacturer": "Bank Scraper"
        }
    }
    
    # HA Problem Binary Sensor: 'ON' means problem, 'OFF' means ok.
    state = "ON" if is_error else "OFF"
    
    client.publish(f"{base_topic}/config", json.dumps(config), retain=True, qos=1)
    client.publish(f"{base_topic}/state", state, retain=True, qos=1)
    
    attributes = {
        "error": bank_data.get("error") if is_error else None,
        "updated_at": bank_data.get("updated_at") if isinstance(bank_data, dict) else None,
        "last_updated": datetime.now().isoformat()
    }
    client.publish(f"{base_topic}/attributes", json.dumps(attributes), retain=True, qos=1)

def _publish_account(client, bank_name, account, idx):
    """Publica una cuenta individual con autodiscovery."""
    account_num = account.get("account_number", f"account_{idx}")
    currency = _normalize_currency(account.get("currency", ""))
    
    # Construir ID base: bank_account_currency
    raw_id = f"{bank_name}_{account_num}_{currency}".lower()
    # Sanitizar caracteres especiales
    safe_id = raw_id.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
    # Eliminar redundancias consecutivas (ej: oca_oca_blue -> oca_blue)
    safe_id = _remove_consecutive_duplicates(safe_id)
    
    # Prefijo de tópico configurable (default: banks)
    prefix = os.getenv("MQTT_TOPIC_PREFIX", "banks").strip()
    base_topic = f"homeassistant/sensor/{prefix}/{safe_id}"

    config = {
        "name": f"{bank_name.replace('_', ' ').title()} {account_num}",
        "unique_id": safe_id,
        "state_topic": f"{base_topic}/state",
        "json_attributes_topic": f"{base_topic}/attributes",
        "unit_of_measurement": account.get("currency", "UYU"),
        "device_class": "monetary",
        "state_class": "measurement",
        "icon": "mdi:bank",
        "device": {
            "identifiers": [f"bank_{bank_name}"],
            "name": bank_name.replace('_', ' ').title(),
            "manufacturer": "Bank Scraper"
        }
    }

    # Publicar Configuración
    client.publish(f"{base_topic}/config", json.dumps(config), retain=True, qos=1)
    
    # Publicar Estado (Saldo disponible para ACCOUNT, Balance para CREDIT_CARD)
    if account.get("type") == "CREDIT_CARD":
        state_value = account.get("balance", {}).get("number", 0)
    else:
        state_value = account.get("available", {}).get("number", 0)
        
    client.publish(f"{base_topic}/state", str(state_value), retain=True, qos=1)
    
    # Publicar todos los datos del JSON como atributos (incluyendo logos, etc.)
    attributes = {**account, "bank": bank_name, "last_updated": datetime.now().isoformat()}
    client.publish(f"{base_topic}/attributes", json.dumps(attributes), retain=True, qos=1)
