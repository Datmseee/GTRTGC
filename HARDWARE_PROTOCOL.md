# Hardware ↔ Software Protocol (v0.2)

How the train ESP32s talk to the SPLRT backend. Hardware and software teams: agree on this page before flashing firmware.

**Setup (v0.2): the reader rides on the train.** Each train has **one ESP32-S3** with the **AS5600** wheel encoder and an **RC522** RFID reader. A cheap RFID tag is stuck on the track at **ST1**, **ST2** and the **Depot**. No ESP32 is needed at the stations.

## 1. Network

```
 LRV01 (ESP32-S3: AS5600 + RC522) ─┐
                                    ├─ WiFi (iPhone hotspot, 2.4 GHz) ─► Laptop: Mosquitto :1883 ─► backend :8000 ─► dashboard
 LRV02 (ESP32-S3: AS5600 + RC522) ─┘
      ▲ passes tags stuck at ST1 / ST2 / DEPOT
```

- **Transport:** MQTT over WiFi. Broker = Mosquitto on the demo laptop, port **1883**, no password (demo only).
- **Everything on one hotspot.** The ESP32s connect to the **laptop's IP address** (`ipconfig` → Wireless LAN IPv4, e.g. `172.20.10.4`).
- **ESP32 libraries:** `PubSubClient`, `ArduinoJson` (v7), `MFRC522`.

## 2. IDs

| Thing | ID | Set where |
|---|---|---|
| Train board #1 | `LRV01` | `LRV_ID` in the firmware; linked to train `810D-001` in Demo settings |
| Train board #2 | `LRV02` | `LRV_ID` in the firmware; linked to train `810D-002` in Demo settings |
| Tag at Station 1 / Station 2 / Depot | its UID, e.g. `04A3B2C1` | **Dashboard → Demo → ⚙ Settings → Station tags** (not in the firmware) |

## 3. Topics and payloads (all from the train)

| Topic | Payload | When |
|---|---|---|
| `splrt/lrv/<LRV_ID>/odometer` | `{"pulses": 15230}` | every **1 s** |
| `splrt/lrv/<LRV_ID>/rfid` | `{"tag": "04A3B2C1", "pulses": 15230}` | when the reader passes a station tag |
| `splrt/lrv/<LRV_ID>/status` | `online` / `offline` | on connect, and as the MQTT **Last Will** (retained) |

Names are case-sensitive: `splrt` lowercase, `LRV01` uppercase.

## 4. Rules for the firmware

1. **`pulses` = running total of AS5600 counts since boot** (4096 = one wheel turn), not the change since the last message. The firmware "unwraps" the angle: add the change in raw angle each read, handle the 4095→0 wrap, ignore jitter under ~8 counts, skip reads while the sensor reports a magnet problem. A lost message then loses no distance, and a reboot (count back to 0) is detected by the server.
2. **Send `pulses` with every station-tag read.** The count at the exact moment of the read makes the distance between stations exact.
3. **No km maths on the ESP32.** Wheel size, counts per turn and demo scale are set in the dashboard (Demo settings), no reflash needed.
4. **No timestamps.** The server stamps each message on arrival.
5. **Tag UID:** uppercase hex, no spaces (e.g. `04A3B2C1`).
6. **Don't resend the same tag within ~3 s.** The server ignores repeats too.
7. **Use a Last Will** (`status`, `offline`, retained) so the dashboard shows when a train drops off.

**Firmware:** `hardware/lrv_unit/lrv_unit.ino`, the one sketch per train board (ESP32-S3). Set `WIFI_SSID`, `WIFI_PASS`, `MQTT_HOST`, `LRV_ID` and the pin numbers at the top.

Default ESP32-S3 pins in the sketch (change them to match the wiring):

| Part | Pin → ESP32-S3 GPIO |
|---|---|
| AS5600 | SDA → 8, SCL → 9, DIR → GND, VCC → 3V3 |
| RC522 | SDA/SS → 10, MOSI → 11, SCK → 12, MISO → 13, RST → 14, 3.3V, GND |

Don't use GPIO 19/20 (USB), and note that GPIO 22–25 don't exist on the S3.

## 5. Track tags

Six passive tags are stuck on the track. The firmware treats them all the same (it just sends the UID + wheel count); the backend knows what each one means:

| Tag | Where | What the software does |
|---|---|---|
| **ST1**, **ST2**, **DEPOT** | at each station | exact position fix: the train snaps to that station |
| **BRANCH** | on the depot branch, **just after the switch** | the train is shown on the Branch → Depot track and continues by wheel distance. Keep it close to the switch so the dashboard updates quickly. |
| **CAL0** | start of the calibration zone (track out of the Depot) | wheel count at the 0 m mark is stored; the dashboard only shows the train past this tag once it has read it |
| **CAL100** | end of the calibration zone | counts since CAL0 → wheel turns → **new wheel circumference = zone length ÷ turns**, saved for that train (same: not shown past it until read) |

The calibration zone is 100 m in the real system; on the model it is 10 cm (100 m ÷ demo scale 1000). Set the measured length in Demo settings. A run is rejected if it changes the wheel size by more than 20% from the last calibration (wheel slip / missed tag), and the value used is the average of the last 3 good runs.

## 6. Registering the track tags

1. Flash the train board and open the Serial Monitor (115200).
2. Hold each tag to the reader. The board prints `station tag {"tag":"04A3B2C1",...}`, and the dashboard shows *"unknown track tag 04A3B2C1"*.
3. In the dashboard: **Demo → ⚙ Demo settings → Track tags**, enter each UID next to its name (Station 1, Station 2, Depot, Depot branch, Calibration 0 m, Calibration end) and click **Save track tags**.
4. Stick each tag in place. The reader range is only ~2–3 cm, so mount the reader low and the tag close underneath its path.

## 7. HTTP fallback (same data, no broker)

```
POST http://<laptop-ip>:8000/api/ingest/odometer   {"device_id": "LRV01", "pulses": 15230}
POST http://<laptop-ip>:8000/api/ingest/lrv_rfid   {"device_id": "LRV01", "tag": "04A3B2C1", "pulses": 15230}
```

## 8. Testing

- **Without hardware:** open `http://localhost:8000/simulator`, drag the wheel and click ST1 / ST2 / DEPOT / BRANCH / CAL 0 m / CAL END. It sends exactly these messages. The simulated wheel has its own real size (double-click to edit), and **RUN 100 m TEST** drives it through the calibration zone so the dashboard measures that size.
- **Watch the real traffic** on the laptop:
  ```
  "C:\Program Files\Mosquitto\mosquitto_sub.exe" -h localhost -t "#" -v
  ```

## 9. Teammate firmware format (also accepted, no firmware change needed)

The current team firmware (`main.cpp`: 2 AS5600 encoders + PN532 readers on one board) is accepted as it is:

| Topic | Payload | Backend does |
|---|---|---|
| `splrt/lrv/LRV01/odometer`, `splrt/lrv/LRV02/odometer` | angle in degrees, e.g. `292.41` | unwraps the angle into a running count (4096 per turn, handles 359°→0°, ignores jitter under ~0.7°), then same as `{"pulses": N}`. A **plain number = angle**; a JSON `{"pulses": N}` = running count. |
| `splrt/station/ST1/rfid`, `.../ST2/rfid`, `.../DEPOT/rfid` | card UID, e.g. `84A7FCD7` | position fix at that station |
| `splrt/station/Dir/rfid` | `DEPOT` | depot branch marker (same as BRANCH) |
| `splrt/station/ST0m/rfid`, `.../ST100m/rfid` | card UID | calibration zone start / end (same as CAL0 / CAL100) |

The topic name says which marker was read, so these cards **don't need to be entered under Track tags**. The messages carry no train ID, so they move the train chosen in **Demo settings → Data sources → "Station-reader RFID reads belong to"** (default `LRV01` → 810D-001).

Notes: the wheel must turn less than half a turn between two angle messages (fine at his ~25 ms rate). High-rate angle messages are batched to 5 database writes/s, and the pending count is written before every tag read so station distances and calibration stay exact.

## Old setup (still supported)

Reader **at each station** and a tag **on each train**: one ESP32 with 3 RC522 readers (`hardware/station_rfid/station_rfid.ino`) publishing `splrt/station/<ST1|ST2|DEPOT>/rfid {"tag": "<train tag>"}`, plus `hardware/lrv_encoder/lrv_encoder.ino` on each train. The train tags are entered in Demo settings (Train tag column).
