#include "WiFiConfiguration.h"
#include <WiFi.h>


static const char* _ssid = nullptr;
static const char* _pass = nullptr;
static const uint32_t CONNECT_TIMEOUT_MS = 10000;  // 10s per attempt


bool wifiConnect(const char* ssid, const char* password, uint8_t maxRetries) {
  _ssid = ssid;
  _pass = password;
  WiFi.mode(WIFI_STA);

  for (uint8_t attempt = 1; attempt <= maxRetries; attempt++) {
    Serial.printf("WiFi attempt %d/%d: %s\n", attempt, maxRetries, ssid);
    WiFi.begin(ssid, password);

    uint32_t start = millis();
    while (WiFi.status() != WL_CONNECTED) {
      if (millis() - start > CONNECT_TIMEOUT_MS) {
        Serial.println("  timed out, retrying...");
        WiFi.disconnect();
        break;  // out of while, next attempt
      }
      delay(250);
      Serial.print(".");
    }

    if (WiFi.status() == WL_CONNECTED) {
      Serial.printf("\nConnected! IP: %s\n", WiFi.localIP().toString().c_str());
      return true;
    }
  }

  Serial.println("WiFi failed after all retries.");
  return false;
}


bool wifiIsConnected() {
  return WiFi.status() == WL_CONNECTED;
}


void wifiEnsureConnected() {
  if (_ssid == nullptr) return;   // never connected before — nothing to retry
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi dropped, reconnecting...");
    wifiConnect(_ssid, _pass);
  }
}