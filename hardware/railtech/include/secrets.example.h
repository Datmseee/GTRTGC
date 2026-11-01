#pragma once
// ------------------------------------------------------------------
// TEMPLATE - copy this file to include/secrets.h and fill it in.
// Wi-Fi and MQTT broker settings for the Railtech ESP32-S3 board.
// secrets.h is git-ignored, so real passwords never go to GitHub.
// ------------------------------------------------------------------

// Wi-Fi the ESP32 joins: the demo phone hotspot (must be 2.4 GHz;
// on an iPhone turn on "Maximise Compatibility").
#define WIFI_SSID        "YOUR_HOTSPOT_NAME"
#define WIFI_PASS        "YOUR_HOTSPOT_PASSWORD"

// Laptop running Mosquitto (the MQTT broker).
//  - Phone hotspot: run `ipconfig` on the laptop -> Wi-Fi IPv4 address (e.g. 172.20.10.x).
//  - Windows Mobile Hotspot on the laptop itself: 192.168.137.1
// The address can change each time the laptop joins the hotspot.
#define MQTT_BROKER_IP   "172.20.10.4"
#define MQTT_BROKER_PORT 1883     // must match `listener` in backend/mosquitto.conf
