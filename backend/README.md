# SPLRT Backend (FastAPI + MQTT + SQLite)

Receives axle-encoder and RFID data from the demo hardware, stores it in SQLite, runs the PM logic and serves it to the dashboard (REST + WebSocket).
Protocol for the hardware team: [`../HARDWARE_PROTOCOL.md`](../HARDWARE_PROTOCOL.md).

## Quick start (Windows, PowerShell)

```powershell
cd backend
python -m pip install -r requirements.txt

# Terminal 1 - MQTT broker (Mosquitto is already installed on the laptop)
& "C:\Program Files\Mosquitto\mosquitto.exe" -c mosquitto.conf -v

# Terminal 2 - backend API
python main.py                  # http://localhost:8000/docs  (try-it-out API page)

# Fake hardware (until the ESP32s are ready) - pick one:
#   a) open http://localhost:8000/simulator  -> drag the wheel with the mouse, click ST1 / ST2 / DEPOT
#   b) Terminal 3: python simulate_hardware.py   -> 2 LRVs drive around by themselves
```

**Demo Track view.** Demo mode is focused on the demo setup only: the map area shows the demo track (ST1, ST2, Depot), and the fleet list, header stats, alerts and ticker show only the two demo LRVs (810D-001, 810D-002). The full 59-train Sengkang–Punggol network stays in Simulation mode. Each model LRV is drawn at its last RFID station plus the encoder distance travelled since, along the next segment (ST1 → ST2 on top, ST2 → ST1 on the bottom, Depot → ST1). It stops just short of the next station until that station's reader actually sees the tag. **Measure your real track and put the segment lengths in `DEMO_TRACK` in `config.py`** so the position matches the physical LRV.

**Demo settings** (Demo mode → **⚙ DEMO SETTINGS**, top-right of the Demo Track). Everything is saved in the backend database:
- **Trains on the demo track:** add a train (train ID, the device ID its ESP32 uses, the RFID tag UID, starting mileage), change a train's device/tag, override its mileage (logged as a manual entry, handy for putting a train just below a PM threshold before a demo), or remove it.
- **Station distances:** the real toy-track length of ST1 → ST2, ST2 → ST1 and Depot → ST1, in metres.
- **Wheel & scale:** wheel diameter (or circumference), counts per wheel turn (AS5600 = 4096) and the demo scale.
- **Data sources:** *Accept data from the simulator page*. **Switch this off when the real ESP32s are running.** The backend listens to both, and it only knows a message is for `LRV01` from its device ID, so simulator clicks would otherwise mix with the real LRV01's counts. With it off, the simulator page shows *SIMULATOR INPUT OFF* and nothing it sends is recorded; real hardware (MQTT or HTTP) is always accepted.

**Hardware simulator page (`/simulator`).** A stand-in for the ESP32s that you control by hand:
- **Wheel:** drag it in a circle (or scroll on it) = the AS5600 on the axle. 4096 counts per turn, sent as a running total every second, exactly like the firmware. *Auto spin* turns it by itself.
- **ST1 / ST2 / DEPOT buttons** (or keys 1 / 2 / 3) = that RFID reader sees the selected LRV's tag.
- **LRV01 / LRV02** chooses which model train you are driving. *Reboot MCU* resets the counter to 0 like an ESP32 restart (the server keeps the mileage).
- It posts to `/api/ingest/odometer` and `/api/ingest/rfid`, which run the same code as the MQTT topics, so the Demo dashboard can't tell it apart from real hardware. Put it side by side with `http://localhost:8000/?mode=demo`.

Open **http://localhost:8000/** for the dashboard (served by the backend, no separate web server needed) and **http://localhost:8000/docs** to see and try every endpoint.

**Modes.** When the dashboard opens it asks which mode to use. You can switch any time with the **SIMULATION | DEMO** switch in the top bar.
- **SIMULATION** (without data): the original simulated fleet. No hardware or backend needed, e.g. on GitHub Pages.
- **DEMO** (with data): data comes from this backend. Mileage/PM of `810D-001` and `810D-002` follow the demo LRVs, and their location (ST1 / ST2 / Depot) shows in the fleet list. The start screen shows whether the backend is running.

Badge next to the switch: **SIM** = simulation, **CONNECTING** = Demo mode looking for the backend, **LIVE** = receiving data, **OFFLINE** = connection lost (last data stays on screen, it reconnects automatically).

Skip the start screen with `http://localhost:8000/?mode=demo` (handy on demo day) or `?mode=sim`. The dashboard looks for the backend on the page's own server, then `http://localhost:8000`; for another address add `?api=http://192.168.x.x:5500`.
In Demo mode, the trains on the map stay parked at stations and mileage never increases on its own: it only changes when the hardware reports distance. (The two demo LRVs run on the toy track, which is not part of the Sengkang–Punggol map; follow them in the fleet list.)

**Troubleshooting**
- **`WinError 10013` / port blocked:** use another port, e.g. `python main.py --port 5500`. For Mosquitto, change `listener 1883` in `mosquitto.conf`, and the port in the firmware too.
- **No broker running yet?** Use `python main.py --no-mqtt` and `python simulate_hardware.py --http http://localhost:8000`.
- **ESP32s can't connect:** check that everything is on the same hotspot and that you used the laptop's hotspot IP (`ipconfig`). If Windows Firewall asks about Python or Mosquitto, click **Allow** for private networks.
- **"Error: Only one usage of each socket address" from Mosquitto:** the Mosquitto Windows service is already running on 1883. Stop it (`net stop mosquitto` in an admin terminal) or change the port.
- **Reset all data:** stop the backend and delete `splrt.db`. It is recreated with seed data on the next start.

## How it works

| File | Purpose |
|---|---|
| `main.py` | FastAPI app, REST routes, WebSocket `/ws`, starts the MQTT bridge |
| `mqtt_bridge.py` | Subscribes to `splrt/#` topics and routes messages to `service.py` |
| `service.py` | Ingestion (pulses → km, RFID → position), fleet queries, PM/stock-change actions |
| `pm.py` | PM status per cycle (2K/13K/40K/120K/360K), same thresholds as the dashboard |
| `db.py` | SQLite schema + seed data (59 trains, same IDs as the dashboard) |
| `config.py` | Broker address, calibration defaults, station IDs, demo LRV ↔ train ↔ tag mapping |
| `simulate_hardware.py` | Fake LRVs and readers for testing |
| `tests/` | `python -m pytest -q` |

**Mileage:** each LRV sends its total pulse count. The server adds the difference × (wheel circumference ÷ pulses per rev) × `demo_scale` to that train's mileage. `demo_scale` defaults to 1000 (1 m on the toy track = 1 km), so PM thresholds can be reached in a short demo. Set it to 1 for real-world units.

**Position:** a station reader seeing a tag gives an exact position fix. The encoder distance since the previous station is saved as `segment_km`, which shows encoder drift between stations (the "gap between stations" challenge).

**PM:** next due = last PM for that level (or any higher level) + cycle. Overdue once reached, "soon" when less than 8% remains. Record a completed PM with `POST /api/pm`.

## API

| Method | Path | What |
|---|---|---|
| GET | `/api/health` | backend + broker status |
| GET | `/api/fleet` | all 59 trains with mileage, status, location, worst PM |
| GET | `/api/trains/{id}` | one train incl. every PM cycle and its tags |
| GET | `/api/alerts` | trains with PM overdue / due soon |
| GET | `/api/history/{id}` | PM history, mileage log, RFID events, stock changes |
| GET | `/api/events` | latest RFID reads (incl. unknown tags) |
| GET | `/api/devices` | ESP32s and whether they're online |
| PUT | `/api/devices/{device_id}` | link an LRV MCU to a train `{"train_id": "810D-001"}` |
| POST | `/api/tags` | link an RFID tag to a train `{"tag": "04A3B2C1", "train_id": "810D-001"}` |
| POST | `/api/pm` | record a PM `{"train_id", "pm_type": "2K", "technician", "notes"}` |
| POST | `/api/stockchange` | `{"withdrawn_train_id", "replacement_train_id", "station", "reason"}` |
| GET/PUT | `/api/track` | demo-track segment lengths (edit in Demo settings) |
| GET/POST | `/api/demo/trains` | trains on the demo track; POST adds or updates `{train_id, device_id, tag, mileage?}` |
| DELETE | `/api/demo/trains/{id}` | take a train off the demo track |
| GET/PUT | `/api/config` | calibration: `pulses_per_rev`, `wheel_circumference_m`, `demo_scale`, `offline_after_s`, `accept_simulator` |
| POST | `/api/ingest/odometer` | HTTP fallback for hardware |
| POST | `/api/ingest/rfid` | HTTP fallback for hardware |
| WS | `/ws` | live events: `train`, `position`, `device`, `unknown_tag` (dashboard falls back to polling if WebSockets are unavailable) |
| GET | `/` | the dashboard (`../First_Dashboard.html`) |
| GET | `/simulator` | hardware simulator page (wheel + station buttons) |

Train objects use the same field names as the dashboard's `fleet` (`id`, `type`, `mileage`, `status`, `loop`, and `pm` shaped like `getPMStatus()`), so wiring the dashboard up needs only small changes.
