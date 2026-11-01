#pragma once
#include <Arduino.h>

void nfcInit();
uint8_t nfcPollAll(uint8_t* uid, uint8_t* uidLength);
bool uidMatches(const uint8_t* a, uint8_t aLen, const uint8_t* b, uint8_t bLen);