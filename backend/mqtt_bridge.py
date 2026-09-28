"""MQTT subscriber: turns hardware messages into service calls.

Topics (root = "splrt" by default):
  splrt/lrv/<device_id>/odometer     {"pulses": 15230}      or just  15230
  splrt/station/<station_id>/rfid    {"tag": "04A3B2C1"}    or just  04A3B2C1
  splrt/lrv/<device_id>/status       online | offline       (use as MQTT Last Will)
  splrt/station/<station_id>/status  online | offline
"""
import json
import logging

import paho.mqtt.client as mqtt

import config
import service

log = logging.getLogger("splrt.mqtt")


def _parse(payload, key):
    text = payload.decode("utf-8", errors="replace").strip()
    try:
        data = json.loads(text)
    except ValueError:
        return text
    if isinstance(data, dict):
        return data.get(key)
    return data


def handle_message(topic, payload):
    """Route one MQTT message. Kept separate from paho so it can be unit-tested."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != config.MQTT_TOPIC_ROOT:
        return None
    _, kind, device_id, channel = parts
    if kind == "lrv" and channel == "odometer":
        return service.ingest_odometer(device_id, int(float(_parse(payload, "pulses"))))
    if kind == "station" and channel == "rfid":
        return service.ingest_rfid(device_id, str(_parse(payload, "tag")))
    if channel == "status" and kind in ("lrv", "station"):
        state = str(_parse(payload, "status")).lower()
        service.set_device_status(device_id, state == "online", kind)
        return {"device_id": device_id, "online": state == "online"}
    return None


class MqttBridge:
    def __init__(self, host=config.MQTT_HOST, port=config.MQTT_PORT):
        self.host, self.port = host, port
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="splrt-backend")
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(min_delay=1, max_delay=10)

    def start(self):
        log.info("Connecting to MQTT broker %s:%s", self.host, self.port)
        self.client.connect_async(self.host, self.port, keepalive=30)
        self.client.loop_start()   # background thread, auto-reconnects

    def stop(self):
        self.client.loop_stop()
        self.client.disconnect()

    def _on_connect(self, client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.error("MQTT connect failed: %s", reason_code)
            return
        self.connected = True
        root = config.MQTT_TOPIC_ROOT
        client.subscribe([(f"{root}/lrv/+/odometer", 1), (f"{root}/station/+/rfid", 1),
                          (f"{root}/+/+/status", 1)])
        log.info("MQTT connected, subscribed to %s/#", root)

    def _on_disconnect(self, client, userdata, flags, reason_code, properties):
        self.connected = False
        log.warning("MQTT disconnected (%s) - retrying", reason_code)

    def _on_message(self, client, userdata, msg):
        try:
            handle_message(msg.topic, msg.payload)
        except Exception as exc:
            log.warning("Bad message on %s: %r (%s)", msg.topic, msg.payload[:100], exc)
