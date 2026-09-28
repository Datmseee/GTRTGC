"""Pretend to be the demo hardware (2 LRVs + 3 RFID readers) so the backend and dashboard
can be tested before the real ESP32s are ready.

    python simulate_hardware.py                  # MQTT to localhost:1883
    python simulate_hardware.py --broker 192.168.43.10
    python simulate_hardware.py --http http://localhost:8000   # no broker, use HTTP fallback
    python simulate_hardware.py --speed 5        # run 5x faster

Each LRV publishes its cumulative encoder pulse count every second; a station reader
publishes the LRV's tag UID when the LRV arrives there. Same topics/payloads as the real
firmware (see HARDWARE_PROTOCOL.md).
"""
import argparse
import json
import random
import time
import urllib.request

# Toy-track segment lengths in metres (Depot -> Station 1 -> Station 2 -> Station 1 ...)
SEGMENTS = {("DEPOT", "ST1"): 0.8, ("ST1", "ST2"): 1.2, ("ST2", "ST1"): 1.2, ("ST1", "DEPOT"): 0.8}
PULSES_PER_REV = 4096  # AS5600 raw counts per revolution
WHEEL_CIRCUMFERENCE_M = 0.0942
PULSES_PER_M = PULSES_PER_REV / WHEEL_CIRCUMFERENCE_M

LRVS = [
    {"device_id": "LRV01", "tag": "A1B2C3D4", "speed": 0.20, "start_delay": 0},
    {"device_id": "LRV02", "tag": "E5F6A7B8", "speed": 0.17, "start_delay": 4},
]


class Sender:
    def __init__(self, broker=None, port=1883, http=None, root="splrt"):
        self.http, self.root, self.client = http, root, None
        if not http:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"sim-{random.randint(0, 9999)}")
            self.client.connect(broker, port, keepalive=30)
            self.client.loop_start()

    def odometer(self, device_id, pulses):
        if self.client:
            self.client.publish(f"{self.root}/lrv/{device_id}/odometer", json.dumps({"pulses": pulses}), qos=0)
        else:
            self._post("/api/ingest/odometer", {"device_id": device_id, "pulses": pulses})

    def rfid(self, station_id, tag):
        if self.client:
            self.client.publish(f"{self.root}/station/{station_id}/rfid", json.dumps({"tag": tag}), qos=1)
        else:
            self._post("/api/ingest/rfid", {"station_id": station_id, "tag": tag})

    def status(self, kind, device_id, online):
        if self.client:
            self.client.publish(f"{self.root}/{kind}/{device_id}/status",
                                "online" if online else "offline", qos=1, retain=True)

    def _post(self, path, body):
        req = urllib.request.Request(self.http.rstrip("/") + path, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"}, method="POST")
        urllib.request.urlopen(req, timeout=5).read()


class SimLrv:
    def __init__(self, spec):
        self.__dict__.update(spec)
        self.at, self.next = "DEPOT", "ST1"
        self.progress_m, self.pulses_exact, self.dwell = 0.0, 0.0, spec["start_delay"]
        self.laps = 0

    def step(self, dt, sender):
        if self.dwell > 0:
            self.dwell -= dt
            return
        seg = SEGMENTS[(self.at, self.next)]
        move = self.speed * dt
        self.progress_m += move
        self.pulses_exact += move * PULSES_PER_M * random.uniform(0.98, 1.02)  # wheel slip noise
        if self.progress_m >= seg:
            self.at, self.progress_m = self.next, 0.0  # (dwell absorbs overshoot)
            sender.rfid(self.at, self.tag)
            print(f"  {self.device_id} arrived at {self.at}  (pulses={int(self.pulses_exact)})")
            self.dwell = 3.0 if self.at != "DEPOT" else 8.0
            if self.at == "DEPOT":
                self.next = "ST1"
            elif self.at == "ST1":
                self.laps += 1
                self.next = "DEPOT" if self.laps % 4 == 0 else "ST2"   # visit depot every 4 laps
            else:
                self.next = "ST1"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--broker", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--http", default=None, help="use HTTP fallback, e.g. http://localhost:8000")
    ap.add_argument("--speed", type=float, default=1.0, help="time multiplier")
    ap.add_argument("--duration", type=float, default=0, help="stop after N seconds (0 = forever)")
    args = ap.parse_args()

    sender = Sender(args.broker, args.port, args.http)
    lrvs = [SimLrv(s) for s in LRVS]
    for s in ("ST1", "ST2", "DEPOT"):
        sender.status("station", s, True)
    for lrv in lrvs:
        sender.status("lrv", lrv.device_id, True)
        sender.rfid("DEPOT", lrv.tag)
    print(f"Simulating {len(lrvs)} LRVs via {'HTTP ' + args.http if args.http else 'MQTT ' + args.broker}."
          " Ctrl+C to stop.")

    dt, last_report, start = 0.25, 0.0, time.time()
    try:
        while True:
            for lrv in lrvs:
                lrv.step(dt * args.speed, sender)
            now = time.time()
            if now - last_report >= 1.0:
                for lrv in lrvs:
                    sender.odometer(lrv.device_id, int(lrv.pulses_exact))
                last_report = now
            if args.duration and now - start >= args.duration:
                break
            time.sleep(dt)
    except KeyboardInterrupt:
        pass
    finally:
        for lrv in lrvs:
            sender.odometer(lrv.device_id, int(lrv.pulses_exact))
            sender.status("lrv", lrv.device_id, False)
        if sender.client:
            time.sleep(0.3)
            sender.client.loop_stop()


if __name__ == "__main__":
    main()
