# Railtech_fixed — what changed and why

This is a copy of the `Railtech` firmware with small reliability fixes.
**Nothing else changed:** pins, tag IDs, MQTT topics, Wi-Fi/broker settings and the encoder code are the same.
The original `Railtech` folder is untouched — to go back, open it in PlatformIO and click Upload.

Only 3 files changed: `src/main.cpp`, `src/PN532.cpp`, `src/MQTT.cpp`. Every change is marked `// FIX n` in the code.

| # | Problem | Fix |
|---|---------|-----|
| 1 | On a power bank no PC reads the USB serial port, and `Serial.print` can stall the loop while waiting for one. | `Serial.setTxTimeoutMs(0)` in `setup()` — prints are dropped instead of waited on when no PC is attached. |
| 2 | MQTT was only tried once at boot and `mqtt.loop()` was never called, so the broker dropped the board after ~20 s and it never reconnected. | `mqttEnsureConnected()` + `mqttLoop()` at the top of `loop()`. Retry every 2 s, 2 s socket timeout so a missing broker doesn't freeze the loop, skip when Wi-Fi is down. |
| 3 | The PN532 retried forever by default; when the ESP32 stopped waiting, the next command collided and the chip froze (up to 30 s until the health check). | `setPassiveActivationRetries(0x02)` after `SAMConfig()` (also after recovery). Health check every 5 s instead of 30 s. |
| 4 | `cardSeen` was reset by every "no card" poll, including the cooldown, so a train parked on a tag re-sent it every 4.5 s. | Remember the last tag. It is sent once on arrival and again only after it has been out of range for 2 s. |
| 5 | The reader listened only ~50% of the time and ignored everything for 4.5 s after a read, so tags on a moving train — and the second tag of the 0 m / 100 m pair — were missed. | Poll almost continuously (10 ms gap, read returns as soon as the PN532 answers), 200 ms after a read. |
| 6 | On a cold power-up (e.g. plugging in the power bank) the ESP32 could start before the PN532 had finished booting. Setup failed once and was never retried, so RFID stayed dead until RST was pressed (the encoder still worked). | PN532 setup is retried for up to 3 s at boot, then every 1 s in the background until it answers; RFID polling waits until the reader is ready. |
| 7 | While the wheel turned, the encoder ran first in `loop()` and could send an MQTT message for every 5° of rotation, so the RFID reader was hardly checked — tags were only read when the wheel stood still (confirmed in the backend log). | RFID is checked first, every loop (priority). The encoders are read and sent at most every 50 ms (20×/s); the backend adds up the angle changes, so mileage stays accurate. |

Build-checked for `4d_systems_esp32s3_gen4_r8n16` (compiles with no errors). Fixes 1–7 were run on the hardware; the repo-preparation changes below are build-checked only.

## Repo preparation (hardware/railtech)
- Wi-Fi SSID/password and MQTT broker IP/port moved out of `main.cpp` / `MQTT.cpp` into `include/secrets.h` (git-ignored); template in `include/secrets.example.h`. The build stops with a clear message if `secrets.h` is missing.
- `USE_ENCODER2` build option (default 0) in `include/AppConfig.h`: the car has only one AS5600, and an unconnected second bus reads back raw 4095 — one junk angle on `splrt/lrv/LRV02/odometer` at boot, a failed I2C transaction every read, and random angles if the lines float.
- `#include "MqttConfiguration.h"` changed to `"MQTTConfiguration.h"` (the real file name), so it also builds on case-sensitive Linux/macOS.
- `platformio.ini`: `lib_deps` lists Adafruit PN532, Adafruit BusIO and PubSubClient with versions; `monitor_speed = 115200`.

## Test checklist
1. Start Mosquitto + `python main.py`, then power the board from the **power bank**.
2. Mosquitto window shows `New client connected ... esp32s3-nfc-01`.
3. Leave it still for 1 minute — it stays connected (no "exceeded timeout").
4. Stop Mosquitto, start it again — the board reconnects by itself within a few seconds.
5. Pass each tag at normal speed — one message per pass; park on a tag — no repeats.
6. Run through 0 m then 100 m — both are read and the wheel size updates.
7. Unplug the power bank, plug it back in, and don't press RST — tags still read.
8. Spin the wheel continuously and pass a tag — the tag is still read while the wheel turns.
