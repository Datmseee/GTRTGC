"""Run from the backend folder:  python -m pytest -q"""
import os
import sys
import tempfile

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MQTT_ENABLED"] = "false"

import config  # noqa: E402


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    monkeypatch.setattr(config, "DB_PATH", os.path.join(tmp, "test.db"))
    monkeypatch.setattr(config, "MQTT_ENABLED", False)
    from fastapi.testclient import TestClient
    import main
    import service
    service._angle.clear()
    with TestClient(main.app) as c:
        yield c


def km_per_pulse():
    s = config.DEFAULT_SETTINGS
    return s["wheel_circumference_m"] * s["demo_scale"] / s["pulses_per_rev"] / 1000


def test_seed_matches_dashboard_fleet(client):
    fleet = client.get("/api/fleet").json()
    assert len(fleet) == 59
    assert sum(t["type"] == "C810" for t in fleet) == 20
    assert sum(t["type"] == "C810A" for t in fleet) == 32
    assert sum(t["type"] == "C810D" for t in fleet) == 7
    assert {"810-001", "810A-032", "810D-007"} <= {t["id"] for t in fleet}
    # forced scenarios: 40100 km -> just past 40K -> overdue ; 39800 -> soon
    by_id = {t["id"]: t for t in fleet}
    assert by_id[fleet[9]["id"]]["pm"]["status"] == "over"
    assert by_id[fleet[2]["id"]]["pm"]["status"] == "soon"


def test_odometer_cumulative_and_reset(client):
    start = client.get("/api/trains/810D-001").json()["mileage"]
    post = lambda p: client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": p}).json()
    assert post(100)["delta_pulses"] == 0          # first message = baseline
    assert post(300)["delta_pulses"] == 200
    assert post(300)["delta_pulses"] == 0          # duplicate / idle
    assert post(50)["delta_pulses"] == 50          # MCU rebooted -> counts from zero
    t = client.get("/api/trains/810D-001").json()
    assert t["mileage"] == pytest.approx(start + 250 * km_per_pulse(), abs=0.1)


def test_rfid_position_and_segment(client):
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    r = client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "a1 b2 c3 d4"}).json()
    assert r["train_id"] == "810D-001"
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 1000})
    r = client.post("/api/ingest/rfid", json={"station_id": "ST2", "tag": "A1B2C3D4"}).json()
    assert r["segment_km"] == pytest.approx(1000 * km_per_pulse(), abs=0.01)
    r2 = client.post("/api/ingest/rfid", json={"station_id": "ST2", "tag": "A1B2C3D4"}).json()
    assert r2["repeat"] is True
    t = client.get("/api/trains/810D-001").json()
    assert t["location"] == "ST2" and t["status"] == "in-service"
    client.post("/api/ingest/rfid", json={"station_id": "DEPOT", "tag": "A1B2C3D4"})
    assert client.get("/api/trains/810D-001").json()["status"] == "depot"


def test_unknown_tag_then_register(client):
    r = client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "DEADBEEF"}).json()
    assert r["train_id"] is None
    assert client.get("/api/events").json()[0]["tag"] == "DEADBEEF"
    client.post("/api/tags", json={"tag": "DEADBEEF", "train_id": "810A-001"})
    r = client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "DEADBEEF"}).json()
    assert r["train_id"] == "810A-001"


def test_pm_record_clears_alert(client):
    overdue = [a for a in client.get("/api/alerts").json() if a["level"] == "over"]
    assert overdue
    a = overdue[0]
    label = a["pm"].split()[0]
    t = client.post("/api/pm", json={"train_id": a["train_id"], "pm_type": label, "technician": "Test"}).json()
    assert t["pm"]["status"] != "over" or t["pm"]["name"] != a["pm"]
    hist = client.get(f"/api/history/{a['train_id']}").json()
    assert hist["pm_history"][0]["technician"] == "Test"
    assert client.post("/api/pm", json={"train_id": a["train_id"], "pm_type": "5K"}).status_code == 400


def test_stock_change(client):
    fleet = client.get("/api/fleet").json()
    svc = next(t for t in fleet if t["status"] == "in-service")
    dep = next(t for t in fleet if t["status"] == "depot" and t["loop"] is None)
    out = client.post("/api/stockchange", json={"withdrawn_train_id": svc["id"],
                                                "replacement_train_id": dep["id"], "reason": "door fault"}).json()
    assert out[0]["status"] == "depot" and out[1]["status"] == "in-service"
    assert out[1]["loop"] == svc["loop"]


def test_config_calibration(client):
    c = client.put("/api/config", json={"pulses_per_rev": 40}).json()
    assert c["pulses_per_rev"] == 40
    assert client.put("/api/config", json={"bogus": 1}).status_code == 400
    assert client.put("/api/config", json={"demo_scale": -1}).status_code == 400


def test_mqtt_routing(client):
    import mqtt_bridge
    r = mqtt_bridge.handle_message("splrt/lrv/LRV02/odometer", b'{"pulses": 10}')
    assert r["device_id"] == "LRV02"
    r = mqtt_bridge.handle_message("splrt/lrv/LRV02/odometer", b'{"pulses": 60}')
    assert r["delta_pulses"] == 50
    r = mqtt_bridge.handle_message("splrt/station/ST1/rfid", b"E5F6A7B8")
    assert r["train_id"] == "810D-002"
    mqtt_bridge.handle_message("splrt/station/ST1/status", b"offline")
    devs = {d["id"]: d for d in client.get("/api/devices").json()}
    assert devs["ST1"]["online"] is False and devs["ST1"]["kind"] == "station"
    assert mqtt_bridge.handle_message("other/topic/x/y", b"1") is None


def test_websocket_receives_updates(client):
    with client.websocket_connect("/ws") as ws:
        assert ws.receive_json()["type"] == "hello"
        client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
        client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 500})
        msg = ws.receive_json()
        assert msg["type"] == "train" and msg["train"]["id"] == "810D-001"


def test_serves_dashboard_and_cycles(client):
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    t = client.get("/api/fleet").json()[0]
    assert len(t["pm_cycles"]) == 5 and "last_pm_km" in t["pm_cycles"][0]


def test_worst_pm_prefers_bigger_cycle_on_tie():
    import pm
    worst, _ = pm.pm_summary(120379, [("40K", 80000), ("13K", 117000), ("2K", 118000)])
    assert worst["name"] == "120K PM" and worst["status"] == "over"


def test_root_redirect_keeps_query(client):
    r = client.get("/?mode=demo", follow_redirects=False)
    assert r.headers["location"] == "/First_Dashboard.html?mode=demo"


def test_serves_simulator(client):
    r = client.get("/simulator")
    assert r.status_code == 200 and "HARDWARE SIMULATOR" in r.text


def test_track_and_since_station(client):
    tr = client.get("/api/track").json()
    assert {s["from"] for s in tr["segments"]} == {"ST1", "ST2", "DEPOT", "BRANCH"} and tr["demo_scale"] > 0
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "A1B2C3D4"})
    assert client.get("/api/trains/810D-001").json()["since_station_km"] == 0
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 4096})
    t = client.get("/api/trains/810D-001").json()
    assert t["since_station_km"] == pytest.approx(km_per_pulse() * 4096, abs=1e-3)


def test_demo_settings_add_edit_remove_train(client):
    assert {t["train_id"] for t in client.get("/api/demo/trains").json()} == {"810D-001", "810D-002"}
    # add a brand-new train
    r = client.post("/api/demo/trains", json={"train_id": "LRV-003", "device_id": "LRV03",
                                               "tag": "11:22:aa:bb", "mileage": 1990})
    assert r.status_code == 200 and r.json()["mileage"] == 1990 and r.json()["location"] == "DEPOT"
    client.post("/api/ingest/odometer", json={"device_id": "LRV03", "pulses": 0})
    client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "1122AABB"})
    assert client.get("/api/trains/LRV-003").json()["location"] == "ST1"
    assert len(client.get("/api/fleet").json()) == 60
    # edit: new tag + mileage override
    client.post("/api/demo/trains", json={"train_id": "LRV-003", "device_id": "LRV03", "tag": "CAFE0001",
                                          "mileage": 2100})
    t = client.get("/api/trains/LRV-003").json()
    assert t["tags"] == ["CAFE0001"] and t["mileage"] == 2100 and t["since_station_km"] == 0
    assert client.get("/api/history/LRV-003").json()["mileage_log"][0]["source"] == "manual"
    # remove: added train is deleted, seeded train only unlinked
    client.delete("/api/demo/trains/LRV-003")
    assert client.get("/api/trains/LRV-003").status_code == 404
    client.delete("/api/demo/trains/810D-002")
    assert client.get("/api/trains/810D-002").status_code == 200
    assert {t["train_id"] for t in client.get("/api/demo/trains").json()} == {"810D-001"}
    assert client.post("/api/demo/trains", json={"train_id": "bad id!", "device_id": "X", "tag": "AA"}).status_code == 400


def test_track_lengths_editable(client):
    r = client.put("/api/track", json={"segments": [{"from": "ST1", "to": "ST2", "length_m": 1.75}]})
    segs = {(s["from"], s["to"]): s["length_m"] for s in r.json()["segments"]}
    assert segs[("ST1", "ST2")] == 1.75 and segs[("ST2", "ST1")] == 1.2
    assert client.put("/api/track", json={"segments": [{"from": "ST1", "to": "X", "length_m": 1}]}).status_code == 400
    assert client.put("/api/track", json={"segments": [{"from": "ST1", "to": "ST2", "length_m": 0}]}).status_code == 400
    assert "demo_track" not in client.get("/api/config").json()


def test_simulator_switch(client):
    body = {"device_id": "LRV01", "pulses": 10, "source": "simulator"}
    assert client.post("/api/ingest/odometer", json=body).status_code == 200
    assert client.put("/api/config", json={"accept_simulator": False}).json()["accept_simulator"] is False
    assert client.post("/api/ingest/odometer", json=body).status_code == 403
    assert client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "A1B2C3D4",
                                                 "source": "simulator"}).status_code == 403
    # real hardware (HTTP fallback / MQTT) still accepted
    assert client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 20}).status_code == 200
    assert client.put("/api/config", json={"accept_simulator": 1}).status_code == 400
    assert client.put("/api/config", json={"demo_scale": True}).status_code == 400


def test_hardware_and_simulator_together(client):
    km0 = client.get("/api/trains/810D-001").json()["mileage"]
    hw = lambda p: client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": p})
    sim = lambda p: client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": p,
                                                              "source": "simulator"})
    hw(50000); sim(0)            # both "power on" with very different running totals
    hw(54096); sim(4096)         # each turns the wheel once
    hw(58192); sim(8192)         # ...and once more
    km = client.get("/api/trains/810D-001").json()["mileage"]
    assert km == pytest.approx(km0 + 4 * 4096 * km_per_pulse(), abs=0.1)   # 4 turns in total, no corruption
    assert all(d["kind"] != "sim" for d in client.get("/api/devices").json())
    assert client.post("/api/ingest/odometer", json={"device_id": "NOPE", "pulses": 1,
                                                     "source": "simulator"}).status_code == 404


def test_manual_adjust(client):
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    client.post("/api/ingest/rfid", json={"station_id": "ST1", "tag": "A1B2C3D4"})
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 4096})
    since = client.get("/api/trains/810D-001").json()["since_station_km"]
    t = client.patch("/api/trains/810D-001", json={"mileage": 1995}).json()
    assert t["mileage"] == 1995 and t["since_station_km"] == pytest.approx(since, abs=1e-3)
    t = client.patch("/api/trains/810D-001", json={"location": "ST2"}).json()
    assert t["location"] == "ST2" and t["since_station_km"] == 0 and t["status"] == "in-service"
    assert client.get("/api/events?limit=1").json()[0]["tag"] == "MANUAL"
    assert client.patch("/api/trains/810D-001", json={"location": "X"}).status_code == 400
    assert client.patch("/api/trains/810D-001", json={}).status_code == 400
    assert client.patch("/api/trains/NOPE", json={"mileage": 1}).status_code == 404


def test_manual_mileage_drops_impossible_pm_records(client):
    t = client.patch("/api/trains/810D-001", json={"mileage": 1950}).json()
    assert t["pm"]["name"] == "2K PM" and t["pm"]["status"] == "soon" and t["pm"]["remaining"] == 50
    assert all(p["mileage_at_pm"] <= 1950 for p in client.get("/api/history/810D-001").json()["pm_history"])


def test_train_mounted_reader_with_station_tags(client):
    tags = client.get("/api/station_tags").json()
    assert set(tags) == {"ST1", "ST2", "DEPOT", "BRANCH", "CAL0", "CAL100"}
    # enter the real UIDs of the tags stuck at the stations
    tags = client.put("/api/station_tags", json={"ST1": "11:22:33:44", "ST2": "55667788", "DEPOT": "99aabbcc"}).json()
    assert {k: tags[k] for k in ("ST1", "ST2", "DEPOT")} == {"ST1": "11223344", "ST2": "55667788", "DEPOT": "99AABBCC"}
    km0 = client.get("/api/trains/810D-001").json()["mileage"]
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    r = client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV01", "tag": "11223344"}).json()
    assert r["train_id"] == "810D-001" and r["station_id"] == "ST1"
    # read at ST2 carries the wheel count at that moment -> applied first, exact segment
    r = client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV01", "tag": "55667788", "pulses": 8192}).json()
    assert r["station_id"] == "ST2" and r["segment_km"] == pytest.approx(8192 * km_per_pulse(), abs=1e-3)
    t = client.get("/api/trains/810D-001").json()
    assert t["location"] == "ST2" and t["mileage"] == pytest.approx(km0 + 8192 * km_per_pulse(), abs=0.1)
    # unknown station tag is reported, not a crash
    r = client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV01", "tag": "DEADBEEF"}).json()
    assert r["station_id"] is None
    # validation
    assert client.put("/api/station_tags", json={"ST1": "AA", "ST2": "AA"}).status_code == 400
    assert client.put("/api/station_tags", json={"ST9": "AA"}).status_code == 400
    assert client.put("/api/station_tags", json={"ST1": "A1B2C3D4"}).status_code == 400   # a train's tag
    assert client.post("/api/ingest/lrv_rfid", json={"device_id": "NOPE", "tag": "11223344"}).status_code == 404


def test_mqtt_train_rfid_and_simulator(client):
    import mqtt_bridge
    mqtt_bridge.handle_message("splrt/lrv/LRV02/odometer", b'{"pulses": 100}')
    r = mqtt_bridge.handle_message("splrt/lrv/LRV02/rfid", b'{"tag": "5A000003", "pulses": 4196}')
    assert r["station_id"] == "DEPOT" and r["segment_km"] == pytest.approx(4096 * km_per_pulse(), abs=1e-3)
    r = mqtt_bridge.handle_message("splrt/lrv/LRV02/rfid", b"5A000001")     # plain UID also accepted
    assert r["station_id"] == "ST1"
    # simulator page uses the same endpoint with its own wheel counter
    client.post("/api/ingest/odometer", json={"device_id": "LRV02", "pulses": 0, "source": "simulator"})
    r = client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV02", "tag": "5A000002", "pulses": 4096,
                                                  "source": "simulator"}).json()
    assert r["station_id"] == "ST2" and r["segment_km"] == pytest.approx(4096 * km_per_pulse(), abs=1e-3)


def test_demo_train_without_train_tag(client):
    r = client.post("/api/demo/trains", json={"train_id": "LRV-009", "device_id": "LRV09"})
    assert r.status_code == 200
    assert next(t for t in client.get("/api/demo/trains").json() if t["train_id"] == "LRV-009")["tag"] is None


def _lrv(client, tag, pulses, dev="LRV01"):
    return client.post("/api/ingest/lrv_rfid", json={"device_id": dev, "tag": tag, "pulses": pulses}).json()


def test_branch_tag_sends_train_towards_depot(client):
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    assert _lrv(client, "5A000002", 0)["station_id"] == "ST2"
    r = _lrv(client, "5A000004", 8192)                       # green tag just after the switch
    assert r["station_id"] == "BRANCH"
    t = client.get("/api/trains/810D-001").json()
    assert t["location"] == "BRANCH" and t["status"] == "in-service" and t["since_station_km"] == 0
    segs = {s["from"]: s for s in client.get("/api/track").json()["segments"]}
    assert segs["BRANCH"]["to"] == "DEPOT"
    assert _lrv(client, "5A000003", 12288)["station_id"] == "DEPOT"
    assert client.get("/api/trains/810D-001").json()["status"] == "depot"


def test_wheel_calibration_zone(client):
    s = client.get("/api/config").json()
    zone, ppr, nominal = s["cal_distance_m"], s["pulses_per_rev"], s["wheel_circumference_m"]
    true_c = 0.0930                                           # the real (worn) wheel is a bit smaller
    counts = round(zone / true_c * ppr)
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    assert _lrv(client, "5A000005", 1000)["calibration"] == "started"      # yellow 0 m
    r = _lrv(client, "5A000006", 1000 + counts)                            # red end
    assert r["calibration"] == "accepted" and r["new_m"] == pytest.approx(true_c, abs=1e-4)
    t = client.get("/api/trains/810D-001").json()
    assert t["wheel"]["circumference_m"] == pytest.approx(true_c, abs=1e-4) and t["wheel"]["calibrated_at"]
    assert t["location"] != "CAL100"                                        # calibration tags don't move the train
    # the new wheel size is used for mileage from now on
    km0 = t["mileage"]
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 1000 + counts + 40960})
    km1 = client.get("/api/trains/810D-001").json()["mileage"]
    assert km1 - km0 == pytest.approx(10 * true_c * s["demo_scale"] / 1000, abs=0.1)
    # other trains keep the global value
    assert client.get("/api/trains/810D-002").json()["wheel"]["circumference_m"] == nominal
    # an implausible run (+50%) is rejected and does not change the wheel
    base = 1000 + counts + 40960
    _lrv(client, "5A000005", base)
    r = _lrv(client, "5A000006", base + round(counts / 1.5))
    assert r["calibration"] == "rejected" and "more than" in r["reason"]
    assert client.get("/api/trains/810D-001").json()["wheel"]["circumference_m"] == pytest.approx(true_c, abs=1e-4)
    # end tag without a start tag is ignored; history is kept
    assert "ignored" in _lrv(client, "5A000006", base + 99999)["calibration"]
    hist = client.get("/api/calibrations/810D-001").json()
    assert [h["accepted"] for h in hist] == [0, 1]
    # average of recent good runs
    b2 = base + 200000
    _lrv(client, "5A000005", b2); r = _lrv(client, "5A000006", b2 + round(zone / 0.0920 * ppr))
    assert r["calibration"] == "accepted" and r["new_m"] == pytest.approx((0.0930 + 0.0920) / 2, abs=2e-4)


def test_pm_alert_settings(client):
    client.patch("/api/trains/810D-001", json={"mileage": 1900})            # 100 km before the 2K PM
    assert client.get("/api/trains/810D-001").json()["pm"]["status"] == "soon"      # 5% left < 8% default
    client.put("/api/config", json={"pm_soon_pct": 4})
    assert client.get("/api/trains/810D-001").json()["pm"]["status"] == "ok"        # 5% left > 4%
    client.patch("/api/trains/810D-001", json={"mileage": 2030})             # 30 km past the 2K PM
    assert client.get("/api/trains/810D-001").json()["pm"]["status"] == "over"      # grace 0 km default
    client.put("/api/config", json={"pm_overdue_grace_km": 50})
    t = client.get("/api/trains/810D-001").json()
    assert t["pm"]["status"] == "soon" and t["pm"]["remaining"] == -30               # within grace: due, amber
    client.patch("/api/trains/810D-001", json={"mileage": 2060})
    assert client.get("/api/trains/810D-001").json()["pm"]["status"] == "over"      # beyond the grace
    assert client.put("/api/config", json={"pm_overdue_grace_km": 0}).status_code == 200
    assert client.put("/api/config", json={"pm_soon_pct": 0}).status_code == 400
    assert client.put("/api/config", json={"pm_soon_pct": 150}).status_code == 400


@pytest.fixture(autouse=True)
def _no_angle_batching(monkeypatch):
    import service
    monkeypatch.setattr(service, "ANGLE_MIN_GAP_S", 0.0)


def test_teammate_angle_payload_unwraps(client):
    """splrt/lrv/LRV01/odometer "292.41": angle in degrees, unwrapped into a running count on the server."""
    import mqtt_bridge
    import service
    send = lambda deg: mqtt_bridge.handle_message("splrt/lrv/LRV01/odometer", f"{deg:.2f}".encode())
    send(350.0)                                   # first reading = starting point
    for deg in (0.0, 10.0, 20.0, 20.1, 20.0):     # across the 359 -> 0 wrap, then jitter
        send(deg)
    total = service._angle["LRV01"]["total"]
    assert abs(total - round(30 / 360 * 4096)) <= 2
    for turn in range(4):                         # 1 full turn forwards in 90 deg steps
        send((20.0 + 90 * (turn + 1)) % 360)
    service._angle["LRV01"]["at"] = 0             # skip the keep-alive throttle
    r = send(20.0)
    t = client.get("/api/trains/810D-001").json()
    pulses = service._angle["LRV01"]["total"]
    assert abs(pulses - round(390 / 360 * 4096)) <= 3
    assert abs(t["session_km"] - pulses * km_per_pulse()) < 1e-3
    r = mqtt_bridge.handle_message("splrt/lrv/LRV01/odometer", b"20.00")   # still: throttled, no DB write
    assert r["note"] == "batched"


def test_teammate_station_topics(client):
    """splrt/station/<ST1|ST2|DEPOT|Dir|ST0m|ST100m>/rfid <uid>: credited to the rfid_train_device train."""
    import mqtt_bridge
    import service
    rf = lambda name, uid: mqtt_bridge.handle_message(f"splrt/station/{name}/rfid", uid.encode())
    send = lambda deg: mqtt_bridge.handle_message("splrt/lrv/LRV01/odometer", f"{deg:.2f}".encode())
    r = rf("ST1", "84A7FCD7")
    assert r["train_id"] == "810D-001" and r["station_id"] == "ST1"
    r = rf("Dir", "DEPOT")
    assert client.get("/api/trains/810D-001").json()["location"] == "BRANCH"
    rf("DEPOT", "5F48F0D7")
    assert client.get("/api/trains/810D-001").json()["location"] == "DEPOT"
    # calibration: 0 m tag, 1 wheel turn, 100 m tag -> circumference = 0.1 m / 1 turn
    send(0.0)
    r = rf("ST0m", "6D85EFD7")
    assert r["calibration"] == "started"
    for deg in (90, 180, 270, 0):
        send(float(deg))
    service._angle["LRV01"]["at"] = 0
    send(0.0)
    r = rf("ST100m", "8EC201D8")
    assert r["calibration"] == "accepted" and abs(r["measured_m"] - 0.1) < 0.002
    assert abs(client.get("/api/trains/810D-001").json()["wheel"]["circumference_m"] - r["new_m"]) < 1e-6
    # credit reads to LRV02 instead
    assert client.put("/api/config", json={"rfid_train_device": "LRV02"}).status_code == 200
    assert rf("ST2", "0396F313")["train_id"] == "810D-002"
    assert client.put("/api/config", json={"rfid_train_device": ""}).status_code == 400
    # an unlinked device gives a clear error instead of moving the wrong train
    client.put("/api/config", json={"rfid_train_device": "LRV09"})
    with pytest.raises(service.NotFound):
        rf("ST1", "84A7FCD7")
    # old setup still works: a registered TRAIN tag on a station topic
    assert rf("ST1", "E5F6A7B8")["train_id"] == "810D-002"


def test_demo_trains_report_measured_wheel(client):
    w = {t["device_id"]: t["wheel"] for t in client.get("/api/demo/trains").json()}
    assert w["LRV01"]["calibrated_at"] is None
    assert w["LRV01"]["circumference_m"] == config.DEFAULT_SETTINGS["wheel_circumference_m"]


def test_wheel_set_by_hand_then_test_averages(client):
    r = client.patch("/api/trains/810D-001", json={"wheel_mm": 29.0})
    assert r.status_code == 200 and r.json()["wheel"]["source"] == "manual"
    assert abs(r.json()["wheel"]["circumference_m"] - 29.0 * 3.14159265 / 1000) < 1e-5
    assert client.patch("/api/trains/810D-001", json={"wheel_mm": 0}).status_code == 400
    # a 100 m test afterwards is averaged with the hand-set value and marked as a test
    client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV01", "tag": "5A000005", "pulses": 0})
    client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV01", "tag": "5A000006", "pulses": 4520})
    w = client.get("/api/trains/810D-001").json()["wheel"]
    assert w["source"] == "test"


def test_last_marker_only_after_tag_read(client):
    ing = lambda tag, n: client.post("/api/ingest/lrv_rfid", json={"device_id": "LRV01", "tag": tag, "pulses": n})
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 0})
    ing("5A000003", 0)                                        # DEPOT
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 3000})
    assert client.get("/api/trains/810D-001").json()["last_marker"] is None   # moved, but no tag read
    ing("5A000005", 3000)                                     # CAL0
    client.post("/api/ingest/odometer", json={"device_id": "LRV01", "pulses": 4000})
    m = client.get("/api/trains/810D-001").json()["last_marker"]
    assert m["id"] == "CAL0" and abs(m["since_km"] - 1000 * km_per_pulse()) < 1e-3
    ing("5A000001", 9000)                                     # ST1 clears it
    assert client.get("/api/trains/810D-001").json()["last_marker"] is None


def test_set_last_pm_moves_due_point(client):
    r = client.put("/api/pm/last", json={"train_id": "810D-001", "pm_type": "2K", "last_pm_km": 99600})
    assert r.status_code == 200, r.text
    c2k = r.json()["pm_cycles"][0]
    assert c2k["due_at"] == 101600 and c2k["status"] == "soon"       # 101,526 km: 74 km left < 8% (160 km)
    # can't be after the current mileage
    assert client.put("/api/pm/last", json={"train_id": "810D-001", "pm_type": "2K", "last_pm_km": 200000}).status_code == 400
    # a later higher-level PM also counts for 2K
    client.put("/api/pm/last", json={"train_id": "810D-001", "pm_type": "13K", "last_pm_km": 99900})
    r = client.put("/api/pm/last", json={"train_id": "810D-001", "pm_type": "2K", "last_pm_km": 99000})
    assert r.status_code == 400 and "13K" in r.json()["detail"]


def test_low_mileage_train_can_be_made_due_soon(client):
    """Demo: a train at 15 km, first 2K check set to 100 km away -> amber (under 160 km)."""
    client.patch("/api/trains/810D-001", json={"mileage": 15.1})
    r = client.put("/api/pm/last", json={"train_id": "810D-001", "pm_type": "2K", "last_pm_km": 15.1 + 100 - 2000})
    assert r.status_code == 200, r.text
    c = r.json()["pm_cycles"][0]
    assert abs(c["due_at"] - 115.1) < 0.1 and c["status"] == "soon"
    assert client.put("/api/pm/last", json={"train_id": "810D-001", "pm_type": "2K", "last_pm_km": -2500}).status_code == 400
