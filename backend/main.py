"""SPLRT Fleet backend - FastAPI + MQTT + SQLite.

Run:   python main.py            (dashboard at http://localhost:8000/ , API docs at /docs)
       python main.py --port 5500 --no-mqtt
"""
import argparse
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from typing import Optional

from fastapi import FastAPI, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel, Field

import config
import db
import service

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(name)s: %(message)s")
log = logging.getLogger("splrt")


# ---------------------------------------------------------------- WebSocket hub

class Hub:
    """Pushes every service event to connected dashboards. Safe to call from any thread."""

    def __init__(self):
        self.clients = set()
        self.loop = None

    async def _send_all(self, text):
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                self.clients.discard(ws)

    def publish(self, event):
        if self.loop is None or not self.clients:
            return
        text = json.dumps(event)
        try:
            running = asyncio.get_running_loop()
        except RuntimeError:
            running = None
        if running is self.loop:
            self.loop.create_task(self._send_all(text))
        else:
            asyncio.run_coroutine_threadsafe(self._send_all(text), self.loop)


hub = Hub()
service.on_event(hub.publish)
bridge = None


@asynccontextmanager
async def lifespan(app):
    global bridge
    db.init_db()
    hub.loop = asyncio.get_running_loop()
    if config.MQTT_ENABLED:
        from mqtt_bridge import MqttBridge
        bridge = MqttBridge(config.MQTT_HOST, config.MQTT_PORT)
        bridge.start()
    else:
        log.info("MQTT disabled - HTTP ingestion only")
    yield
    if bridge:
        bridge.stop()


app = FastAPI(title="SPLRT Fleet Backend", version="0.1.0", lifespan=lifespan)
# The dashboard may be opened from file:// or another port, so allow any origin.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def _wrap(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except service.NotFound as e:
        raise HTTPException(404, str(e))
    except service.Forbidden as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))


# ---------------------------------------------------------------- models

class OdometerIn(BaseModel):
    device_id: str = Field(examples=["LRV01"])
    pulses: int = Field(ge=0, examples=[15230])
    source: str = Field("http", description='"simulator" for the simulator page')


class RfidIn(BaseModel):
    station_id: str = Field(examples=["ST1"])
    tag: str = Field(examples=["A1B2C3D4"])
    source: str = Field("http", description='"simulator" for the simulator page')


class DemoTrainIn(BaseModel):
    train_id: str = Field(examples=["LRV-003"])
    device_id: str = Field(examples=["LRV03"])
    tag: str = Field(examples=["04A3B2C1"])
    mileage: Optional[float] = Field(None, description="set / override the mileage (km)")
    type: Optional[str] = None


class TrackIn(BaseModel):
    segments: list


class PmIn(BaseModel):
    train_id: str
    pm_type: str = Field(examples=["2K"])
    technician: Optional[str] = None
    notes: Optional[str] = None


class StockChangeIn(BaseModel):
    withdrawn_train_id: str
    replacement_train_id: str
    station: Optional[str] = None
    reason: Optional[str] = None


class TagIn(BaseModel):
    tag: str
    train_id: str


class DeviceAssignIn(BaseModel):
    train_id: str


# ---------------------------------------------------------------- routes

@app.get("/api/health")
def health():
    return {"ok": True, "mqtt_enabled": config.MQTT_ENABLED,
            "mqtt_connected": bool(bridge and bridge.connected),
            "broker": f"{config.MQTT_HOST}:{config.MQTT_PORT}", "dashboards": len(hub.clients)}


@app.get("/api/fleet")
def get_fleet():
    return service.fleet()


@app.get("/api/trains/{train_id}")
def get_train(train_id: str):
    return _wrap(service.train, train_id)


class AdjustIn(BaseModel):
    mileage: Optional[float] = None
    location: Optional[str] = Field(None, examples=["ST1"])


@app.patch("/api/trains/{train_id}")
def patch_train(train_id: str, body: AdjustIn):
    """Manual correction (dashboard double-click): set mileage and/or current station."""
    return _wrap(service.adjust_train, train_id, body.mileage, body.location)


@app.get("/api/alerts")
def get_alerts():
    return service.alerts()


@app.get("/api/history/{train_id}")
def get_history(train_id: str, limit: int = 100):
    return _wrap(service.history, train_id, limit)


@app.get("/api/events")
def get_events(limit: int = 50):
    return service.recent_events(limit)


@app.get("/api/devices")
def get_devices():
    return service.devices()


@app.put("/api/devices/{device_id}")
def put_device(device_id: str, body: DeviceAssignIn):
    return _wrap(service.assign_device, device_id, body.train_id)


@app.post("/api/tags")
def post_tag(body: TagIn):
    return _wrap(service.assign_tag, body.tag, body.train_id)


@app.post("/api/pm")
def post_pm(body: PmIn):
    return _wrap(service.record_pm, body.train_id, body.pm_type, body.technician, body.notes)


@app.post("/api/stockchange")
def post_stockchange(body: StockChangeIn):
    return _wrap(service.stock_change, body.withdrawn_train_id, body.replacement_train_id,
                 body.station, body.reason)


@app.get("/api/track")
def get_track():
    """Demo-track layout: stations and segment lengths (toy metres) + demo scale."""
    return service.track()


@app.put("/api/track")
def put_track(body: TrackIn):
    """Change segment lengths, e.g. {"segments": [{"from": "ST1", "to": "ST2", "length_m": 1.25}]}"""
    return _wrap(service.update_track, body.segments)


@app.get("/api/demo/trains")
def get_demo_trains():
    """Trains on the demo track (linked to an on-board device)."""
    return service.demo_trains()


@app.post("/api/demo/trains")
def post_demo_train(body: DemoTrainIn):
    """Add a train to the demo track, or change its device / RFID tag / mileage."""
    return _wrap(service.save_demo_train, body.train_id.strip(), body.device_id.strip(), body.tag,
                 body.mileage, body.type)


@app.delete("/api/demo/trains/{train_id}")
def delete_demo_train(train_id: str):
    return _wrap(service.remove_demo_train, train_id)


@app.get("/api/config")
def get_config():
    return service.get_config()


@app.put("/api/config")
def put_config(body: dict):
    return _wrap(service.update_config, body)


# HTTP fallback for hardware that cannot use MQTT (same logic as the MQTT topics)
@app.post("/api/ingest/odometer")
def ingest_odometer(body: OdometerIn):
    _wrap(service.check_source, body.source)
    return _wrap(service.ingest_odometer, body.device_id, body.pulses, body.source)


@app.post("/api/ingest/rfid")
def ingest_rfid(body: RfidIn):
    _wrap(service.check_source, body.source)
    return _wrap(service.ingest_rfid, body.station_id, body.tag, body.source)


@app.websocket("/ws")
async def websocket(ws: WebSocket):
    await ws.accept()
    hub.clients.add(ws)
    try:
        await ws.send_text(json.dumps({"type": "hello", "fleet_size": len(service.fleet())}))
        while True:
            await ws.receive_text()  # keep-alive; client messages are ignored
    except WebSocketDisconnect:
        pass
    finally:
        hub.clients.discard(ws)


# Serve the dashboard from the same server: http://localhost:8000/
DASHBOARD = config.BASE_DIR.parent / "First_Dashboard.html"


@app.get("/", include_in_schema=False)
def root(request: Request):
    query = request.url.query           # keep ?mode=demo etc.
    return RedirectResponse("/First_Dashboard.html" + ("?" + query if query else ""))


@app.get("/First_Dashboard.html", include_in_schema=False)
def dashboard():
    if not DASHBOARD.exists():
        raise HTTPException(404, "First_Dashboard.html not found next to the backend folder")
    return FileResponse(DASHBOARD, headers={"Cache-Control": "no-cache"})


@app.get("/simulator", include_in_schema=False)
def simulator():
    """Hardware simulator page: drag a wheel + press station buttons instead of real ESP32s."""
    return FileResponse(config.BASE_DIR / "simulator.html", headers={"Cache-Control": "no-cache"})


if __name__ == "__main__":
    import uvicorn

    p = argparse.ArgumentParser(description="SPLRT Fleet backend")
    p.add_argument("--host", default="0.0.0.0", help="0.0.0.0 lets ESP32s on the hotspot reach the API")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--no-mqtt", action="store_true", help="run without an MQTT broker (HTTP ingestion only)")
    p.add_argument("--mqtt-host", default=None)
    args = p.parse_args()
    if args.no_mqtt:
        config.MQTT_ENABLED = False
    if args.mqtt_host:
        config.MQTT_HOST = args.mqtt_host
    uvicorn.run(app, host=args.host, port=args.port)
