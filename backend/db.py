"""SQLite schema, connection helper and seed data (59 trains, same layout as makeFleet())."""
import json
import random
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

import config

_lock = threading.RLock()

SCHEMA = """
CREATE TABLE IF NOT EXISTS trains (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  serial TEXT,
  year INTEGER,
  loop TEXT,
  current_km REAL NOT NULL,
  session_km REAL DEFAULT 0,
  status TEXT DEFAULT 'depot',          -- 'in-service' | 'depot' | 'maintenance'
  serviceable INTEGER DEFAULT 1,
  location TEXT,                        -- last RFID station seen (ST1 / ST2 / DEPOT)
  location_at TEXT,
  km_at_location REAL,                  -- odometer when last seen at a station
  last_updated TEXT
);
CREATE TABLE IF NOT EXISTS devices (
  id TEXT PRIMARY KEY,                  -- e.g. LRV01, ST1
  kind TEXT NOT NULL,                   -- 'lrv' | 'station'
  train_id TEXT,                        -- LRV devices only
  last_pulses INTEGER,
  online INTEGER DEFAULT 0,
  last_seen TEXT,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);
CREATE TABLE IF NOT EXISTS tags (
  tag TEXT PRIMARY KEY,                 -- RFID UID, uppercase hex
  train_id TEXT NOT NULL,
  assigned_at TEXT,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);
CREATE TABLE IF NOT EXISTS mileage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id TEXT NOT NULL,
  km_reading REAL NOT NULL,
  delta_km REAL,
  source TEXT,
  recorded_at TEXT NOT NULL,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);
CREATE TABLE IF NOT EXISTS rfid_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  station_id TEXT NOT NULL,
  tag TEXT NOT NULL,
  train_id TEXT,                        -- NULL if the tag is not registered
  km_reading REAL,
  segment_km REAL,                      -- encoder distance since previous station (drift check)
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pm_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id TEXT NOT NULL,
  pm_type TEXT NOT NULL,                -- '2K' | '13K' | '40K' | '120K' | '360K'
  mileage_at_pm REAL NOT NULL,
  performed_at TEXT NOT NULL,
  technician TEXT,
  notes TEXT,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);
CREATE TABLE IF NOT EXISTS stock_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  withdrawn_train_id TEXT NOT NULL,
  replacement_train_id TEXT NOT NULL,
  station TEXT,
  reason TEXT,
  changed_at TEXT NOT NULL,
  FOREIGN KEY (withdrawn_train_id) REFERENCES trains(id),
  FOREIGN KEY (replacement_train_id) REFERENCES trains(id)
);
CREATE TABLE IF NOT EXISTS station_tags (
  tag TEXT PRIMARY KEY,                 -- RFID UID of the tag stuck at the station
  station_id TEXT NOT NULL UNIQUE       -- ST1 / ST2 / DEPOT
);
CREATE TABLE IF NOT EXISTS train_wheels (
  train_id TEXT PRIMARY KEY,            -- per-train wheel size from calibration runs
  circumference_m REAL NOT NULL,
  calibrated_at TEXT
);
CREATE TABLE IF NOT EXISTS calibrations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id TEXT NOT NULL,
  counts INTEGER NOT NULL,              -- encoder counts between the 0 m and 100 m tags
  turns REAL NOT NULL,
  measured_m REAL,                      -- circumference from this run
  previous_m REAL,
  new_m REAL,                           -- value in use after this run (average of recent good runs)
  accepted INTEGER NOT NULL,
  reason TEXT,
  recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cal_pending (
  counter_key TEXT PRIMARY KEY,         -- device (or device~SIM) that passed the 0 m tag
  start_pulses INTEGER NOT NULL,
  started_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS train_marker (
  train_id TEXT PRIMARY KEY,            -- last in-between track tag (CAL0 / CAL100) read since the last station
  marker TEXT NOT NULL,
  km REAL NOT NULL,                     -- train mileage when it was read
  read_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS settings (
  key TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_mileage_train ON mileage_log(train_id, id);
CREATE INDEX IF NOT EXISTS idx_rfid_train ON rfid_events(train_id, id);
CREATE INDEX IF NOT EXISTS idx_pm_train ON pm_history(train_id);
"""


def now_iso():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def connect():
    """One connection per unit of work; a process-wide lock serialises writers."""
    with _lock:
        conn = sqlite3.connect(config.DB_PATH, timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def get_settings(conn):
    s = dict(config.DEFAULT_SETTINGS)
    for row in conn.execute("SELECT key, value FROM settings WHERE key <> 'demo_track'"):
        s[row["key"]] = json.loads(row["value"])
    return s


def init_db(seed=True):
    with connect() as conn:
        conn.executescript(SCHEMA)
        if seed and conn.execute("SELECT COUNT(*) FROM trains").fetchone()[0] == 0:
            _seed(conn)
        # track tags: add any that are missing (also upgrades databases from before these features)
        have = {r[0] for r in conn.execute("SELECT station_id FROM station_tags")}
        for sid, tag in config.DEFAULT_STATION_TAGS.items():
            if sid not in have:
                conn.execute("INSERT OR IGNORE INTO station_tags (tag,station_id) VALUES (?,?)", (tag, sid))


def _seed_fleet():
    """Mirror makeFleet() in First_Dashboard.html, but deterministic."""
    rng = random.Random(2026)
    loops = ["SK-West", "SK-East", "PG-West", "PG-East"]
    fleet, idx = [], 0
    groups = [
        # prefix, type, count, base km, km spread, in-service prob, serial base, year base, year mod
        ("810", "C810", 20, 80000, 280000, 0.72, 5000, 2003, 3),
        ("810A", "C810A", 32, 20000, 200000, 0.78, 6000, 2008, 5),
        ("810D", "C810D", 7, 5000, 100000, 0.70, 7000, 2015, 4),
    ]
    for prefix, ttype, count, base, spread, p_svc, ser, yr, mod in groups:
        for i in range(1, count + 1):
            svc = rng.random() < p_svc
            fleet.append({
                "id": f"{prefix}-{i:03d}", "type": ttype,
                "km": float(int(base + rng.random() * spread)),
                "status": "in-service" if svc else "depot",
                "loop": loops[idx % 4] if svc else None,
                "serial": f"SER{ser + i}", "year": yr + (i % mod),
            })
            idx += 1
    # Same forced PM-alert scenarios as the dashboard
    for i, km in {2: 39800, 5: 119600, 9: 40100, 14: 13050, 18: 1900,
                  22: 359500, 28: 120200, 35: 39700}.items():
        fleet[i]["km"] = float(km)
    return fleet


def _seed(conn):
    ts = now_iso()
    fleet = _seed_fleet()
    for t in fleet:
        conn.execute(
            "INSERT INTO trains (id,type,serial,year,loop,current_km,status,last_updated)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (t["id"], t["type"], t["serial"], t["year"], t["loop"], t["km"], t["status"], ts))
        # Seed PM history: assume every threshold already passed was serviced on time,
        # except trains that are just past a threshold (those start as overdue).
        for cycle, label in zip(config.PM_CYCLES, config.PM_LABELS):
            done_at = (t["km"] // cycle) * cycle
            if done_at > 0 and (t["km"] - done_at) < cycle * config.PM_SEED_OVERDUE_WINDOW:
                done_at -= cycle
            if done_at > 0:
                conn.execute(
                    "INSERT INTO pm_history (train_id,pm_type,mileage_at_pm,performed_at,technician,notes)"
                    " VALUES (?,?,?,?,?,?)",
                    (t["id"], label, done_at, ts, "seed", "Initial record (seed data)"))

    # Demo track: the two model LRVs start at the depot
    for lrv in config.DEMO_LRVS:
        conn.execute("UPDATE trains SET status='depot', loop='DEMO', location=?, location_at=?,"
                     " km_at_location=current_km WHERE id=?",
                     (config.DEPOT_ID, ts, lrv["train_id"]))
        conn.execute("INSERT INTO devices (id,kind,train_id) VALUES (?,?,?)",
                     (lrv["device_id"], "lrv", lrv["train_id"]))
        conn.execute("INSERT INTO tags (tag,train_id,assigned_at) VALUES (?,?,?)",
                     (lrv["tag"], lrv["train_id"], ts))
    for sid in config.STATIONS:
        conn.execute("INSERT INTO devices (id,kind) VALUES (?,?)", (sid, "station"))
