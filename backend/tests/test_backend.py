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
    r = mqtt_bridge.handle_message("splrt/lrv/LRV02/odometer", b"60")   # plain number also accepted
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
    assert {s["from"] for s in tr["segments"]} == {"ST1", "ST2", "DEPOT"} and tr["demo_scale"] > 0
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
