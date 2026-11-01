/*#include "PN532Configuration.h"
#include <SPI.h>
#include <Adafruit_PN532.h>
#define PN532_SCK   12
#define PN532_MISO  13
#define PN532_MOSI  11
#define PN532_SS1   10
#define PN532_SS2   14
#define PN532_SS3   21
#define PN532_IRQ1  5
#define PN532_IRQ2  6
#define PN532_IRQ3  7

static Adafruit_PN532 nfc1(PN532_SS1, &SPI);
static Adafruit_PN532 nfc2(PN532_SS2, &SPI);
static Adafruit_PN532 nfc3(PN532_SS3, &SPI);

static volatile bool irq1Pending = false;

void ARDUINO_ISR_ATTR onNfcIRQ1() {
  irq1Pending = true;
}

void nfcInit() {
  // deselect everyone BEFORE anything touches the bus
  pinMode(PN532_SS1, OUTPUT); digitalWrite(PN532_SS1, HIGH);
  pinMode(PN532_SS2, OUTPUT); digitalWrite(PN532_SS2, HIGH);
  pinMode(PN532_SS3, OUTPUT); digitalWrite(PN532_SS3, HIGH);
  pinMode(PN532_IRQ1, INPUT);
  pinMode(PN532_IRQ2, INPUT);
  pinMode(PN532_IRQ3, INPUT);
  SPI.begin(PN532_SCK, PN532_MISO, PN532_MOSI);  // no SS argument
  nfc1.begin();
  nfc2.begin();
  nfc3.begin();
  if (!nfc1.getFirmwareVersion()) Serial.println("PN532 #1 not found");
  if (!nfc2.getFirmwareVersion()) Serial.println("PN532 #2 not found");
  if (!nfc3.getFirmwareVersion()) Serial.println("PN532 #3 not found");
  nfc1.SAMConfig();
  nfc2.SAMConfig();
  nfc3.SAMConfig();
  nfc1.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  nfc2.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  nfc3.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  attachInterrupt(PN532_IRQ1, onNfcIRQ1, FALLING);
  irq1Pending = (digitalRead(PN532_IRQ1) == LOW);
}

uint8_t nfcPollAll(uint8_t* uid, uint8_t* uidLength) {
  Serial.printf("IRQs: %d %d %d\n",
    digitalRead(PN532_IRQ1), digitalRead(PN532_IRQ2), digitalRead(PN532_IRQ3));
  delay(500);
  if (digitalRead(PN532_IRQ1) == LOW &&
      nfc1.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, uidLength, 50)) return 1;
  if (digitalRead(PN532_IRQ2) == LOW &&
      nfc2.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, uidLength, 50)) return 2;
  if (digitalRead(PN532_IRQ3) == LOW &&
      nfc3.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, uidLength, 50)) return 3;
  return 0;
}

uint8_t nfcPollAll(uint8_t* uid, uint8_t* uidLength) {\
    Serial.printf("IRQs: %d %d %d\n",
    digitalRead(PN532_IRQ1), digitalRead(PN532_IRQ2), digitalRead(PN532_IRQ3));
    delay(100);
    if (irq1Pending || digitalRead(PN532_IRQ1) == LOW) {
    irq1Pending = false;

    // IRQ can also signal command acknowledgements.
    // Only read a response if the reader is still signalling ready.
    if (digitalRead(PN532_IRQ1) == LOW) {
      bool found = nfc1.readDetectedPassiveTargetID(uid, uidLength);

      nfc1.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);

      if (found) return 1;
    }
  }
  if (digitalRead(PN532_IRQ2) == LOW) {
    if (nfc2.readDetectedPassiveTargetID(uid, uidLength)) {
      nfc2.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
      return 2;
    }
    nfc2.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  }
  if (digitalRead(PN532_IRQ3) == LOW) {
    if (nfc3.readDetectedPassiveTargetID(uid, uidLength)) {
      nfc3.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
      return 3;
    }
    nfc3.startPassiveTargetIDDetection(PN532_MIFARE_ISO14443A);
  }
  return 0;
}

bool uidMatches(const uint8_t* a, uint8_t aLen, const uint8_t* b, uint8_t bLen) {
  if (aLen != bLen) return false;
  return memcmp(a, b, aLen) == 0;
}
*/
/*
#include "PN532Configuration.h"
#include <SPI.h>
#include <Adafruit_PN532.h>

#define PN532_SCK   12
#define PN532_MISO  13
#define PN532_MOSI  11
#define PN532_SS    10


static Adafruit_PN532 nfc(PN532_SS, &SPI);


void nfcInit() {
  // Keep the PN532 deselected at boot
  pinMode(PN532_SS, OUTPUT);
  digitalWrite(PN532_SS, HIGH);

  SPI.begin(PN532_SCK, PN532_MISO, PN532_MOSI);

  nfc.begin();

  if (!nfc.getFirmwareVersion()) Serial.println("PN532 not found");

  nfc.SAMConfig();
}

// ------------------------------------------------------------------
// Un-wedges the PN532 without resetting the whole ESP32.
// Re-runs begin() (re-sends the wakeup frame) + SAMConfig().
// Returns true if the chip answered after recovery.
// ------------------------------------------------------------------
static bool nfcRecover() {
  nfc.begin();
  uint32_t ver = nfc.getFirmwareVersion();

  if (!ver) {
    Serial.println("PN532 still dead after re-init");
    return false;
  }

  nfc.SAMConfig();
  Serial.printf("PN532 recovered (fw %d.%d)\n",
                (ver >> 16) & 0xFF, (ver >> 8) & 0xFF);
  return true;
}

// ------------------------------------------------------------------
// Watchdog — pings the chip every 30 s. If it doesn't respond,
// recover it in place.
// ------------------------------------------------------------------
#define NFC_CHECK_MS  30000

static void nfcWatchdog() {
  static uint32_t lastCheck = 0;
  if ((millis() - lastCheck) < NFC_CHECK_MS) return;
  lastCheck = millis();

  if (!nfc.getFirmwareVersion()) {
    Serial.println("PN532 wedged, recovering...");
    nfcRecover();
  }
}

uint8_t nfcPollAll(uint8_t* uid, uint8_t* uidLength) {
  //nfcWatchdog();

  // Rate limit: don't hammer the PN532 back-to-back.
  static uint32_t nextPoll = 0;
  if (millis() < nextPoll) return 0;      // chill, check again next loop

  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, uidLength, 20)) {
    nextPoll = millis() + 300;            // cooldown after a successful read
    return 1;
  }

  nextPoll = millis() + 200;              // idle: poll ~5×/s
  return 0;
}

bool uidMatches(const uint8_t* a, uint8_t aLen,
                const uint8_t* b, uint8_t bLen) {
  if (aLen != bLen) return false;
  return memcmp(a, b, aLen) == 0;
}*/
#include "PN532Configuration.h"
#include <SPI.h>
#include <Adafruit_PN532.h>


#define PN532_SCK   12
#define PN532_MISO  13
#define PN532_MOSI  11
#define PN532_SS    10


static Adafruit_PN532 nfc(PN532_SS, &SPI);


// FIX 6: on a cold power-up (power bank plugged in) the ESP32 can start talking
// to the PN532 before the PN532 has finished booting. Then init failed once and
// was never redone, so the reader stayed dead until RST was pressed.
// Now init is retried at boot, and redone automatically whenever it is missing.
static bool nfcReady = false;

static bool nfcSetup() {
  nfc.begin();
  uint32_t ver = nfc.getFirmwareVersion();
  if (!ver) return false;
  nfc.SAMConfig();
  // FIX 3: by default the PN532 keeps searching forever. When the ESP32 stops
  // waiting, the next command collides with that search and the chip freezes.
  // Tell it to give up by itself after a couple of tries.
  nfc.setPassiveActivationRetries(0x02);
  Serial.printf("PN532 ready (fw %d.%d)\n", (ver >> 16) & 0xFF, (ver >> 8) & 0xFF);
  return true;
}


void nfcInit() {
  // Keep the PN532 deselected at boot
  pinMode(PN532_SS, OUTPUT);
  digitalWrite(PN532_SS, HIGH);

  SPI.begin(PN532_SCK, PN532_MISO, PN532_MOSI);

  // FIX 6: give the PN532 up to ~3 s to wake up after power-on
  for (int i = 0; i < 15 && !nfcReady; i++) {
    nfcReady = nfcSetup();
    if (!nfcReady) delay(200);
  }
  if (!nfcReady) Serial.println("PN532 not found yet - will keep retrying");
}


// ------------------------------------------------------------------
// Self-healing health check. If the reader was never set up, retry
// every 1 s. Otherwise ping it every 5 s and redo the setup if it
// stopped answering.
// ------------------------------------------------------------------
#define NFC_CHECK_MS  5000    // FIX 3: check every 5 s (was 30 s)

static void nfcHealthCheck() {
  static uint32_t lastCheck = 0;
  uint32_t interval = nfcReady ? NFC_CHECK_MS : 1000;
  if ((millis() - lastCheck) < interval) return;
  lastCheck = millis();

  if (nfcReady && nfc.getFirmwareVersion()) return;   // chip alive - nothing to do

  Serial.println(nfcReady ? "PN532 wedged, recovering..." : "PN532 setup retry...");
  nfcReady = nfcSetup();
  if (!nfcReady) Serial.println("PN532 still not answering - retrying");
}


uint8_t nfcPollAll(uint8_t* uid, uint8_t* uidLength) {
  nfcHealthCheck();
  if (!nfcReady) return 0;               // FIX 6: reader not set up yet

  // Rate limit: don't hammer the PN532 back-to-back.
  static uint32_t nextPoll = 0;
  if (millis() < nextPoll) return 0;

  // 150 ms of active listening per poll...
  if (nfc.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, uidLength, 100)) {   // FIX 5: returns as soon as the PN532 answers
    nextPoll = millis() + 200;           // FIX 5: was 4500 ms, which missed the next tag (e.g. CAL 100 m)
    return 1;
  }

  nextPoll = millis() + 10;              // FIX 5: was 150 ms, so it was only listening half the time
  return 0;
}


bool uidMatches(const uint8_t* a, uint8_t aLen,
                const uint8_t* b, uint8_t bLen) {
  if (aLen != bLen) return false;
  return memcmp(a, b, aLen) == 0;
}