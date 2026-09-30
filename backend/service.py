"""Core logic shared by MQTT and HTTP ingestion and by the REST API."""
import json
import logging
import math
import threading
import time
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


def _wheel(conn, train_id, s):
    """Wheel circumference for a train: its own calibrated value, else the global setting."""
    if train_id:
        r = conn.execute("SELECT circumference_m FROM train_wheels WHERE train_id=?", (train_id,)).fetchone()
        if r:
            return r["circumference_m"]
    return s["wheel_circumference_m"]


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
            delta_km = delta / s["pulses_per_rev"] * _wheel(conn, train_id, s) * s["demo_scale"] / 1000.0
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


# Teammate's firmware sends the wheel ANGLE in degrees ("292.41") instead of a running count.
# The server unwraps it into a running count here, then treats it exactly like {"pulses": N}.
ANGLE_DEADBAND = 8          # counts (~0.7 deg): ignore jitter while the wheel is still
ANGLE_KEEPALIVE_S = 2.0     # still wheel: refresh "online" at most this often
ANGLE_MIN_GAP_S = 0.2       # moving wheel: write to the database at most 5x per second
_angle = {}                 # device_id -> {"ref": raw, "total": count, "sent": count, "at": time}
_angle_lock = threading.Lock()


def ingest_angle(device_id, degrees, source="mqtt"):
    """Handle one AS5600 angle reading (0-360 deg). The wheel must turn less than half a turn between readings."""
    deg = float(degrees)
    if math.isnan(deg) or deg < 0 or deg > 360.5:
        raise ValueError(f"angle out of range: {degrees}")
    raw = int(round(deg / 360.0 * 4096)) % 4096
    with _angle_lock:
        st = _angle.get(device_id)
        if st is None:
            with db.connect() as conn:          # carry on from the stored count, so a backend restart
                row = conn.execute("SELECT last_pulses FROM devices WHERE id=?", (device_id,)).fetchone()
            start = row["last_pulses"] if row and row["last_pulses"] is not None else 0
            st = _angle[device_id] = {"ref": raw, "total": start, "sent": None, "at": 0.0}
        else:
            d = raw - st["ref"]
            if d > 2048:
                d -= 4096
            elif d < -2048:
                d += 4096
            if abs(d) >= ANGLE_DEADBAND:
                st["total"] += abs(d)           # mileage counts both directions
                st["ref"] = raw
        now = time.monotonic()
        gap = ANGLE_KEEPALIVE_S if st["total"] == st["sent"] else ANGLE_MIN_GAP_S
        if st["sent"] is not None and now - st["at"] < gap:
            return {"device_id": device_id, "angle_raw": raw, "pulses": st["total"], "note": "batched"}
        st["sent"], st["at"] = st["total"], now
        total = st["total"]
    result = ingest_odometer(device_id, total, source)
    result.update({"angle_raw": raw, "pulses": total})
    return result


def flush_angle(device_id):
    """Write any batched wheel count now (before a tag read, so the station distance is exact)."""
    with _angle_lock:
        st = _angle.get(device_id)
        if st is None or st["total"] == st["sent"]:
            return
        st["sent"], st["at"] = st["total"], time.monotonic()
        total = st["total"]
    ingest_odometer(device_id, total)


def ingest_station_topic(name, payload, source="mqtt"):
    """Teammate's firmware: splrt/station/<name>/rfid <card uid>. The topic name says which track marker
    was read (ST1 / ST2 / DEPOT / Dir / ST0m / ST100m). There is no train ID, so the read is credited to
    the train of the device in the 'rfid_train_device' setting.

    If the payload is a registered TRAIN tag, it is the old setup (reader at the station) instead.
    """
    marker = config.STATION_TOPIC_MARKERS.get(name)
    tag = normalise_tag(payload)
    if not tag:
        raise ValueError("empty tag")
    with db.connect() as conn:
        is_train_tag = conn.execute("SELECT 1 FROM tags WHERE tag=?", (tag,)).fetchone() is not None
        device_id = str(db.get_settings(conn).get("rfid_train_device") or "")
    if marker is None or (is_train_tag and marker in config.STATIONS):
        return ingest_rfid(name, tag, source)
    flush_angle(device_id)
    ts = db.now_iso()
    with db.connect() as conn:
        dev = conn.execute("SELECT train_id FROM devices WHERE id=? AND kind='lrv'", (device_id,)).fetchone()
        if dev is None or not dev["train_id"]:
            raise NotFound(f"RFID reads are credited to device '{device_id}', which is not linked to a train"
                           " (Demo settings -> Data sources)")
        train_id = dev["train_id"]
        if marker in ("CAL0", "CAL100"):
            result = _calibration_mark(conn, marker, device_id, train_id, None, ts)
            result.update({"device_id": device_id, "tag": tag, "station_id": marker, "train_id": train_id})
            event = _marker_read(conn, train_id, marker, ts, result.pop("_event", None))
        else:
            result, event = _position_fix(conn, train_id, marker, tag, ts)
            result["device_id"] = device_id
    if event:
        emit(event)
    return result


def _drop_future_pm(conn, train_id, km):
    """After a manual mileage change, PM records above the new mileage can't be right - remove them."""
    conn.execute("DELETE FROM pm_history WHERE train_id=? AND mileage_at_pm > ?", (train_id, km))


def adjust_train(train_id, mileage=None, location=None, wheel_mm=None):
    """Manual correction from the dashboard (double-click). Logged as 'manual'.

    wheel_mm: wheel diameter set by hand (e.g. measured with calipers). Stored like a calibration run
    marked 'manual', so the next 100 m tests average from it.
    """
    if mileage is None and location is None and wheel_mm is None:
        raise ValueError("nothing to change")
    if wheel_mm is not None and (isinstance(wheel_mm, bool) or not isinstance(wheel_mm, (int, float))
                                 or not 1 <= wheel_mm <= 2000):
        raise ValueError("wheel diameter must be between 1 and 2000 mm")
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
            conn.execute("DELETE FROM train_marker WHERE train_id=?", (train_id,))
        if wheel_mm is not None:
            circ = float(wheel_mm) * math.pi / 1000.0
            previous = _wheel(conn, train_id, db.get_settings(conn))
            conn.execute("INSERT INTO train_wheels (train_id,circumference_m,calibrated_at) VALUES (?,?,?)"
                         " ON CONFLICT(train_id) DO UPDATE SET circumference_m=excluded.circumference_m,"
                         " calibrated_at=excluded.calibrated_at", (train_id, circ, ts))
            conn.execute("INSERT INTO calibrations (train_id,counts,turns,measured_m,previous_m,new_m,accepted,reason,"
                         "recorded_at) VALUES (?,0,0,?,?,?,1,'manual',?)", (train_id, circ, previous, circ, ts))
        t = _train_dict(conn, train_id)
    emit({"type": "train", "train": t})
    return t


def _position_fix(conn, train_id, station_id, tag, ts):
    """Exact position fix: `train_id` is at `station_id` now. Returns (result, event)."""
    t = conn.execute("SELECT current_km, km_at_location, location FROM trains WHERE id=?",
                     (train_id,)).fetchone()
    segment = None if t["km_at_location"] is None else t["current_km"] - t["km_at_location"]
    status = "depot" if station_id == config.DEPOT_ID else "in-service"
    # Ignore repeated reads of the same station while the train dwells there
    repeat = t["location"] == station_id and (segment or 0) == 0
    conn.execute("UPDATE trains SET location=?, location_at=?, km_at_location=current_km,"
                 " status=CASE WHEN status='maintenance' THEN status ELSE ? END,"
                 " last_updated=? WHERE id=?", (station_id, ts, status, ts, train_id))
    conn.execute("DELETE FROM train_marker WHERE train_id=?", (train_id,))
    if not repeat:
        conn.execute("INSERT INTO rfid_events (station_id,tag,train_id,km_reading,segment_km,"
                     "recorded_at) VALUES (?,?,?,?,?,?)",
                     (station_id, tag, train_id, t["current_km"], segment, ts))
    result = {"station_id": station_id, "tag": tag, "train_id": train_id,
              "segment_km": None if segment is None else round(segment, 3), "repeat": repeat}
    event = None if repeat else {"type": "position", "train": _train_dict(conn, train_id),
                                 "station_id": station_id, "segment_km": result["segment_km"], "at": ts}
    return result, event


def ingest_rfid(station_id, tag, source="mqtt"):
    """OLD SETUP - reader at the station, tag on the train: the station reports which train tag it saw."""
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
            log.warning("Unknown tag %s at %s - register it in Demo settings", tag, station_id)
            event = {"type": "unknown_tag", "station_id": station_id, "tag": tag, "at": ts}
            result = {"station_id": station_id, "tag": tag, "train_id": None, "note": "unknown tag"}
        else:
            result, event = _position_fix(conn, row["train_id"], station_id, tag, ts)
    if event:
        emit(event)
    return result


def ingest_lrv_rfid(device_id, tag, pulses=None, source="mqtt"):
    """NEW SETUP - reader on the train, tag at the station: the train reports which station tag it passed.

    If the message also carries the wheel count at the moment of the read (`pulses`), that count is
    applied first, so the station fix lines up exactly with the distance travelled.
    """
    tag = normalise_tag(tag)
    if not tag:
        raise ValueError("empty tag")
    if pulses is not None:
        ingest_odometer(device_id, pulses, source)
    elif source != "simulator":
        flush_angle(device_id)
    ts = db.now_iso()
    with db.connect() as conn:
        dev = conn.execute("SELECT train_id FROM devices WHERE id=? AND kind='lrv'", (device_id,)).fetchone()
        if dev is None or not dev["train_id"]:
            raise NotFound(f"device {device_id} is not linked to a train (add it in Demo settings)")
        train_id = dev["train_id"]
        st = conn.execute("SELECT station_id FROM station_tags WHERE tag=?", (tag,)).fetchone()
        if st is None:
            conn.execute("INSERT INTO rfid_events (station_id,tag,train_id,recorded_at) VALUES ('UNKNOWN',?,?,?)",
                         (tag, train_id, ts))
            log.warning("%s read unknown track tag %s - enter it under Track tags in Demo settings",
                        device_id, tag)
            event = {"type": "unknown_station_tag", "device_id": device_id, "tag": tag, "at": ts}
            result = {"device_id": device_id, "tag": tag, "train_id": train_id, "station_id": None,
                      "note": "unknown track tag"}
        elif st["station_id"] in ("CAL0", "CAL100"):
            key = device_id + SIM_SUFFIX if source == "simulator" else device_id
            result = _calibration_mark(conn, st["station_id"], key, train_id, pulses, ts)
            result.update({"device_id": device_id, "tag": tag, "station_id": st["station_id"]})
            event = _marker_read(conn, train_id, st["station_id"], ts, result.pop("_event", None))
        else:                                   # ST1 / ST2 / DEPOT, or BRANCH (heading to the Depot)
            result, event = _position_fix(conn, train_id, st["station_id"], tag, ts)
            result["device_id"] = device_id
    if event:
        emit(event)
    return result


def _marker_read(conn, train_id, marker, ts, event):
    """An in-between track tag (CAL0 / CAL100) was read: the dashboard may now show the train past it."""
    conn.execute("INSERT INTO train_marker (train_id,marker,km,read_at) SELECT id,?,current_km,? FROM trains WHERE id=?"
                  " ON CONFLICT(train_id) DO UPDATE SET marker=excluded.marker, km=excluded.km,"
                  " read_at=excluded.read_at", (marker, ts, train_id))
    t = _train_dict(conn, train_id)
    if event:
        event["train"] = t
        return event
    return {"type": "train", "train": t}


def _calibration_mark(conn, mark, key, train_id, pulses, ts):
    """Wheel calibration: count encoder counts between the 0 m and end tags of the calibration zone.

    circumference = zone length / wheel turns. A run is rejected if it is implausible (too few counts,
    counter reset, or a change larger than cal_max_change_pct from the train's calibrated value).
    The value used is the average of the last 3 accepted runs, so one odd run can't throw it off.
    """
    s = db.get_settings(conn)
    if pulses is None:
        row = conn.execute("SELECT last_pulses FROM devices WHERE id=?", (key,)).fetchone()
        pulses = row["last_pulses"] if row and row["last_pulses"] is not None else None
    if pulses is None:
        return {"calibration": "no wheel count yet"}
    pulses = int(pulses)
    if mark == "CAL0":
        conn.execute("INSERT INTO cal_pending (counter_key,start_pulses,started_at) VALUES (?,?,?)"
                     " ON CONFLICT(counter_key) DO UPDATE SET start_pulses=excluded.start_pulses,"
                     " started_at=excluded.started_at", (key, pulses, ts))
        return {"train_id": train_id, "calibration": "started"}

    pend = conn.execute("SELECT * FROM cal_pending WHERE counter_key=?", (key,)).fetchone()
    conn.execute("DELETE FROM cal_pending WHERE counter_key=?", (key,))
    if pend is None:
        return {"train_id": train_id, "calibration": "ignored - no 0 m mark before this one"}
    age = (datetime.fromisoformat(ts) - datetime.fromisoformat(pend["started_at"])).total_seconds()
    counts = pulses - pend["start_pulses"]
    previous = _wheel(conn, train_id, s)
    has_prior = conn.execute("SELECT 1 FROM train_wheels WHERE train_id=?", (train_id,)).fetchone() is not None
    turns = counts / s["pulses_per_rev"] if counts > 0 else 0.0
    measured = s["cal_distance_m"] / turns if turns > 0 else None
    reason = None
    if age > 300:
        reason = "too long between the 0 m and end tags (over 5 min)"
    elif counts <= 0:
        reason = "wheel count went backwards (encoder restarted?)"
    elif turns < 0.05:
        reason = "too few wheel counts - missed a tag?"
    elif has_prior and abs(measured - previous) / previous * 100 > s["cal_max_change_pct"]:
        reason = (f"change of {(measured - previous) / previous * 100:+.1f}% is more than "
                  f"{s['cal_max_change_pct']}% - wheel slip or a missed tag?")
    accepted = reason is None
    new = previous
    if accepted:
        recent = [r["measured_m"] for r in conn.execute(
            "SELECT measured_m FROM calibrations WHERE train_id=? AND accepted=1 ORDER BY id DESC LIMIT 2",
            (train_id,))]
        new = (measured + sum(recent)) / (1 + len(recent))
        conn.execute("INSERT INTO train_wheels (train_id,circumference_m,calibrated_at) VALUES (?,?,?)"
                     " ON CONFLICT(train_id) DO UPDATE SET circumference_m=excluded.circumference_m,"
                     " calibrated_at=excluded.calibrated_at", (train_id, new, ts))
    conn.execute("INSERT INTO calibrations (train_id,counts,turns,measured_m,previous_m,new_m,accepted,reason,"
                 "recorded_at) VALUES (?,?,?,?,?,?,?,?,?)",
                 (train_id, counts, turns, measured, previous, new, 1 if accepted else 0, reason, ts))
    if accepted:
        log.info("%s wheel calibrated: %.4f m (run %.4f m, was %.4f m)", train_id, new, measured, previous)
    else:
        log.warning("%s calibration rejected: %s", train_id, reason)
    res = {"train_id": train_id, "calibration": "accepted" if accepted else "rejected", "reason": reason,
           "counts": counts, "turns": round(turns, 3),
           "measured_m": None if measured is None else round(measured, 5),
           "previous_m": round(previous, 5), "new_m": round(new, 5)}
    res["_event"] = {"type": "calibration", "train": _train_dict(conn, train_id), **res}
    return res


def calibrations(train_id, limit=20):
    with db.connect() as conn:
        if conn.execute("SELECT 1 FROM trains WHERE id=?", (train_id,)).fetchone() is None:
            raise NotFound(f"train {train_id} not found")
        return [dict(r) for r in conn.execute(
            "SELECT * FROM calibrations WHERE train_id=? ORDER BY id DESC LIMIT ?", (train_id, limit))]


def station_tags():
    with db.connect() as conn:
        rows = {r["station_id"]: r["tag"] for r in conn.execute("SELECT tag, station_id FROM station_tags")}
    return {sid: rows.get(sid) for sid in config.TRACK_TAG_IDS}


def set_station_tags(values):
    """values: {"ST1": "04A3B2C1", ...} - the tag stuck at each station."""
    bad = set(values) - set(config.TRACK_TAG_IDS)
    if bad:
        raise ValueError(f"unknown track tags: {sorted(bad)}")
    clean = {sid: normalise_tag(tag) for sid, tag in values.items()}
    if any(not t for t in clean.values()):
        raise ValueError("tag UID cannot be empty")
    if len(set(clean.values())) != len(clean):
        raise ValueError("each track tag needs a different UID")
    with db.connect() as conn:
        for sid, tag in clean.items():
            if conn.execute("SELECT 1 FROM tags WHERE tag=?", (tag,)).fetchone():
                raise ValueError(f"tag {tag} is already used as a train tag")
            conn.execute("DELETE FROM station_tags WHERE station_id=?", (sid,))
            clash = conn.execute("SELECT station_id FROM station_tags WHERE tag=?", (tag,)).fetchone()
            if clash and clash["station_id"] not in clean:
                raise ValueError(f"tag {tag} is already used for {clash['station_id']}")
            conn.execute("DELETE FROM station_tags WHERE tag=?", (tag,))
            conn.execute("INSERT INTO station_tags (tag,station_id) VALUES (?,?)", (tag, sid))
    return station_tags()


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
    st = db.get_settings(conn)
    worst, cycles = pm.pm_summary(r["current_km"], _pm_rows(conn, train_id),
                                  st["pm_soon_pct"], st["pm_overdue_grace_km"])
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
    m = conn.execute("SELECT marker, km FROM train_marker WHERE train_id=?", (train_id,)).fetchone()
    # last in-between tag read since the station fix, and the encoder distance since it
    d["last_marker"] = None if m is None else {"id": m["marker"],
                                                "since_km": round(max(0.0, r["current_km"] - m["km"]), 4)}
    dev = conn.execute("SELECT id, online, last_seen FROM devices WHERE train_id=?", (train_id,)).fetchone()
    d["device"] = None if dev is None else {"id": dev["id"], "online": _is_online(conn, dev),
                                            "last_seen": dev["last_seen"]}
    d["pm_cycles"] = cycles          # used by the dashboard's PM schedule
    w = conn.execute("SELECT circumference_m, calibrated_at FROM train_wheels WHERE train_id=?", (train_id,)).fetchone()
    d["wheel"] = _wheel_info(conn, train_id)
    if detail:
        d["tags"] = [x["tag"] for x in conn.execute("SELECT tag FROM tags WHERE train_id=?", (train_id,))]
    return d


def _wheel_info(conn, train_id):
    """Wheel size the dashboard uses: measured by the 100 m test / set by hand, else the starting value."""
    w = conn.execute("SELECT circumference_m, calibrated_at FROM train_wheels WHERE train_id=?", (train_id,)).fetchone()
    if w is None:
        return {"circumference_m": db.get_settings(conn)["wheel_circumference_m"], "calibrated_at": None,
                "source": "default"}
    last = conn.execute("SELECT reason FROM calibrations WHERE train_id=? AND accepted=1 ORDER BY id DESC LIMIT 1",
                        (train_id,)).fetchone()
    return {"circumference_m": round(w["circumference_m"], 5), "calibrated_at": w["calibrated_at"],
            "source": "manual" if last and last["reason"] == "manual" else "test"}


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


def set_last_pm(train_id, pm_type, last_pm_km):
    """Set where a PM cycle was last done (dashboard double-click on the PM due mileage).

    The next PM of that level is then due at last_pm_km + cycle. Later records of the same level are
    removed. A later PM of a HIGHER level also counts for this level, so that one has to be changed first.
    """
    if pm_type not in pm.LABEL_TO_CYCLE:
        raise ValueError(f"pm_type must be one of {config.PM_LABELS}")
    if isinstance(last_pm_km, bool) or not isinstance(last_pm_km, (int, float)):
        raise ValueError("last PM mileage must be a number")
    cycle = pm.LABEL_TO_CYCLE[pm_type]
    if last_pm_km < -cycle:
        raise ValueError(f"the {pm_type} PM can't be due below 0 km")
    last_pm_km = float(last_pm_km)
    with db.connect() as conn:
        _require_train(conn, train_id)
        km = conn.execute("SELECT current_km FROM trains WHERE id=?", (train_id,)).fetchone()[0]
        if last_pm_km > km + 1e-6:
            raise ValueError(f"the last {pm_type} PM can't be after the current mileage ({km:,.1f} km), "
                             f"so it can be due at {km + cycle:,.0f} km at the latest")
        higher = [lbl for lbl, c in pm.LABEL_TO_CYCLE.items() if c > cycle]
        if higher:
            r = conn.execute(f"SELECT pm_type, mileage_at_pm FROM pm_history WHERE train_id=? AND mileage_at_pm > ?"
                             f" AND pm_type IN ({','.join('?' * len(higher))}) ORDER BY mileage_at_pm DESC LIMIT 1",
                             (train_id, last_pm_km, *higher)).fetchone()
            if r:
                raise ValueError(f"a {r['pm_type']} PM at {r['mileage_at_pm']:,.0f} km also counts as a {pm_type} PM - "
                                 f"change the {r['pm_type']} PM first")
        conn.execute("DELETE FROM pm_history WHERE train_id=? AND pm_type=? AND mileage_at_pm > ?",
                     (train_id, pm_type, last_pm_km))
        if last_pm_km != 0 or conn.execute("SELECT 1 FROM pm_history WHERE train_id=? AND pm_type=?",
                                           (train_id, pm_type)).fetchone() is None:
            conn.execute("INSERT INTO pm_history (train_id,pm_type,mileage_at_pm,performed_at,technician,notes)"
                         " VALUES (?,?,?,?,NULL,'set from dashboard')", (train_id, pm_type, last_pm_km, db.now_iso()))
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
        return {"stations": config.STATIONS, "markers": config.MARKERS, "demo_scale": s["demo_scale"],
                "cal_distance_m": s["cal_distance_m"], "segments": _segments(conn)}


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
                        "online": _is_online(conn, dev),
                        # wheel size the dashboard uses: measured by the 100 m test, else the starting value
                        "wheel": _wheel_info(conn, r["train_id"])})
        return out


def save_demo_train(train_id, device_id, tag, mileage=None, ttype=None):
    """Add a train to the demo track, or update its device / tag / mileage."""
    _check_id("train_id", train_id)
    _check_id("device_id", device_id)
    tag = normalise_tag(tag or "")        # optional: only for the old reader-at-station setup
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
        if tag:
            if conn.execute("SELECT 1 FROM station_tags WHERE tag=?", (tag,)).fetchone():
                raise ValueError(f"tag {tag} is already used as a station tag")
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


ZERO_OK = {"pm_overdue_grace_km"}      # settings that may be 0
TEXT_SETTINGS = {"rfid_train_device"}  # settings that are text


def update_config(values):
    allowed = set(config.DEFAULT_SETTINGS)
    bad = set(values) - allowed
    if bad:
        raise ValueError(f"unknown settings: {sorted(bad)}")
    with db.connect() as conn:
        for k, v in values.items():
            if k in TEXT_SETTINGS:
                if not isinstance(v, str) or not v.strip():
                    raise ValueError(f"{k} must be a non-empty text")
                v = v.strip()
            elif isinstance(config.DEFAULT_SETTINGS[k], bool):
                if not isinstance(v, bool):
                    raise ValueError(f"{k} must be true or false")
            elif isinstance(v, bool) or not isinstance(v, (int, float)) or v < 0 or (v == 0 and k not in ZERO_OK):
                raise ValueError(f"{k} must be a positive number")
            elif k == "pm_soon_pct" and v > 100:
                raise ValueError("pm_soon_pct must be 100 or less")
            conn.execute("INSERT INTO settings (key,value) VALUES (?,?)"
                         " ON CONFLICT(key) DO UPDATE SET value=excluded.value", (k, json.dumps(v)))
        out = db.get_settings(conn)
    emit({"type": "track"})
    return out
