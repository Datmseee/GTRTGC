// SPLRT demo - ONE board per train: AS5600 wheel encoder + RC522 RFID reader on an ESP32-S3
// Libraries: PubSubClient (Nick O'Leary), ArduinoJson v7 (Benoit Blanchon), MFRC522 (miguelbalboa).
// PlatformIO: rename to src/main.cpp and add  #include <Arduino.h>  at the top.
//
// The train carries the reader; an RFID tag is stuck at each station (ST1, ST2, DEPOT).
// Publishes:
//   splrt/lrv/<LRV_ID>/odometer  {"pulses": N}                   every 1 s (running total, 4096 per wheel turn)
//   splrt/lrv/<LRV_ID>/rfid      {"tag": "5A000001", "pulses": N}  when the reader passes a station tag
//   splrt/lrv/<LRV_ID>/status    online / offline (Last Will)
// The station-tag UIDs are entered in the dashboard (Demo -> Settings -> Station tags), not here.
//
// Wiring (ESP32-S3 - change the pin numbers below if yours differ):
//   AS5600:  VCC 3V3, GND, SDA -> GPIO 8,  SCL -> GPIO 9,  DIR -> GND
//   RC522:   3.3V, GND, SDA(SS) -> GPIO 10, MOSI -> GPIO 11, SCK -> GPIO 12, MISO -> GPIO 13, RST -> GPIO 14
//   (Do not use GPIO 19/20 - USB - or 22-25 / 26-32 on most S3 boards.)

#include <WiFi.h>
#include <Wire.h>
#include <SPI.h>
#include <MFRC522.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---------- change these ----------
const char* WIFI_SSID    = "YourHotspot";
const char* WIFI_PASS    = "YourPassword";
const char* MQTT_HOST    = "172.20.10.4";     // IP of the laptop running Mosquitto (ipconfig)
const uint16_t MQTT_PORT = 1883;
const char* LRV_ID       = "LRV01";           // LRV01 on one train, LRV02 on the other

const int PIN_SDA  = 8,  PIN_SCL  = 9;        // AS5600 (I2C)
const int PIN_SS   = 10, PIN_MOSI = 11, PIN_SCK = 12, PIN_MISO = 13, PIN_RST = 14;   // RC522 (SPI)

const int DEADBAND        = 8;                // counts (~0.7 deg): ignore encoder jitter when stopped
const uint32_t REPEAT_MS  = 3000;             // ignore the same station tag again within 3 s
// ----------------------------------

// ---------- AS5600 wheel encoder ----------
const uint8_t AS5600_ADDR = 0x36;
const uint8_t REG_STATUS  = 0x0B;             // bit5 MD magnet detected, bit4 ML too weak, bit3 MH too strong
const uint8_t REG_RAW_ANG = 0x0C;             // 12-bit raw angle

uint32_t totalCounts = 0;                     // distance travelled in counts, both directions
int refRaw = -1;
bool magnetOk = false;

int readRawAngle() {
  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(REG_RAW_ANG);
  if (Wire.endTransmission(false) != 0) return -1;
  if (Wire.requestFrom(AS5600_ADDR, (uint8_t)2) != 2) return -1;
  return ((Wire.read() << 8) | Wire.read()) & 0x0FFF;
}

bool readMagnetOk() {
  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(REG_STATUS);
  if (Wire.endTransmission(false) != 0) return false;
  if (Wire.requestFrom(AS5600_ADDR, (uint8_t)1) != 1) return false;
  uint8_t st = Wire.read();
  return (st & 0x20) && !(st & 0x18);
}

// Call every few ms: the wheel must turn less than half a revolution between calls.
void updateOdometer() {
  magnetOk = readMagnetOk();
  if (!magnetOk) return;                      // "magnet PROBLEM" -> skip unreliable readings
  int raw = readRawAngle();
  if (raw < 0) return;
  if (refRaw < 0) { refRaw = raw; return; }
  int diff = raw - refRaw;                    // shortest way round the 4095 -> 0 wrap
  if (diff > 2048) diff -= 4096;
  if (diff < -2048) diff += 4096;
  if (abs(diff) >= DEADBAND) { totalCounts += abs(diff); refRaw = raw; }
}

// ---------- RC522 reader ----------
MFRC522 rfid(PIN_SS, PIN_RST);
String lastTag;
uint32_t lastTagMs = 0;

String uidHex(const MFRC522::Uid& uid) {
  String s;
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) s += "0";
    s += String(uid.uidByte[i], HEX);
  }
  s.toUpperCase();
  return s;                                   // e.g. "04A3B2C1"
}

// ---------- WiFi / MQTT ----------
WiFiClient net;
PubSubClient mqtt(net);
char topicOdo[64], topicRfid[64], topicStatus[64];

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  Serial.print("WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(200); updateOdometer(); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
}

bool connectMqtt() {
  if (mqtt.connect(LRV_ID, topicStatus, 1, true, "offline")) {
    mqtt.publish(topicStatus, "online", true);
    Serial.println("MQTT OK");
    return true;
  }
  Serial.printf("MQTT failed (%d), retrying\n", mqtt.state());
  return false;
}

void publishOdometer() {
  JsonDocument doc;
  doc["pulses"] = totalCounts;
  doc["magnet_ok"] = magnetOk;
  char buf[96];
  serializeJson(doc, buf);
  if (mqtt.connected()) mqtt.publish(topicOdo, buf);
  Serial.printf("odometer %s  (%.2f turns)\n", buf, totalCounts / 4096.0);
}

void setup() {
  Serial.begin(115200);
  delay(300);
  Wire.begin(PIN_SDA, PIN_SCL);
  Wire.setClock(400000);
  SPI.begin(PIN_SCK, PIN_MISO, PIN_MOSI, PIN_SS);
  rfid.PCD_Init();
  Serial.print("RC522 ");
  rfid.PCD_DumpVersionToSerial();             // "Firmware Version: 0x92" = OK, 0x00/0xFF = wiring problem

  snprintf(topicOdo, sizeof(topicOdo), "splrt/lrv/%s/odometer", LRV_ID);
  snprintf(topicRfid, sizeof(topicRfid), "splrt/lrv/%s/rfid", LRV_ID);
  snprintf(topicStatus, sizeof(topicStatus), "splrt/lrv/%s/status", LRV_ID);
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

uint32_t lastSend = 0, lastMqttTry = 0;

void loop() {
  updateOdometer();                           // keep counting even while (re)connecting

  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected() && millis() - lastMqttTry > 1000) { lastMqttTry = millis(); connectMqtt(); }
  mqtt.loop();

  // Station tag under the train? Send it together with the wheel count at this exact moment.
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    String tag = uidHex(rfid.uid);
    rfid.PICC_HaltA();
    if (!(tag == lastTag && millis() - lastTagMs < REPEAT_MS)) {
      lastTag = tag; lastTagMs = millis();
      JsonDocument doc;
      doc["tag"] = tag;
      doc["pulses"] = totalCounts;
      char buf[96];
      serializeJson(doc, buf);
      if (mqtt.connected()) mqtt.publish(topicRfid, buf);
      Serial.printf("station tag %s\n", buf);
    }
  }

  if (millis() - lastSend >= 1000) {
    lastSend = millis();
    publishOdometer();
  }
  delay(2);
}
