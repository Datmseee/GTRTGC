#pragma once
#include <Arduino.h>

#define AS5600_I2C_ADDR   0x36

// bus 0 (existing)
#define AS5600_SDA_PIN    8      // whatever yours already are
#define AS5600_SCL_PIN    9
// bus 1 (NEW — pick 2 free GPIOs on your board)
#define AS5600_SDA2_PIN   42     // example — check your 4D board's free pins!
#define AS5600_SCL2_PIN   41

bool as5600Init();               // encoder 1
bool as5600Init2();              // NEW: encoder 2
uint16_t as5600ReadRaw();
uint16_t as5600ReadRaw2();       // NEW
float as5600ReadAngleDeg();
float as5600ReadAngleDeg2();     // NEW