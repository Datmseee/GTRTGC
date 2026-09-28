// SPLRT demo - Station firmware: 3x MFRC522 RFID readers on one ESP32 -> MQTT
// Board: ESP32. Libraries: MFRC522 (GithubCommunity), PubSubClient, ArduinoJson.
//
// Each reader is one waypoint. When it reads a tag it publishes
//   splrt/station/<STATION_ID>/rfid   {"tag":"A1B2C3D4"}
// Readers share the SPI bus (SCK 18, MISO 19, MOSI 23) and have their own SS pin.
// Example sketch - adjust pins to your wiring.

#include <WiFi.h>
#include <SPI.h>
#include <MFRC522.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---------- change these ----------
const char* WIFI_SSID   = "YourHotspot";
const char* WIFI_PASS   = "YourPassword";
const char* MQTT_HOST   = "192.168.43.10";   // IP of the laptop running Mosquitto
const uint16_t MQTT_PORT = 1883;
const int RST_PIN = 22;                      // shared reset line
struct Reader { const char* stationId; int ssPin; };
Reader READERS[] = { {"ST1", 5}, {"ST2", 17}, {"DEPOT", 16} };
const uint32_t REPEAT_MS = 5000;             // ignore the same tag on the same reader for 5 s
// ----------------------------------

const int N = sizeof(READERS) / sizeof(READERS[0]);
MFRC522 rfid[3];
String lastTag[3];

uint32_t lastTagMs[3] = {0};

WiFiClient net;
PubSubClient mqtt(net);
const char* CLIENT_ID = "STATIONS";
const char* STATUS_TOPIC = "splrt/station/STATIONS/status";

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(300); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
}

void connectMqtt() {
  while (!mqtt.connected()) {
    if (mqtt.connect(CLIENT_ID, STATUS_TOPIC, 1, true, "offline")) {
      mqtt.publish(STATUS_TOPIC, "online", true);
      for (int i = 0; i < N; i++) {
        char t[64];
        snprintf(t, sizeof(t), "splrt/station/%s/status", READERS[i].stationId);
        mqtt.publish(t, "online", true);
      }
      Serial.println("MQTT OK");
    } else {
      Serial.printf("MQTT failed (%d), retrying\n", mqtt.state());
      delay(1000);
    }
  }
}

String uidHex(const MFRC522::Uid& uid) {
  String s;
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += "0";
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;   // e.g. "04A3B2C1"
}

void setup() {
  Serial.begin(115200);
  SPI.begin();
  for (int i = 0; i < N; i++) {
    rfid[i].PCD_Init(READERS[i].ssPin, RST_PIN);
    Serial.printf("Reader %s on SS %d ready\n", READERS[i].stationId, READERS[i].ssPin);
  }
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected()) connectMqtt();
  mqtt.loop();

  for (int i = 0; i < N; i++) {
    if (!rfid[i].PICC_IsNewCardPresent() || !rfid[i].PICC_ReadCardSerial()) continue;
    String tag = uidHex(rfid[i].uid);
    rfid[i].PICC_HaltA();

    if (tag == lastTag[i] && millis() - lastTagMs[i] < REPEAT_MS) continue;
    lastTag[i] = tag;
    lastTagMs[i] = millis();

    char topic[64], buf[64];
    snprintf(topic, sizeof(topic), "splrt/station/%s/rfid", READERS[i].stationId);
    StaticJsonDocument<64> doc;
    doc["tag"] = tag;
    serializeJson(doc, buf);
    mqtt.publish(topic, buf);
    Serial.printf("%s read %s\n", READERS[i].stationId, tag.c_str());
  }
}
