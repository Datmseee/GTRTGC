#pragma once
// ------------------------------------------------------------------
// Build options for the Railtech firmware.
// ------------------------------------------------------------------

// Second AS5600 encoder (train LRV02) on I2C bus 1 (GPIO 42 SDA / 41 SCL).
// The car currently has only ONE encoder (LRV01), so this is OFF by default.
// With no sensor connected, the second bus reads back 0xFF bytes = raw 4095 (359.9 deg):
// one junk angle gets published to splrt/lrv/LRV02/odometer at boot, every read costs a
// failed I2C transaction, and floating SDA/SCL lines can return random angles (fake mileage).
// Turn on with 1 here, or add  build_flags = -DUSE_ENCODER2=1  to platformio.ini.
#ifndef USE_ENCODER2
#define USE_ENCODER2 0
#endif

// Wi-Fi + MQTT broker settings live in include/secrets.h (git-ignored).
#if __has_include("secrets.h")
#include "secrets.h"
#else
#error "include/secrets.h is missing: copy include/secrets.example.h to include/secrets.h and fill in your Wi-Fi + MQTT broker IP"
#endif
