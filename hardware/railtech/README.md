# Railtech train board firmware (ESP32-S3)

This firmware runs on the board inside the demo LRV. It does two jobs:

- reads the **wheel angle** from an **AS5600** magnetic encoder;
- reads **RFID track tags** with a **PN532**.

It sends both to the SPLRT backend over **MQTT** (Mosquitto on the demo laptop). The backend turns wheel turns into mileage, snaps the train to a station when a tag is read, and calibrates the wheel size in the 0 m → END zone.

PlatformIO project · board `4d_systems_esp32s3_gen4_r8n16` · Arduino framework.
`CHANGES.md` lists the reliability fixes (1–7) made on top of the original sketch.

---

## 1. Wiring

### PN532 RFID reader (SPI)

| PN532 pin | ESP32-S3 | Notes |
|---|---|---|
| SCK | **GPIO 12** | |
| MISO | **GPIO 13** | |
| MOSI | **GPIO 11** | |
| SS / NSS / CS | **GPIO 10** | |
| VCC | **5 V** (recommended) or 3.3 V | 5 V gives a stronger field if the module has an on-board regulator (most red PN532 boards do). Add a 100–470 µF capacitor across VCC–GND if reads drop out while Wi-Fi is busy. |
| GND | GND | short, solid wire |
| IRQ | not connected | not used: the firmware polls over SPI |
| RSTO / RST | not connected | |

**Set the module's mode switches to SPI.**

### AS5600 wheel encoder (I2C)

| AS5600 pin | Encoder 1 (LRV01, used) | Encoder 2 (LRV02, off by default) |
|---|---|---|
| SDA | **GPIO 8** (`Wire`) | GPIO 42 (`Wire1`) |
| SCL | **GPIO 9** (`Wire`) | GPIO 41 (`Wire1`) |
| VCC | 3.3 V | 3.3 V |
| GND | GND | GND |
| DIR | **GND, soldered** | GND |
| OUT, GPO | not connected | not connected |

- **DIR must be tied to GND.** If it floats, the direction flips at random. The backend adds every angle change as mileage, so the train "creeps" forward on the dashboard.
- **Magnet:** a diametric magnet centred over the chip, **0.5–3 mm** away, fixed so it can't wobble. With no magnet the AS5600 outputs random angles, which shows up as fake mileage.
- Loose SDA/SCL/GND/VCC joints also produce angle jumps, so solder them. For the same reason, don't pull just VCC to "disable" the sensor: it can half-power itself through SDA/SCL. Unplug all four wires, or build without it.

Pins are defined in `src/PN532.cpp` and `include/EncoderConfiguration.h`.

### Power

- USB-C from the laptop (for uploading or monitoring) or from a power bank (for the demo).
- Use a **data** USB cable for uploading. Power-only cables don't show up as a COM port.

### Second encoder (`USE_ENCODER2`)

The car has **one** AS5600 (LRV01), so encoder 2 is compiled out by default (`include/AppConfig.h`).

If it were left on with no sensor connected, the second I2C bus would read back `0xFF` bytes, which is raw 4095 (359.9°). That causes three problems:

- one junk angle is published to `splrt/lrv/LRV02/odometer` at boot;
- every loop wastes a failed I2C transaction;
- floating SDA/SCL lines can return random angles, which become fake LRV02 mileage.

To use a second sensor, set `USE_ENCODER2 1` in `include/AppConfig.h`, or uncomment `build_flags = -DUSE_ENCODER2=1` in `platformio.ini`.

---

## 2. RFID tags

The UIDs are in `src/main.cpp`. The topic name tells the backend which marker was read (see `STATION_TOPIC_MARKERS` in `backend/config.py`).

| UID | Variable | What it is | Published to | Backend marker |
|---|---|---|---|---|
| `84A7FCD7` | `stationCard1` | Station 1 (Sengkang) | `splrt/station/ST1/rfid` | `ST1` |
| `0396F313` | `stationCard2` | Station 2 (Punggol) | `splrt/station/ST2/rfid` | `ST2` |
| `5F48F0D7` | `stationCard3` | Depot | `splrt/station/DEPOT/rfid` | `DEPOT` |
| `6D85EFD7` | `card0m` | Calibration zone start ("0 m") | `splrt/station/ST0m/rfid` | `CAL0` |
| `8EC201D8` | `card100m` | Calibration zone end ("100 m" = 10 cm on the 1:1000 model) | `splrt/station/ST100m/rfid` | `CAL100` |
| `E84A00D8` | `cardDirection` | Depot branch: the train is heading into the depot | `splrt/station/Dir/rfid` (payload `DEPOT`) | `BRANCH` |

- Unknown tags are printed as `Ur stinky, UID: <uid>` and not published.
- To change a tag, edit its byte array in `src/main.cpp`.

---

## 3. MQTT

| Topic | Payload | When |
|---|---|---|
| `splrt/lrv/LRV01/odometer` | wheel angle in degrees, text, e.g. `123.45` (0–360) | when the angle changed by ≥ 5°, checked at most every 50 ms (≤ 20 messages/s) |
| `splrt/lrv/LRV02/odometer` | same | only with `USE_ENCODER2 1` |
| `splrt/station/<ST1\|ST2\|DEPOT\|ST0m\|ST100m>/rfid` | tag UID as hex text, e.g. `84A7FCD7` | once when a tag arrives; not repeated while it stays in range; can repeat after 2 s out of range |
| `splrt/station/Dir/rfid` | `DEPOT` | when the direction tag is read |

- Client ID: `esp32s3-nfc-01`. No username or password (demo broker; see `backend/mosquitto.conf`).
- The backend unwraps the angle into a running wheel count. The wheel must turn less than half a turn between two messages.
- Station-topic reads carry no train ID. The backend credits them to the device in the setting `rfid_train_device` (default `LRV01`).

---

## 4. Wi-Fi and broker settings: `include/secrets.h`

The SSID, password and broker IP/port are **not** in the code. They live in `include/secrets.h`, which is **git-ignored**.

```
copy include/secrets.example.h  ->  include/secrets.h      (then edit it)
```

| Define | Value |
|---|---|
| `WIFI_SSID` / `WIFI_PASS` | the demo hotspot (must be 2.4 GHz; on an iPhone turn on "Maximise Compatibility") |
| `MQTT_BROKER_IP` | the laptop running Mosquitto: `ipconfig` → Wi-Fi IPv4. It can change each time the laptop joins the hotspot. A laptop's own Windows Mobile Hotspot is always `192.168.137.1`. |
| `MQTT_BROKER_PORT` | `1883` |

If `secrets.h` is missing, the build stops with a message telling you to create it.

---

## 5. Build, upload, monitor

1. Install **VS Code** and the **PlatformIO IDE** extension.
   - The first launch downloads the PlatformIO core and the ESP32 toolchain. That takes a few minutes, needs internet, and uses about 2 GB.
2. **File → Open Folder → `hardware/railtech`**. Open the folder that contains `platformio.ini`, not `src/`.
   - The first build also downloads the libraries listed in `lib_deps`.
3. Create `include/secrets.h` (section 4).
4. Use the buttons in the bottom bar:
   - **✓ Build**: on the command line, `pio run`
   - **→ Upload**: `pio run -t upload`
   - **🔌 Serial Monitor** (115200 baud): `pio device monitor`
5. Make sure upload goes to the right port.
   - The board shows up as **`USB Serial Device (COMx)`**.
   - "Standard Serial over Bluetooth link" ports are not the board. If Auto picks one, the upload fails with "semaphore timeout".
   - Choose the port by clicking **Auto** in the bottom bar, or set `upload_port = COMx` in `platformio.ini`.
   - To list ports in PowerShell: `Get-PnpDevice -Class Ports -PresentOnly | Select FriendlyName`.
6. If upload says "port busy" or "failed to connect":
   - close other serial monitors;
   - put the board in download mode: hold **BOOT**, tap **RESET**, release **BOOT**, then upload again;
   - after **SUCCESS**, tap **RESET**.

The first build compiles the whole Arduino framework (3–10 min). Later builds take seconds.

---

## 6. Expected serial output on boot

The board uses native USB serial, so open the Serial Monitor first, then press **RESET** to see the boot messages:

```
PN532 ready (fw 1.6)
WiFi attempt 1/3: <your hotspot>
.......
Connected! IP: 172.20.10.7
WiFi connected
MQTT connected
```

Then while running:

```
Angle1: 123.45 deg | raw 1404          <- wheel turned >= 5 deg
Card on reader 1: 84A7FCD7
Station 1 reached!
```

With the wheel standing still there should be **no** `Angle1:` lines. If they keep appearing, the encoder is noisy: check DIR, the magnet and the joints.

| Message | Meaning / what to do |
|---|---|
| `PN532 not found yet - will keep retrying` | the reader isn't answering: check its power, the SPI wires and the SPI mode switches. It retries every 1 s in the background. |
| `PN532 wedged, recovering...` (often) | power dips: feed the PN532 from 5 V and add a capacitor |
| `WiFi failed after all retries.` | wrong SSID/password, or the hotspot is 5 GHz only. The board keeps retrying from `loop()`. |
| `MQTT connect failed, rc=-2` | can't reach the broker: wrong `MQTT_BROKER_IP`, Mosquitto not running, or Windows Firewall blocking TCP 1883. It retries every 2 s. |

Run the backend side (from the repo's `backend/` folder):

```
& "C:\Program Files\Mosquitto\mosquitto.exe" -c mosquitto.conf -v
python main.py
```

The Mosquitto window should show `New client connected ... esp32s3-nfc-01`.
