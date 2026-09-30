"""MQTT subscriber: turns hardware messages into service calls.

Topics (root = "splrt" by default):
  splrt/lrv/<device_id>/odometer     {"pulses": 15230}      running count (our firmware / simulator)
                                     292.41                 plain number = wheel ANGLE in degrees
                                                            (teammate's firmware; unwrapped on the server)
  splrt/lrv/<device_id>/rfid         {"tag": "5A000001", "pulses": 15230}   reader on the train, tag at station
  splrt/station/<name>/rfid          84A7FCD7               teammate's firmware: <name> = ST1 | ST2 | DEPOT |
                                                            Dir (depot branch) | ST0m | ST100m (calibration);
                                                            credited to the 'rfid_train_device' train
                                     {"tag": "<train tag>"} old setup: reader at the station, tag on the train
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
        return data if key is None else data.get(key)
    return data


def _tag(payload, data):
    """A tag from a JSON object, else the raw text (so a UID like '12E45678' isn't read as a number)."""
    if isinstance(data, dict):
        return str(data.get("tag", ""))
    return payload.decode("utf-8", errors="replace").strip().strip('"')


def handle_message(topic, payload):
    """Route one MQTT message. Kept separate from paho so it can be unit-tested."""
    parts = topic.split("/")
    if len(parts) != 4 or parts[0] != config.MQTT_TOPIC_ROOT:
        return None
    _, kind, device_id, channel = parts
    if kind == "lrv" and channel == "odometer":
        data = _parse(payload, None)
        if isinstance(data, dict):                  # {"pulses": N}: running count
            return service.ingest_odometer(device_id, int(float(data.get("pulses"))))
        return service.ingest_angle(device_id, float(data))   # plain number: angle in degrees
    if kind == "lrv" and channel == "rfid":        # reader on the train, tag at the station
        data = _parse(payload, None)
        if isinstance(data, dict):
            return service.ingest_lrv_rfid(device_id, str(data.get("tag", "")), data.get("pulses"))
        return service.ingest_lrv_rfid(device_id, _tag(payload, data))
    if kind == "station" and channel == "rfid":
        return service.ingest_station_topic(device_id, _tag(payload, _parse(payload, None)))
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
        client.subscribe([(f"{root}/lrv/+/odometer", 1), (f"{root}/lrv/+/rfid", 1),
                          (f"{root}/station/+/rfid", 1),
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
