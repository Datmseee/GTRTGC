"""Core logic shared by MQTT and HTTP ingestion and by the REST API."""
import json
import logging
from datetime import datetime, timezone

import config
import db
import pm

log = logging.getLogger("splrt")

# Set by main.py so every change is pushed to connected dashboards over WebSocket.
_listeners = []


def on_event(fn):
    _listeners.append(fn)


def emit(event):
    for fn in list(_listeners):
        try:
            fn(event)
        except Exception:  # never let a listener break ingestion
            log.exception("event listener failed")


class NotFound(Exception):
    pass


def normalise_tag(tag):
    return "".join(ch for ch in str(tag).upper() if ch.isalnum())


# ---------------------------------------------------------------- ingestion

SIM_SUFFIX = "~SIM"


def ingest_odometer(device_id, pulses, source="mqtt"):
    """Handle a cumulative pulse count from an LRV's axle encoder.

    The device sends the running total since boot. The server keeps the previous value,
    so a lost message loses no distance. If the total goes down, the MCU rebooted and the
    new total is counted from zero.

    The simulator page keeps its own counter ("<device>~SIM") for the same train, so the
    real ESP32 and the simulator can both drive a train at the same time: each one's
    distance is added, and neither corrupts the other's running total.
    """
    pulses = int(pulses)
    if pulses < 0:
        raise ValueError("pulses must be >= 0")
    ts = db.now_iso()
    sim = source == "simulator"
    with db.connect() as conn:
        s = db.get_settings(conn)
        if sim:
            base = conn.execute("SELECT train_id FROM devices WHERE id=? AND kind='lrv'", (device_id,)).fetchone()
            if base is None or not base["train_id"]:
                raise NotFound(f"device {device_id} is not linked to a train (add it in Demo settings)")
            train_id = base["train_id"]
            key = device_id + SIM_SUFFIX
            dev = conn.execute("SELECT * FROM devices WHERE id=?", (key,)).fetchone()
            if dev is None:
                conn.execute("INSERT INTO devices (id,kind) VALUES (?,'sim')", (key,))
                dev = conn.execute("SELECT * FROM devices WHERE id=?", (key,)).fetchone()
        else:
            key = device_id
            dev = conn.execute("SELECT * FROM devices WHERE id=?", (key,)).fetchone()
            train_id = dev["train_id"] if dev else None
        if dev is None:
            conn.execute("INSERT INTO devices (id,kind,last_pulses,online,last_seen) VALUES (?,?,?,1,?)",
                         (device_id, "lrv", pulses, ts))
            log.warning("New LRV device %s registered - assign it to a train in Demo settings", device_id)
            result = {"device_id": device_id, "train_id": None, "delta_pulses": 0, "delta_km": 0.0,
                      "note": "unassigned device - baseline stored"}
            event = {"type": "device", "device_id": device_id, "online": True}
        else:
            prev = dev["last_pulses"]
            if prev is None:
                delta = 0                       # first message: just take a baseline
            elif pulses >= prev:
                delta = pulses - prev
            else:
                delta = pulses                  # counter reset (MCU reboot)
                log.info("%s counter reset (%s -> %s)", key, prev, pulses)
            conn.execute("UPDATE devices SET last_pulses=?, online=1, last_seen=? WHERE id=?",
                         (pulses, ts, key))
            delta_km = delta / s["pulses_per_rev"] * s["wheel_circumference_m"] * s["demo_scale"] / 1000.0
            result = {"device_id": device_id, "train_id": train_id, "delta_pulses": delta,
                      "delta_km": round(delta_km, 4), "source": source}
            event = None
            if train_id and delta > 0:
                conn.execute("UPDATE trains SET current_km=current_km+?, session_km=session_km+?,"
                             " last_updated=? WHERE id=?", (delta_km, delta_km, ts, train_id))
                km = conn.execute("SELECT current_km FROM trains WHERE id=?", (train_id,)).fetchone()[0]
                conn.execute("INSERT INTO mileage_log (train_id,km_reading,delta_km,source,recorded_at)"
                             " VALUES (?,?,?,?,?)", (train_id, km, delta_km, source, ts))
                result["km"] = round(km, 3)
                event = {"type": "train", "train": _train_dict(conn, train_id)}
    if event:
        emit(event)
    return result


def _drop_future_pm(conn, train_id, km):
    """After a manual mileage change, PM records above the new mileage can't be right - remove them."""
    conn.execute("DELETE FROM pm_history WHERE train_id=? AND mileage_at_pm > ?", (train_id, km))


def adjust_train(train_id, mileage=None, location=None):
    """Manual correction from the dashboard (double-click). Logged as 'manual'."""
    if mileage is None and location is None:
        raise ValueError("nothing to change")
    if mileage is not None and (isinstance(mileage, bool) or not isinstance(mileage, (int, float))
                                or not 0 <= mileage <= 5_000_000):
        raise ValueError("mileage must be between 0 and 5,000,000 km")
    if location is not None and location not in config.STATIONS:
        raise ValueError(f"location must be one of {list(config.STATIONS)}")
    ts = db.now_iso()
    with db.connect() as conn:
        r = conn.execute("SELECT * FROM trains WHERE id=?", (train_id,)).fetchone()
        if r is None:
            raise NotFound(f"train {train_id} not found")
        if mileage is not None:
            # keep the distance since the last station, so the LRV stays where it is on the track
            since = 0.0 if r["km_at_location"] is None else max(0.0, r["current_km"] - r["km_at_location"])
            conn.execute("UPDATE trains SET current_km=?, km_at_location=?, last_updated=? WHERE id=?",
                         (float(mileage), float(mileage) - since, ts, train_id))
            conn.execute("INSERT INTO mileage_log (train_id,km_reading,delta_km,source,recorded_at)"
                         " VALUES (?,?,NULL,'manual',?)", (train_id, float(mileage), ts))
            _drop_future_pm(conn, train_id, float(mileage))
        if location is not None:
            km = conn.execute("SELECT current_km FROM trains WHERE id=?", (train_id,)).fetchone()[0]
            status = "depot" if location == config.DEPOT_ID else "in-service"
            conn.execute("UPDATE trains SET location=?, location_at=?, km_at_location=current_km,"
                         " status=CASE WHEN status='maintenance' THEN status ELSE ? END, last_updated=?"
                         " WHERE id=?", (location, ts, status, ts, train_id))
            conn.execute("INSERT INTO rfid_events (station_id,tag,train_id,km_reading,segment_km,recorded_at)"
                         " VALUES (?,'MANUAL',?,?,NULL,?)", (location, train_id, km, ts))
        t = _train_dict(conn, train_id)
    emit({"type": "train", "train": t})
    return t


def ingest_rfid(station_id, tag, source="mqtt"):
    """Handle a tag read at a station / depot reader: exact position fix for that train."""
    tag = normalise_tag(tag)
    if not tag:
        raise ValueError("empty tag")
    ts = db.now_iso()
    with db.connect() as conn:
        conn.execute("INSERT INTO devices (id,kind,online,last_seen) VALUES (?,?,1,?)"
                     " ON CONFLICT(id) DO UPDATE SET online=1, last_seen=excluded.last_seen",
                     (station_id, "station", ts))
        row = conn.execute("SELECT train_id FROM tags WHERE tag=?", (tag,)).fetchone()
        if row is None:
            conn.execute("INSERT INTO rfid_events (station_id,tag,recorded_at) VALUES (?,?,?)",
                         (station_id, tag, ts))
            log.warning("Unknown tag %s at %s - register it via POST /api/tags", tag, station_id)
            event = {"type": "unknown_tag", "station_id": station_id, "tag": tag, "at": ts}
            result = {"station_id": station_id, "tag": tag, "train_id": None, "note": "unknown tag"}
        else:
            train_id = row["train_id"]
            t = conn.execute("SELECT current_km, km_at_location, location FROM trains WHERE id=?",
                             (train_id,)).fetchone()
            segment = None if t["km_at_location"] is None else t["current_km"] - t["km_at_location"]
            status = "depot" if station_id == config.DEPOT_ID else "in-service"
            # Ignore the same reader seeing the same tag repeatedly while the train dwells
            repeat = t["location"] == station_id and (segment or 0) == 0
            conn.execute("UPDATE trains SET location=?, location_at=?, km_at_location=current_km,"
                         " status=CASE WHEN status='maintenance' THEN status ELSE ? END,"
                         " last_updated=? WHERE id=?", (station_id, ts, status, ts, train_id))
            if not repeat:
                conn.execute("INSERT INTO rfid_events (station_id,tag,train_id,km_reading,segment_km,"
                             "recorded_at) VALUES (?,?,?,?,?,?)",
                             (station_id, tag, train_id, t["current_km"], segment, ts))
            result = {"station_id": station_id, "tag": tag, "train_id": train_id,
                      "segment_km": None if segment is None else round(segment, 3), "repeat": repeat}
            event = None if repeat else {"type": "position", "train": _train_dict(conn, train_id),
                                         "station_id": station_id, "segment_km": result["segment_km"],
                                         "at": ts}
    if event:
        emit(event)
    return result


def set_device_status(device_id, online, kind="lrv"):
    ts = db.now_iso()
    with db.connect() as conn:
        conn.execute("INSERT INTO devices (id,kind,online,last_seen) VALUES (?,?,?,?)"
                     " ON CONFLICT(id) DO UPDATE SET online=excluded.online, last_seen=excluded.last_seen",
                     (device_id, kind, 1 if online else 0, ts))
    emit({"type": "device", "device_id": device_id, "online": bool(online)})


# ---------------------------------------------------------------- queries

def _pm_rows(conn, train_id):
    return [(r["pm_type"], r["mileage_at_pm"]) for r in
            conn.execute("SELECT pm_type, mileage_at_pm FROM pm_history WHERE train_id=?", (train_id,))]


def _train_dict(conn, train_id, detail=False):
    r = conn.execute("SELECT * FROM trains WHERE id=?", (train_id,)).fetchone()
    if r is None:
        raise NotFound(f"train {train_id} not found")
    worst, cycles = pm.pm_summary(r["current_km"], _pm_rows(conn, train_id))
    d = {
        "id": r["id"], "type": r["type"], "serial": r["serial"], "year": r["year"],
        "loop": r["loop"], "mileage": round(r["current_km"], 1), "session_km": round(r["session_km"], 3),
        "status": r["status"], "serviceable": bool(r["serviceable"]),
        "location": r["location"], "location_at": r["location_at"],
        # encoder distance since the last RFID station fix (places the LRV on the demo track)
        "since_station_km": None if r["km_at_location"] is None
        else round(max(0.0, r["current_km"] - r["km_at_location"]), 4),
        "last_updated": r["last_updated"], "pm": worst,
    }
    dev = conn.execute("SELECT id, online, last_seen FROM devices WHERE train_id=?", (train_id,)).fetchone()
    d["device"] = None if dev is None else {"id": dev["id"], "online": _is_online(conn, dev),
                                            "last_seen": dev["last_seen"]}
    d["pm_cycles"] = cycles          # used by the dashboard's PM schedule
    if detail:
        d["tags"] = [x["tag"] for x in conn.execute("SELECT tag FROM tags WHERE train_id=?", (train_id,))]
    return d


def _is_online(conn, dev):
    if not dev["online"] or not dev["last_seen"]:
        return False
    if "kind" in dev.keys() and dev["kind"] == "station":
        return True   # readers only talk when a tag passes; rely on the MQTT Last Will instead
    s = db.get_settings(conn)
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(dev["last_seen"])).total_seconds()
    return age <= s["offline_after_s"]


def fleet():
    with db.connect() as conn:
        ids = [r[0] for r in conn.execute("SELECT id FROM trains ORDER BY rowid")]
        return [_train_dict(conn, i) for i in ids]


def train(train_id):
    with db.connect() as conn:
        return _train_dict(conn, train_id, detail=True)


def alerts():
    out = []
    for t in fleet():
        if t["pm"]["status"] in ("over", "soon"):
            out.append({"train_id": t["id"], "type": t["type"], "level": t["pm"]["status"],
                        "pm": t["pm"]["name"], "remaining_km": t["pm"]["remaining"],
                        "location": t["location"] or t["loop"] or "Depot"})
    out.sort(key=lambda a: (a["level"] != "over", a["remaining_km"]))
    return out


def history(train_id, limit=100):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM trains WHERE id=?", (train_id,)).fetchone() is None:
            raise NotFound(f"train {train_id} not found")
        q = lambda sql: [dict(r) for r in conn.execute(sql, (train_id, limit))]
        return {
            "train_id": train_id,
            "pm_history": q("SELECT * FROM pm_history WHERE train_id=? ORDER BY id DESC LIMIT ?"),
            "mileage_log": q("SELECT * FROM mileage_log WHERE train_id=? ORDER BY id DESC LIMIT ?"),
            "rfid_events": q("SELECT * FROM rfid_events WHERE train_id=? ORDER BY id DESC LIMIT ?"),
            "stock_changes": [dict(r) for r in conn.execute(
                "SELECT * FROM stock_changes WHERE withdrawn_train_id=? OR replacement_train_id=?"
                " ORDER BY id DESC LIMIT ?", (train_id, train_id, limit))],
        }


def recent_events(limit=50):
    with db.connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM rfid_events ORDER BY id DESC LIMIT ?", (limit,))]


def devices():
    with db.connect() as conn:
        rows = conn.execute("SELECT * FROM devices WHERE kind <> 'sim' ORDER BY kind, id").fetchall()
        return [{"id": r["id"], "kind": r["kind"], "train_id": r["train_id"], "last_pulses": r["last_pulses"],
                 "online": _is_online(conn, r), "last_seen": r["last_seen"]} for r in rows]


# ---------------------------------------------------------------- actions

def _require_train(conn, train_id):
    if conn.execute("SELECT 1 FROM trains WHERE id=?", (train_id,)).fetchone() is None:
        raise NotFound(f"train {train_id} not found")


def record_pm(train_id, pm_type, technician=None, notes=None):
    if pm_type not in pm.LABEL_TO_CYCLE:
        raise ValueError(f"pm_type must be one of {config.PM_LABELS}")
    with db.connect() as conn:
        _require_train(conn, train_id)
        km = conn.execute("SELECT current_km FROM trains WHERE id=?", (train_id,)).fetchone()[0]
        conn.execute("INSERT INTO pm_history (train_id,pm_type,mileage_at_pm,performed_at,technician,notes)"
                     " VALUES (?,?,?,?,?,?)", (train_id, pm_type, km, db.now_iso(), technician, notes))
        t = _train_dict(conn, train_id)
    emit({"type": "train", "train": t})
    return t


def stock_change(withdrawn, replacement, station=None, reason=None):
    if withdrawn == replacement:
        raise ValueError("withdrawn and replacement must differ")
    with db.connect() as conn:
        _require_train(conn, withdrawn)
        _require_train(conn, replacement)
        loop = conn.execute("SELECT loop FROM trains WHERE id=?", (withdrawn,)).fetchone()[0]
        conn.execute("UPDATE trains SET status='depot', loop=NULL, last_updated=? WHERE id=?",
                     (db.now_iso(), withdrawn))
        conn.execute("UPDATE trains SET status='in-service', loop=?, last_updated=? WHERE id=?",
                     (loop, db.now_iso(), replacement))
        conn.execute("INSERT INTO stock_changes (withdrawn_train_id,replacement_train_id,station,reason,changed_at)"
                     " VALUES (?,?,?,?,?)", (withdrawn, replacement, station, reason, db.now_iso()))
        out = [_train_dict(conn, withdrawn), _train_dict(conn, replacement)]
    for t in out:
        emit({"type": "train", "train": t})
    return out


def assign_tag(tag, train_id):
    tag = normalise_tag(tag)
    with db.connect() as conn:
        _require_train(conn, train_id)
        conn.execute("INSERT INTO tags (tag,train_id,assigned_at) VALUES (?,?,?)"
                     " ON CONFLICT(tag) DO UPDATE SET train_id=excluded.train_id, assigned_at=excluded.assigned_at",
                     (tag, train_id, db.now_iso()))
    return {"tag": tag, "train_id": train_id}


def assign_device(device_id, train_id):
    with db.connect() as conn:
        _require_train(conn, train_id)
        conn.execute("UPDATE devices SET train_id=NULL WHERE train_id=? AND id<>?", (train_id, device_id))
        conn.execute("INSERT INTO devices (id,kind,train_id) VALUES (?,?,?)"
                     " ON CONFLICT(id) DO UPDATE SET train_id=excluded.train_id", (device_id, "lrv", train_id))
    return {"device_id": device_id, "train_id": train_id}


# ---------------------------------------------------------------- demo settings

class Forbidden(Exception):
    pass


def check_source(source):
    """Refuse simulator data when 'accept_simulator' is switched off."""
    if source == "simulator":
        with db.connect() as conn:
            if not db.get_settings(conn).get("accept_simulator", True):
                raise Forbidden("Simulator input is switched off in Demo settings")


def _segments(conn):
    row = conn.execute("SELECT value FROM settings WHERE key='demo_track'").fetchone()
    saved = json.loads(row["value"]) if row else {}
    return [dict(seg, length_m=float(saved.get(f"{seg['from']}>{seg['to']}", seg["length_m"])))
            for seg in config.DEMO_TRACK["segments"]]


def track():
    with db.connect() as conn:
        s = db.get_settings(conn)
        return {"stations": config.STATIONS, "demo_scale": s["demo_scale"], "segments": _segments(conn)}


def update_track(segments):
    """segments: [{"from": "ST1", "to": "ST2", "length_m": 1.25}, ...] - only lengths can change."""
    known = {f"{g['from']}>{g['to']}" for g in config.DEMO_TRACK["segments"]}
    with db.connect() as conn:
        row = conn.execute("SELECT value FROM settings WHERE key='demo_track'").fetchone()
        saved = json.loads(row["value"]) if row else {}
        for seg in segments:
            key = f"{seg.get('from')}>{seg.get('to')}"
            if key not in known:
                raise ValueError(f"unknown segment {key}")
            length = seg.get("length_m")
            if not isinstance(length, (int, float)) or not 0 < length <= 1000:
                raise ValueError(f"length_m for {key} must be between 0 and 1000 m")
            saved[key] = float(length)
        conn.execute("INSERT INTO settings (key,value) VALUES ('demo_track',?)"
                     " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (json.dumps(saved),))
    emit({"type": "track"})
    return track()


_ID_OK = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_")


def _check_id(name, value):
    if not value or len(value) > 24 or set(value) - _ID_OK:
        raise ValueError(f"{name} must be 1-24 letters, digits, - or _")


def demo_trains():
    """Trains linked to an on-board device = the trains running on the demo track."""
    with db.connect() as conn:
        rows = conn.execute("SELECT d.id AS device_id, t.id AS train_id, t.type, t.current_km"
                            " FROM devices d JOIN trains t ON t.id = d.train_id"
                            " WHERE d.kind='lrv' ORDER BY t.id").fetchall()
        out = []
        for r in rows:
            tags = [x["tag"] for x in conn.execute("SELECT tag FROM tags WHERE train_id=?", (r["train_id"],))]
            dev = conn.execute("SELECT * FROM devices WHERE id=?", (r["device_id"],)).fetchone()
            out.append({"train_id": r["train_id"], "type": r["type"], "mileage": round(r["current_km"], 1),
                        "device_id": r["device_id"], "tag": tags[0] if tags else None,
                        "online": _is_online(conn, dev)})
        return out


def save_demo_train(train_id, device_id, tag, mileage=None, ttype=None):
    """Add a train to the demo track, or update its device / tag / mileage."""
    _check_id("train_id", train_id)
    _check_id("device_id", device_id)
    tag = normalise_tag(tag)
    if not tag:
        raise ValueError("tag is required (the UID of the RFID tag on this train)")
    if mileage is not None and (not isinstance(mileage, (int, float)) or mileage < 0 or mileage > 5_000_000):
        raise ValueError("mileage must be between 0 and 5,000,000 km")
    ts = db.now_iso()
    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM trains WHERE id=?", (train_id,)).fetchone()
        if not exists:
            km = float(mileage or 0)
            conn.execute("INSERT INTO trains (id,type,serial,loop,current_km,status,location,location_at,"
                         "km_at_location,last_updated) VALUES (?,?,?,?,?,?,?,?,?,?)",
                         (train_id, ttype or "DEMO", "DEMO-ADDED", "DEMO", km, "depot",
                          config.DEPOT_ID, ts, km, ts))
        else:
            conn.execute("UPDATE trains SET loop='DEMO', type=COALESCE(?, type) WHERE id=?", (ttype, train_id))
            if mileage is not None:
                conn.execute("UPDATE trains SET current_km=?, km_at_location=?, last_updated=? WHERE id=?",
                             (float(mileage), float(mileage), ts, train_id))
                conn.execute("INSERT INTO mileage_log (train_id,km_reading,delta_km,source,recorded_at)"
                             " VALUES (?,?,NULL,'manual',?)", (train_id, float(mileage), ts))
                _drop_future_pm(conn, train_id, float(mileage))
        # one device per train, one train per device
        conn.execute("UPDATE devices SET train_id=NULL WHERE train_id=? AND id<>?", (train_id, device_id))
        conn.execute("INSERT INTO devices (id,kind,train_id) VALUES (?,?,?)"
                     " ON CONFLICT(id) DO UPDATE SET train_id=excluded.train_id, kind='lrv'",
                     (device_id, "lrv", train_id))
        conn.execute("DELETE FROM tags WHERE train_id=? AND tag<>?", (train_id, tag))
        conn.execute("INSERT INTO tags (tag,train_id,assigned_at) VALUES (?,?,?)"
                     " ON CONFLICT(tag) DO UPDATE SET train_id=excluded.train_id, assigned_at=excluded.assigned_at",
                     (tag, train_id, ts))
        t = _train_dict(conn, train_id)
    emit({"type": "train", "train": t})
    return t


def remove_demo_train(train_id):
    """Take a train off the demo track. Trains that were added in Demo settings are deleted."""
    with db.connect() as conn:
        r = conn.execute("SELECT serial FROM trains WHERE id=?", (train_id,)).fetchone()
        if r is None:
            raise NotFound(f"train {train_id} not found")
        conn.execute("DELETE FROM devices WHERE train_id=?", (train_id,))
        conn.execute("DELETE FROM tags WHERE train_id=?", (train_id,))
        if r["serial"] == "DEMO-ADDED":
            for table in ("mileage_log", "rfid_events", "pm_history"):
                conn.execute(f"DELETE FROM {table} WHERE train_id=?", (train_id,))
            conn.execute("DELETE FROM trains WHERE id=?", (train_id,))
            t = None
        else:
            t = _train_dict(conn, train_id)
    emit({"type": "removed", "train_id": train_id})
    if t:
        emit({"type": "train", "train": t})
    return {"removed": train_id}


def get_config():
    with db.connect() as conn:
        return db.get_settings(conn)


def update_config(values):
    allowed = set(config.DEFAULT_SETTINGS)
    bad = set(values) - allowed
    if bad:
        raise ValueError(f"unknown settings: {sorted(bad)}")
    with db.connect() as conn:
        for k, v in values.items():
            if isinstance(config.DEFAULT_SETTINGS[k], bool):
                if not isinstance(v, bool):
                    raise ValueError(f"{k} must be true or false")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or v <= 0:
                raise ValueError(f"{k} must be a positive number")
            conn.execute("INSERT INTO settings (key,value) VALUES (?,?)"
                         " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))
        out = db.get_settings(conn)
    emit({"type": "track"})
    return out
