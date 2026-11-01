#include "MQTTConfiguration.h"
#include "AppConfig.h"   // MQTT_BROKER_IP / MQTT_BROKER_PORT from secrets.h
#include <WiFi.h>
#include <PubSubClient.h>

// ---------- broker address: edit include/secrets.h ----------
const char* MQTT_HOST = MQTT_BROKER_IP;     // set in include/secrets.h
const uint16_t MQTT_PORT = MQTT_BROKER_PORT; // set in include/secrets.h
const char* MQTT_CLIENT_ID = "esp32s3-nfc-01";
// --------------------------------

static WiFiClient wifiClient;
static PubSubClient mqtt(wifiClient);

void mqttInit() {
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
  mqtt.setSocketTimeout(2);   // FIX 2: don't freeze the loop for 15 s if the broker is unreachable
  mqtt.setKeepAlive(30);
}

// non-blocking: tries once per second, never freezes the loop
void mqttEnsureConnected() {
  if (mqtt.connected()) return;
  if (WiFi.status() != WL_CONNECTED) return;   // FIX 2: no Wi-Fi, no point trying
  static uint32_t lastTry = 0;
  if (millis() - lastTry < 2000) return;   // FIX 2: retry every 2 s
  lastTry = millis();

  if (mqtt.connect(MQTT_CLIENT_ID)) {
    Serial.println("MQTT connected");
  } else {
    Serial.printf("MQTT connect failed, rc=%d\n", mqtt.state());
  }
}

// must be called every loop() — keeps the connection alive
void mqttLoop() {
  mqtt.loop();
}

// publish helper: topic + small C-string payload
bool mqttPublish(const char* topic, const char* payload) {
  if (!mqtt.connected()) return false;
  return mqtt.publish(topic, payload);
}