# Hardware ↔ Software Protocol (v0.1)

How the ESP32s on the demo track talk to the SPLRT backend. Hardware and software teams: agree on this page before flashing firmware.

## 1. Network

```
 LRV01/LRV02 (ESP32 + axle encoder)  ─┐
                                       ├─ WiFi (same phone hotspot) ─► Laptop: Mosquitto :1883 ─► FastAPI :8000 ─► Dashboard
 Station ESP32 (3x MFRC522 readers)   ─┘
```

- **Transport:** MQTT over WiFi. Broker = Mosquitto on the demo laptop, port **1883**, no password (demo only).
- **Everything on one hotspot.** ESP32s connect to the **laptop's IP address** (run `ipconfig` on the laptop and use the "Wireless LAN" IPv4 address).
- **Fallback:** if MQTT isn't possible, the same data can be sent with HTTP POST (section 5).
- **ESP32 libraries:** `PubSubClient`, `ArduinoJson`, `MFRC522`.

## 2. IDs

| Device | ID | Notes |
|---|---|---|
| Train MCU #1 | `LRV01` | linked to fleet train `810D-001` on the server |
| Train MCU #2 | `LRV02` | linked to fleet train `810D-002` on the server |
| Reader at Station 1 | `ST1` | |
| Reader at Station 2 | `ST2` | |
| Reader at Depot | `DEPOT` | a train read here is shown as "in depot" |

Device → train links and tag → train links live on the server, so swapping hardware between trains needs no reflashing.

## 3. Topics and payloads

| From | Topic | Payload | When |
|---|---|---|---|
| LRV | `splrt/lrv/<LRV_ID>/odometer` | `{"pulses": 15230}` | every **1 s** |
| Station reader | `splrt/station/<STATION_ID>/rfid` | `{"tag": "04A3B2C1"}` | when a tag is read |
| LRV | `splrt/lrv/<LRV_ID>/status` | `online` / `offline` | on connect + as MQTT **Last Will** (retained) |
| Station | `splrt/station/<STATION_ID>/status` | `online` / `offline` | same |

A plain value without JSON (`15230` or `04A3B2C1`) is also accepted.

## 4. Rules for the firmware

0. **Our encoder is an AS5600 magnetic angle sensor** (raw 0–4095 = one wheel turn). It gives an angle, not pulses, so the LRV firmware "unwraps" the angle into a running total: add the change in raw angle each read (handling the 4095→0 wrap, ignoring jitter under ~8 counts, and skipping reads while the sensor reports a magnet problem). **4096 counts = 1 wheel revolution**, and that total is what goes in `pulses`. See `hardware/lrv_encoder/lrv_encoder.ino`.
1. **`pulses` = running total since boot, not the change since the last message.** A lost message then loses no distance. If the ESP32 reboots and the count drops back to 0, the server detects it and keeps counting.
2. **No km maths on the ESP32.** The server converts pulses → km using `pulses_per_rev`, `wheel_circumference_m` and `demo_scale`. Change them with `PUT /api/config`, no reflash needed. `pulses_per_rev` is already 4096 for the AS5600. **Tell the software team the wheel diameter.**
3. **No timestamps.** The server stamps each message on arrival, since the ESP32 has no real-time clock.
4. **Tag UID:** uppercase hex, no spaces or colons (e.g. `04A3B2C1`). The server also cleans up `04:a3:b2:c1`.
5. **De-duplicate at the reader:** don't resend the same tag on the same reader within ~5 s. The server ignores repeats too.
6. **Use a Last Will** (`status` topic, payload `offline`, retained) so the dashboard shows when a device drops off.

Example firmware: `hardware/lrv_encoder/lrv_encoder.ino` and `hardware/station_rfid/station_rfid.ino`.

## 5. HTTP fallback (same data, no broker)

```
POST http://<laptop-ip>:8000/api/ingest/odometer   {"device_id": "LRV01", "pulses": 15230}
POST http://<laptop-ip>:8000/api/ingest/rfid       {"station_id": "ST1", "tag": "04A3B2C1"}
```

## 6. Registering real tags

The server ships with placeholder tags `A1B2C3D4` (LRV01) and `E5F6A7B8` (LRV02). When a real tag is read, the server logs **"Unknown tag XXXXXXXX at ST1"**. Link it to a train:

```
POST /api/tags   {"tag": "XXXXXXXX", "train_id": "810D-001"}
```

or edit `DEMO_LRVS` in `backend/config.py` before the first run.

## 7. Testing without hardware

`python backend/simulate_hardware.py` publishes exactly these messages for 2 fake LRVs.

To watch the real traffic on the laptop:
```
"C:\Program Files\Mosquitto\mosquitto_sub.exe" -h localhost -t "splrt/#" -v
```

To send a test message by hand:
```
"C:\Program Files\Mosquitto\mosquitto_pub.exe" -h localhost -t splrt/station/ST1/rfid -m "{\"tag\":\"A1B2C3D4\"}"
```
