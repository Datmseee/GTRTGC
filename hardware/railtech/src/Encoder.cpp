#include "EncoderConfiguration.h"
#include <Wire.h>

#define REG_STATUS     0x0B
#define REG_RAW_ANGLE  0x0C

// ---- helpers now take a bus reference ----
static uint16_t readReg16(TwoWire& bus, uint8_t reg) {
    bus.beginTransmission(AS5600_I2C_ADDR);
    bus.write(reg);
    bus.endTransmission(false);
    bus.requestFrom((uint8_t)AS5600_I2C_ADDR, (uint8_t)2);
    return ((uint16_t)bus.read() << 8) | bus.read();
}

static uint8_t readReg8(TwoWire& bus, uint8_t reg) {
    bus.beginTransmission(AS5600_I2C_ADDR);
    bus.write(reg);
    bus.endTransmission(false);
    bus.requestFrom((uint8_t)AS5600_I2C_ADDR, (uint8_t)1);
    return bus.read();
}

// ---- encoder 1: Wire as before ----
bool as5600Init() {
    Wire.begin(AS5600_SDA_PIN, AS5600_SCL_PIN);
    Wire.setClock(400000);
    Wire.beginTransmission(AS5600_I2C_ADDR);
    return Wire.endTransmission() == 0;
}

uint16_t as5600ReadRaw() {
    return readReg16(Wire, REG_RAW_ANGLE) & 0x0FFF;
}

float as5600ReadAngleDeg() {
    return as5600ReadRaw() * (360.0f / 4096.0f);
}

// ---- encoder 2: Wire1 ----
bool as5600Init2() {
    Wire1.begin(AS5600_SDA2_PIN, AS5600_SCL2_PIN);
    Wire1.setClock(400000);
    Wire1.beginTransmission(AS5600_I2C_ADDR);
    return Wire1.endTransmission() == 0;
}

uint16_t as5600ReadRaw2() {
    return readReg16(Wire1, REG_RAW_ANGLE) & 0x0FFF;
}

float as5600ReadAngleDeg2() {
    return as5600ReadRaw2() * (360.0f / 4096.0f);
}