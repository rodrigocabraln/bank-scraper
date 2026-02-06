"""
Publicador MQTT para Home Assistant.

Este módulo publica los datos de saldos bancarios a un broker MQTT
usando el protocolo Home Assistant MQTT Discovery, permitiendo que
los sensores se creen automáticamente en Home Assistant.

Características:
    - Auto-discovery de sensores en Home Assistant
    - Publicación de estado de bancos (ok/error) como binary_sensor
    - Publicación de cuentas individuales como sensors monetarios
    - Aplanamiento de objetos anidados para compatibilidad con HA
    - Manejo de valores null con defaults sensatos

Tópicos MQTT generados:
    - homeassistant/binary_sensor/{prefix}/{bank}_status/...
    - homeassistant/sensor/{prefix}/{bank}_{account}_{currency}/...

Uso:
    Este módulo es llamado por scheduler.py después de cada ejecución
    del scraper. No se ejecuta directamente.
"""
import json
import logging
import os
import re
import time
import paho.mqtt.client as mqtt

from banks.common import normalize_currency

logger = logging.getLogger(__name__)


# =============================================================================
# FUNCIONES AUXILIARES
# =============================================================================

def _remove_consecutive_duplicates(text: str, separator: str = "_") -> str:
    """
    Elimina palabras consecutivas duplicadas en un texto.
    
    Útil para limpiar IDs generados que pueden tener redundancias
    como "oca_oca_blue" que debería ser "oca_blue".
    
    Args:
        text: Texto a limpiar.
        separator: Carácter separador de palabras.
        
    Returns:
        str: Texto sin duplicados consecutivos.
        
    Examples:
        >>> _remove_consecutive_duplicates("foo_foo_bar_123")
        'foo_bar_123'
        >>> _remove_consecutive_duplicates("bank_bank_bank_test")
        'bank_test'
    """
    if not text:
        return text
    parts = text.split(separator)
    result = [parts[0]] if parts else []
    for part in parts[1:]:
        if part != result[-1]:
            result.append(part)
    return separator.join(result)


def _flatten_for_mqtt(account: dict) -> dict:
    """
    Aplana un objeto de cuenta para compatibilidad con Home Assistant.
    
    Los atributos JSON de Home Assistant no soportan bien objetos anidados,
    así que convertimos campos como balance y available a campos planos.
    También convierte valores null a defaults apropiados.
    
    Args:
        account: Diccionario de cuenta con posibles objetos anidados.
        
    Returns:
        dict: Cuenta con campos aplanados.
        
    Example:
        >>> _flatten_for_mqtt({"balance": {"raw": "$5", "number": 5}})
        {'balance_raw': '$5', 'balance_number': 5}
        
        >>> _flatten_for_mqtt({"available": {"raw": None, "number": None}})
        {'available_raw': '---', 'available_number': 0}
    """
    result = {}
    for key, value in account.items():
        if isinstance(value, dict) and key in ("balance", "available"):
            # Aplanar: balance → balance_raw, balance_number
            for subkey, subvalue in value.items():
                flat_key = f"{key}_{subkey}"
                # Convertir null a defaults sensatos
                if subvalue is None:
                    result[flat_key] = "---" if subkey == "raw" else 0
                else:
                    result[flat_key] = subvalue
        elif value is None:
            result[key] = "---"
        else:
            result[key] = value
    return result


# =============================================================================
# PUBLICACIÓN DE ENTIDADES
# =============================================================================

def _publish_bank_status(client, bank_name: str, bank_data: dict, updated_at: str = None) -> None:
    """
    Publica el estado general de un banco como binary_sensor.
    
    Crea un binary_sensor con device_class "problem" que indica
    si el scraping del banco fue exitoso o falló.
    
    Args:
        client: Cliente MQTT conectado.
        bank_name: Nombre identificador del banco.
        bank_data: Datos del banco (puede contener "error").
        updated_at: Timestamp de la última actualización.
    """
    prefix = os.getenv("MQTT_TOPIC_PREFIX", "banks").strip()
    safe_bank_id = f"{bank_name}_status".lower().replace(" ", "_")
    base_topic = f"homeassistant/binary_sensor/{prefix}/{safe_bank_id}"
    
    is_error = isinstance(bank_data, dict) and "error" in bank_data
    
    # Configuración de autodiscovery
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
    
    # Estado: ON = problema, OFF = ok
    state = "ON" if is_error else "OFF"
    
    # Publicar config, estado y atributos
    client.publish(f"{base_topic}/config", json.dumps(config), retain=True, qos=1)
    client.publish(f"{base_topic}/state", state, retain=True, qos=1)
    
    attributes = {
        "error": bank_data.get("error") if is_error else None,
        "updated_at": bank_data.get("updated_at") if isinstance(bank_data, dict) else None,
        "last_updated": updated_at or bank_data.get("updated_at")
    }
    client.publish(f"{base_topic}/attributes", json.dumps(attributes), retain=True, qos=1)


def _publish_account(client, bank_name: str, account: dict, idx: int, updated_at: str = None) -> None:
    """
    Publica una cuenta individual como sensor monetario.
    
    Crea un sensor con device_class "monetary" que muestra el saldo
    disponible (para cuentas) o el balance/consumos (para tarjetas).
    
    Args:
        client: Cliente MQTT conectado.
        bank_name: Nombre identificador del banco.
        account: Diccionario con datos de la cuenta.
        idx: Índice de la cuenta (usado si no tiene account_number).
        updated_at: Timestamp de la última actualización.
    """
    account_num = account.get("account_number", f"account_{idx}")
    currency = normalize_currency(account.get("currency", ""), output_format="code")
    
    # Construir ID único: bank_account_currency
    raw_id = f"{bank_name}_{account_num}_{currency}".lower()
    # Sanitizar: reemplazar separadores comunes por underscore, luego eliminar
    # cualquier caracter no alfanumérico (previene $, €, #, +, / en tópicos MQTT)
    safe_id = raw_id.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_")
    safe_id = re.sub(r'[^a-z0-9_]', '', safe_id)
    # Eliminar redundancias (ej: oca_oca_blue → oca_blue)
    safe_id = _remove_consecutive_duplicates(safe_id)
    
    prefix = os.getenv("MQTT_TOPIC_PREFIX", "banks").strip()
    base_topic = f"homeassistant/sensor/{prefix}/{safe_id}"

    # Configuración de autodiscovery
    config = {
        "name": f"{bank_name.replace('_', ' ').title()} {account_num}",
        "unique_id": safe_id,
        "state_topic": f"{base_topic}/state",
        "json_attributes_topic": f"{base_topic}/attributes",
        "unit_of_measurement": account.get("currency", "UYU"),
        "device_class": "monetary",
        "state_class": "total",
        "icon": "mdi:bank",
        "device": {
            "identifiers": [f"bank_{bank_name}"],
            "name": bank_name.replace('_', ' ').title(),
            "manufacturer": "Bank Scraper"
        }
    }

    # Publicar configuración
    client.publish(f"{base_topic}/config", json.dumps(config), retain=True, qos=1)
    
    # Estado: disponible para ACCOUNT, balance para CREDIT_CARD
    if account.get("type") == "CREDIT_CARD":
        state_value = account.get("balance", {}).get("number", 0)
    else:
        state_value = account.get("available", {}).get("number", 0)
        
    client.publish(f"{base_topic}/state", str(state_value), retain=True, qos=1)
    
    # Atributos: todos los datos de la cuenta aplanados
    flattened_account = _flatten_for_mqtt(account)
    attributes = {**flattened_account, "bank": bank_name, "last_updated": updated_at}
    client.publish(f"{base_topic}/attributes", json.dumps(attributes), retain=True, qos=1)


# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def publish_to_mqtt(data: dict) -> None:
    """
    Publica los datos del scraper a MQTT con Home Assistant Discovery.
    
    Conecta al broker MQTT, publica el timestamp general, estado de
    cada banco, y cada cuenta individual. Usa un bucle de eventos
    asíncrono para garantizar que todos los mensajes se envíen.
    
    Args:
        data: Diccionario con la estructura:
            {
                "updated_at": "2026-01-30T22:00:00-03:00",
                "banks": {
                    "bank_name": {
                        "updated_at": "...",
                        "accounts": [...]
                    }
                }
            }
            
    Environment Variables:
        MQTT_BROKER: IP/hostname del broker (requerido)
        MQTT_PORT: Puerto del broker (default: 1883)
        MQTT_USER: Usuario para autenticación
        MQTT_PASS: Contraseña para autenticación
        MQTT_TOPIC_PREFIX: Prefijo de tópicos (default: banks)
    """
    mqtt_broker = os.getenv("MQTT_BROKER")
    if not mqtt_broker:
        logger.info("MQTT_BROKER no configurado. Saltando publicación MQTT.")
        return

    mqtt_port = int(os.getenv("MQTT_PORT", "1883"))
    mqtt_user = os.getenv("MQTT_USER")
    mqtt_pass = os.getenv("MQTT_PASS")

    # Usar API v2 de paho-mqtt si está disponible
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    except AttributeError:
        client = mqtt.Client()

    if mqtt_user and mqtt_pass:
        client.username_pw_set(mqtt_user, mqtt_pass)

    try:
        # Conexión asíncrona
        client.connect(mqtt_broker, mqtt_port, 60)
        client.loop_start()
        
        # Esperar conexión
        time.sleep(1)

        # Publicar timestamp general
        client.publish(
            "bank_scraper/last_update",
            data.get("updated_at", ""),
            retain=True,
            qos=1
        )

        # Publicar cada banco
        for bank_name, bank_data in data.get("banks", {}).items():
            # Obtener updated_at del banco o global
            bank_updated_at = None
            if isinstance(bank_data, dict):
                bank_updated_at = bank_data.get("updated_at") or data.get("updated_at")
            
            # Siempre publicar estado del banco
            _publish_bank_status(client, bank_name, bank_data, bank_updated_at)
            
            # Publicar cuentas si no hay error
            if isinstance(bank_data, dict) and "error" not in bank_data:
                accounts = bank_data.get("accounts", [])
                for idx, account in enumerate(accounts):
                    _publish_account(client, bank_name, account, idx, bank_updated_at)
            elif isinstance(bank_data, dict) and "error" in bank_data:
                logger.warning(f"Banco {bank_name} reportó error: {bank_data['error']}. Publicando solo estado.")

        # Esperar a que se envíen los mensajes
        time.sleep(2)
        
        client.loop_stop()
        client.disconnect()
        logger.info("Publicación MQTT completada con éxito.")
        
    except Exception as e:
        logger.error(f"Error publicando en MQTT: {e}")
