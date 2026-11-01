#pragma once
#include <Arduino.h>

bool wifiConnect(const char* ssid, const char* password, uint8_t maxRetries = 3);
bool wifiIsConnected();
void wifiEnsureConnected();