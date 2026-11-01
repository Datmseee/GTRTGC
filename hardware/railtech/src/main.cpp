#include <Arduino.h>
#include "WiFiConfiguration.h"
#include "HttpConfiguration.h"
#include "PN532Configuration.h"
#include <Adafruit_PN532.h>
#include "EncoderConfiguration.h"
#include "MQTTConfiguration.h"

#include "AppConfig.h"         // USE_ENCODER2 + Wi-Fi/MQTT settings from secrets.h

const char* SSID = WIFI_SSID;    // set in include/secrets.h
const char* PASS = WIFI_PASS;
uint8_t uid[7]; // Buffer to store the returned UID
uint8_t uidLength; // Length of the UID (4 or 7 bytes depending on card type)
uint8_t which = 0;
float previousEncoderValue1 = 0.0f;
float previousEncoderValue2 = 0.0f;
uint8_t rotation1 = 0;
uint8_t rotation2 = 0;
uint8_t stationCard1[] = { 0x84, 0xA7, 0xFC, 0xD7 };
uint8_t stationCard2[] = { 0x03, 0x96, 0xF3, 0x13 };
uint8_t stationCard3[] = { 0x5F, 0x48, 0xF0, 0xD7 };
uint8_t card0m[] = { 0x6D, 0x85, 0xEF, 0xD7 };
uint8_t card100m[] = { 0x8E, 0xC2, 0x01, 0xD8 };
uint8_t cardDirection[] = { 0xE8, 0x4A, 0x00, 0xD8 };

void setup() {
  Serial.begin(115200);
#if ARDUINO_USB_CDC_ON_BOOT && ARDUINO_USB_MODE
  // FIX 1: on a power bank no PC is reading the USB serial port.
  // Without this, every Serial.print can stall the loop while it waits for a PC.
  Serial.setTxTimeoutMs(0);
#endif
  as5600Init();
#if USE_ENCODER2
  as5600Init2();
#endif
  nfcInit();
  wifiConnect(SSID, PASS);
  mqttInit(); 
  if (wifiIsConnected()) {      // don't bother MQTT with no WiFi
    Serial.printf("WiFi connected\n");
    mqttEnsureConnected();
    mqttLoop();
  }
}

void loop() {
  wifiEnsureConnected();
  mqttEnsureConnected();   // FIX 2: reconnect to the broker if it was not ready or the link dropped
  mqttLoop();              // FIX 2: keep the MQTT connection alive (stops the ~20 s timeout)

  // FIX 7: RFID has priority. It is checked first, every loop, so a tag is never
  // missed while the encoder is busy. (Before, the encoder ran first and could send
  // a message for every 5 deg of rotation, which starved the RFID reader.)
  // FIX 4: remember the last tag instead of "cardSeen".
  // A tag is sent once when it arrives. While it stays in range (train parked on it)
  // it is not sent again. It can be sent again after it has been out of range for
  // TAG_REPEAT_MS.
  const uint32_t TAG_REPEAT_MS = 2000;
  static char lastUid[16] = "";
  static uint32_t lastSeenMs = 0;

  which = nfcPollAll(uid, &uidLength);

  if (which) {
    // Safety: uid[] only has space for seven bytes.
    if (uidLength > 7) {
      uidLength = 7;
    }

    // Convert UID bytes into text, e.g. 84 A7 FC D7 -> "84A7FCD7"
    char uidStr[16];
    int pos = 0;
    for (uint8_t i = 0; i < uidLength; i++) {
      pos += snprintf(uidStr + pos, sizeof(uidStr) - pos, "%02X", uid[i]);
    }

    bool sameTagStillThere = (strcmp(uidStr, lastUid) == 0) &&
                             (millis() - lastSeenMs < TAG_REPEAT_MS);
    lastSeenMs = millis();
    strncpy(lastUid, uidStr, sizeof(lastUid) - 1);

    if (!sameTagStillThere) {
      Serial.printf("Card on reader %d: %s\n", which, uidStr);

      // ---------------- RFID card actions ----------------
      if (uidMatches(uid, uidLength, stationCard1, sizeof(stationCard1))) {
        Serial.println("Station 1 reached!");
        mqttPublish("splrt/station/ST1/rfid", uidStr);
      }
      else if (uidMatches(uid, uidLength, stationCard2, sizeof(stationCard2))) {
        Serial.println("Station 2 reached!");
        mqttPublish("splrt/station/ST2/rfid", uidStr);
      }
      else if (uidMatches(uid, uidLength, stationCard3, sizeof(stationCard3))) {
        Serial.println("Depot reached!");
        mqttPublish("splrt/station/DEPOT/rfid", uidStr);
      }
      else if (uidMatches(uid, uidLength, card0m, sizeof(card0m))) {
        Serial.println("0m reached!");
        mqttPublish("splrt/station/ST0m/rfid", uidStr);
      }
      else if (uidMatches(uid, uidLength, card100m, sizeof(card100m))) {
        Serial.println("100m reached!");
        mqttPublish("splrt/station/ST100m/rfid", uidStr);
      }
      else if (uidMatches(uid, uidLength, cardDirection, sizeof(cardDirection))) {
        Serial.println("Direction reached!");
        mqttPublish("splrt/station/Dir/rfid", "DEPOT");
      }
      else {
        // uid is an array, so don't use %02X directly on uid.
        // uidStr is the complete printable RFID value.
        Serial.printf("Ur stinky, UID: %s\n", uidStr);
      }
    }
  }

  // FIX 7: read/send the encoders at most every ENCODER_PERIOD_MS (20 times a second).
  // The backend adds up the angle changes, so mileage stays accurate.
  const uint32_t ENCODER_PERIOD_MS = 50;
  static uint32_t lastEncoderMs = 0;
  if (millis() - lastEncoderMs >= ENCODER_PERIOD_MS) {
    lastEncoderMs = millis();
    //Encoder 1 update only if changes >= 5 degrees
    float deg1 = as5600ReadAngleDeg();
    if (fabs(deg1 - previousEncoderValue1) >= 5.0f) {
      Serial.printf("Angle1: %.2f deg | raw %u\n", deg1, as5600ReadRaw());

      char buf[16];
      snprintf(buf, sizeof(buf), "%.2f", deg1);
      mqttPublish("splrt/lrv/LRV01/odometer", buf);

      previousEncoderValue1 = deg1;
      //delay(20);
    }

#if USE_ENCODER2
    //Encoder 2 update only if changes >= 5 degrees
    float deg2 = as5600ReadAngleDeg2();
    if (fabs(deg2 - previousEncoderValue2) >= 5.0f) {
      Serial.printf("Angle2: %.2f deg | raw %u\n", deg2, as5600ReadRaw2());

      char buf[16];
      snprintf(buf, sizeof(buf), "%.2f", deg2);
      mqttPublish("splrt/lrv/LRV02/odometer", buf);

      previousEncoderValue2 = deg2;
      //delay(20);
    }
#endif
  }
  /*
  static bool cardSeen[4] = { false, false, false, false };  // index 1-3 for NFC
  which = nfcPollAll(uid, &uidLength);

  if (which && !cardSeen[which]) {
    cardSeen[which] = true;

    if (uidLength > 7) uidLength = 7;
    Serial.printf("Card on reader %d\n", which);

    char uidStr[16];
    int pos = 0;
    for (uint8_t i = 0; i < uidLength; i++) {
      pos += snprintf(uidStr + pos, sizeof(uidStr) - pos, "%02X", uid[i]);
      Serial.printf("%02X ", uid[i]);
    } // uidStr now contains the UID as a hex string


    if (uidMatches(uid, uidLength, stationCard1, sizeof(stationCard1))) {
      Serial.println("Station 1 reached!");
      mqttPublish("splrt/station/ST1/rfid", uidStr);
      //Serial.println(uidStr);
    } 
    else if (uidMatches(uid, uidLength, stationCard2, sizeof(stationCard2))) {
      Serial.println("Station 2 reached!");
      mqttPublish("splrt/station/ST2/rfid", uidStr);    
      //Serial.println(uidStr);
    } 
    else if (uidMatches(uid, uidLength, stationCard3, sizeof(stationCard3))) {
      Serial.println("Depot reached!");
      mqttPublish("splrt/station/DEPOT/rfid", uidStr);   
      //Serial.println(uidStr);
    } 
    else if (uidMatches(uid, uidLength, card0m, sizeof(card0m))) {
      Serial.println("0m reached!");
      mqttPublish("splrt/station/ST0m/rfid", uidStr);  
      //Serial.println(uidStr);
    } 
    else if (uidMatches(uid, uidLength, card100m, sizeof(card100m))) {
      Serial.println("100m reached!");
      mqttPublish("splrt/station/ST100m/rfid", uidStr); 
      //Serial.println(uidStr);
    } 
    else if (uidMatches(uid, uidLength, cardDirection, sizeof(cardDirection))) {
      Serial.println("Direction reached!");
      mqttPublish("splrt/station/Dir/rfid", "DEPOT"); 
      //Serial.println(uidStr);
    }
    else {
      Serial.printf("Ur stinky, UID:%02X\n", uid);
    }
  }

  if (!which) {
    cardSeen[1] = cardSeen[2] = cardSeen[3] = false;
  }
}*/
}
