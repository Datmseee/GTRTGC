"""Backend settings. Override any value with an environment variable of the same name."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _env(name, default, cast=str):
    value = os.environ.get(name)
    return default if value is None or value == "" else cast(value)


def _bool(v):
    return str(v).lower() in ("1", "true", "yes", "on")


# SQLite database file (created automatically on first run)
DB_PATH = _env("SPLRT_DB", str(BASE_DIR / "splrt.db"))

# MQTT broker (Mosquitto running on the demo laptop)
MQTT_ENABLED = _env("MQTT_ENABLED", True, _bool)
MQTT_HOST = _env("MQTT_HOST", "localhost")
MQTT_PORT = _env("MQTT_PORT", 1883, int)
MQTT_TOPIC_ROOT = _env("MQTT_TOPIC_ROOT", "splrt")

# Default calibration (editable at runtime via PUT /api/config, stored in the DB)
DEFAULT_SETTINGS = {
    # Encoder counts for one full wheel revolution.
    # AS5600 magnetic angle sensor: 12-bit raw angle -> 4096 counts per revolution.
    "pulses_per_rev": 4096,
    # Wheel circumference in metres (toy wheel: pi x diameter, e.g. 30 mm -> 0.0942 m)
    "wheel_circumference_m": 0.0942,
    # Demo multiplier: 1 real metre on the toy track counts as `demo_scale` metres of
    # LRV mileage, so PM thresholds can be reached during a short demo. Set to 1 for real use.
    "demo_scale": 1000.0,
    # A device that has sent nothing for this many seconds is shown as offline
    "offline_after_s": 15,
    # Maintenance alerts: "due soon" when less than this % of a PM cycle is left, and
    # "overdue" once the train is more than this many km past the PM mileage.
    "pm_soon_pct": 8,
    "pm_overdue_grace_km": 0,
    # Wheel calibration zone: distance between the "0 m" and "100 m" track tags, in toy-track
    # metres (0.1 m x demo_scale 1000 = 100 m), and the largest change accepted from one run.
    "cal_distance_m": 0.1,
    "cal_max_change_pct": 20,
    # Accept data from the simulator page (/simulator). Turn OFF when the real hardware
    # is running, otherwise simulator and ESP32 data for the same LRV get mixed.
    "accept_simulator": True,
    # Teammate's firmware format: station-topic RFID reads (splrt/station/ST1/rfid <uid>) carry no
    # train ID, so they are credited to the train linked to this device.
    "rfid_train_device": "LRV01",
}

# Teammate's firmware publishes the reader position in the topic name:
#   splrt/station/<name>/rfid  <card uid>   ->  this track marker
STATION_TOPIC_MARKERS = {
    "ST1": "ST1", "ST2": "ST2", "DEPOT": "DEPOT",
    "Dir": "BRANCH", "ST0m": "CAL0", "ST100m": "CAL100",
}

# Station / waypoint IDs used by the RFID readers on the demo track
STATIONS = {
    "ST1": "Station 1",
    "ST2": "Station 2",
    "DEPOT": "Depot",
}
DEPOT_ID = "DEPOT"

# Train-mounted reader setup: an RFID tag is stuck at each station, and the reader on the
# train reports which tag it passes. Placeholders - enter the real UIDs in Demo settings.
DEFAULT_STATION_TAGS = {
    "ST1": "5A000001",
    "ST2": "5A000002",
    "DEPOT": "5A000003",
    "BRANCH": "5A000004",
    "CAL0": "5A000005",
    "CAL100": "5A000006",
}

# Extra track tags (not stations):
#   BRANCH - just after the switch into the depot branch: the train is heading to the Depot
#   CAL0 / CAL100 - start / end of the wheel calibration zone on the track out of the Depot
MARKERS = {
    "BRANCH": "Depot branch",
    "CAL0": "Calibration 0 m",
    "CAL100": "Calibration end",
}
TRACK_TAG_IDS = ["ST1", "ST2", "DEPOT", "BRANCH", "CAL0", "CAL100"]

# Physical demo-track layout, used by the dashboard's Demo Track view to place each LRV
# between stations. Lengths are real toy-track metres - measure yours and update them.
# The LRV is assumed to run  ST1 -> ST2 (top)  -> ST1 (bottom)  and  DEPOT -> ST1.
DEMO_TRACK = {
    "segments": [
        {"from": "ST1", "to": "ST2", "path": "top", "length_m": 1.2},
        {"from": "ST2", "to": "ST1", "path": "bottom", "length_m": 1.2},
        {"from": "DEPOT", "to": "ST1", "path": "depot_out", "length_m": 0.8},
        {"from": "BRANCH", "to": "DEPOT", "path": "depot_in", "length_m": 0.3},
    ],
}

# PM cycles - must match PM_CYCLES in First_Dashboard.html
PM_CYCLES = [2000, 13000, 40000, 120000, 360000]
PM_LABELS = ["2K", "13K", "40K", "120K", "360K"]
PM_SOON_FRACTION = 0.08   # "due soon" when less than 8% of the cycle remains (same as dashboard)
PM_SEED_OVERDUE_WINDOW = 0.02  # seed data: trains just past a threshold start as overdue

# Demo LRVs: device ID of the on-board MCU -> fleet train ID, plus the RFID tag on that train.
# Replace the tag UIDs with the real ones (or register them via POST /api/tags).
DEMO_LRVS = [
    {"device_id": "LRV01", "train_id": "810D-001", "tag": "A1B2C3D4"},
    {"device_id": "LRV02", "train_id": "810D-002", "tag": "E5F6A7B8"},
]
