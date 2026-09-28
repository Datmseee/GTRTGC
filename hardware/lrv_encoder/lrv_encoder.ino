// SPLRT demo - LRV (train) firmware: AS5600 magnetic angle sensor -> MQTT
// Board: ESP32. Libraries: PubSubClient (Nick O'Leary), ArduinoJson (Benoit Blanchon), Wire (built in).
//
// The AS5600 gives an ABSOLUTE angle (raw 0..4095 = 0..360 deg), not pulses.
// This sketch turns it into a running total of counts travelled (4096 counts = 1 wheel turn)
// and publishes that total every second to  splrt/lrv/<LRV_ID>/odometer  as {"pulses": N}.
// The server converts counts -> km (pulses_per_rev = 4096 in backend/config.py).
//
// Wiring (ESP32): AS5600 VCC->3V3, GND->GND, SDA->GPIO21, SCL->GPIO22, DIR->GND.
// Magnet: diametrically magnetised disc on the wheel axle, centred over the chip, ~0.5-3 mm gap.

#include <WiFi.h>
#include <Wire.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ---------- change these ----------
const char* WIFI_SSID    = "YourHotspot";
const char* WIFI_PASS    = "YourPassword";
const char* MQTT_HOST    = "192.168.43.10";   // IP of the laptop running Mosquitto
const uint16_t MQTT_PORT = 1883;
const char* LRV_ID       = "LRV01";           // LRV01 or LRV02
const int DEADBAND       = 8;                 // counts (~0.7 deg): ignore sensor jitter when stopped
// ----------------------------------

const uint8_t AS5600_ADDR = 0x36;
const uint8_t REG_STATUS  = 0x0B;             // bit5 MD = magnet detected, bit4 ML = too weak, bit3 MH = too strong
const uint8_t REG_RAW_ANG = 0x0C;             // 12-bit raw angle (0x0C high, 0x0D low)

uint32_t totalCounts = 0;   // distance travelled in counts (always increases, either direction)
int refRaw = -1;            // last angle that was counted
bool magnetOk = false;

int readReg16(uint8_t reg) {
  Wire.beginTransmission(AS5600_ADDR);
  Wire.write(reg);
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
  return (st & 0x20) && !(st & 0x18);          // detected, not too weak, not too strong
}

// Call often (every few ms). The wheel must turn less than half a revolution between calls.
void updateOdometer() {
  magnetOk = readMagnetOk();
  if (!magnetOk) return;                       // "magnet PROBLEM": readings are unreliable, skip them
  int raw = readReg16(REG_RAW_ANG);
  if (raw < 0) return;
  if (refRaw < 0) { refRaw = raw; return; }    // first good reading = starting point

  int diff = raw - refRaw;                     // shortest way round the 0/4095 wrap
  if (diff > 2048) diff -= 4096;
  if (diff < -2048) diff += 4096;

  if (abs(diff) >= DEADBAND) {                 // real movement, not jitter
    totalCounts += abs(diff);                  // mileage counts both directions
    refRaw = raw;
  }
}

WiFiClient net;
PubSubClient mqtt(net);
char topicOdo[64], topicStatus[64];

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASS);
  while (WiFi.status() != WL_CONNECTED) { delay(300); updateOdometer(); Serial.print("."); }
  Serial.printf("\nWiFi OK, IP %s\n", WiFi.localIP().toString().c_str());
}

bool connectMqtt() {
  // Last Will: broker publishes "offline" for us if we drop off
  if (mqtt.connect(LRV_ID, topicStatus, 1, true, "offline")) {
    mqtt.publish(topicStatus, "online", true);
    Serial.println("MQTT OK");
    return true;
  }
  Serial.printf("MQTT failed (%d), retrying\n", mqtt.state());
  return false;
}

void setup() {
  Serial.begin(115200);
  Wire.begin(21, 22);
  Wire.setClock(400000);
  snprintf(topicOdo, sizeof(topicOdo), "splrt/lrv/%s/odometer", LRV_ID);
  snprintf(topicStatus, sizeof(topicStatus), "splrt/lrv/%s/status", LRV_ID);
  connectWifi();
  mqtt.setServer(MQTT_HOST, MQTT_PORT);
}

uint32_t lastSend = 0, lastMqttTry = 0;

void loop() {
  updateOdometer();                            // keep sampling even while (re)connecting

  if (WiFi.status() != WL_CONNECTED) connectWifi();
  if (!mqtt.connected() && millis() - lastMqttTry > 1000) { lastMqttTry = millis(); connectMqtt(); }
  mqtt.loop();

  if (millis() - lastSend >= 1000) {
    lastSend = millis();
    StaticJsonDocument<96> doc;
    doc["pulses"] = totalCounts;
    doc["magnet_ok"] = magnetOk;               // extra field, ignored by the server for now
    char buf[96];
    serializeJson(doc, buf);
    if (mqtt.connected()) mqtt.publish(topicOdo, buf);
    Serial.printf("sent %s  (%.2f turns)\n", buf, totalCounts / 4096.0);
  }
  delay(2);
}
