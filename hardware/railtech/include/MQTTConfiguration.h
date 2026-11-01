#pragma once
#include <Arduino.h>
void mqttInit();
void mqttEnsureConnected();
void mqttLoop();
bool mqttPublish(const char* topic, const char* payload);