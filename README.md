# SPLRT Fleet Management Dashboard
**Singapore RailTech Grand Challenge (SGRTGC) 2026**

Automated mileage tracking and preventive maintenance scheduling for 59 trains on the Sengkang-Punggol LRT network.

## Running
```bash
python3 -m http.server 8080
# open http://localhost:8080/First_Dashboard.html
```

---

## Competition Context

**Event:** SGRTGC 2026 Open Innovation Challenge — organised by LTA, judged by SBST and SMRT. Must build a working prototype.

| Milestone | Date |
|-----------|------|
| Registration deadline | 20 Mar 2026 |
| Check-in 1 (online) | Week of 8–12 Jun 2026 |
| Check-in 2 (physical) | Week of 10–15 Aug 2026 |
| Final submission | **1 Oct 2026, 6pm** |
| Event Day | **24 Oct 2026** |

**Budget:** $500 seed money (reimbursed on full submission)

**Deliverables:** Report (Word/PDF), video (max 3 min, MP4), poster (A1, PowerPoint)

---

## Problem Statement

**"Automation of LRT Vehicle Mileage Tracking to Enhance Maintenance Planning"**

**Current process (manual, 3 steps):**
1. OCC/WC estimate mileage daily (rounds × loop distance) — logged in spreadsheet
2. Accumulated estimate triggers manual recall of a train for inspection
3. Staff physically reads Hubometer at depot; delta = current − previous reading

**Pain points:** No real-time data, error-prone estimation, labour-intensive, no centralised view, reactive scheduling.

### PM Trigger Mileages
| Cycle | Action |
|-------|--------|
| 2,000 km | Visual inspection |
| 13,000 km | Function checks (Emergency Door, Saloon Door) |
| 40,000 km | Extended checks (Air-con, Brakes) |
| 120,000 km | Detail checks (Greasing, Air Compressor, Filter Cleaning) |
| 360,000 km | Full overhaul (Bogie removal, major parts) |

---

## The Fleet

| Type | Count | Mileage System |
|------|-------|---------------|
| C810 | 20 | Hubometer — requires shunt to MMB |
| C810A | 32 | Hubometer — requires shunt to MMB |
| C810D | 7 | MVCS — requires authorised personnel onboard |
| **Total** | **59** | |

**Lines:**
- Sengkang LRT: West Loop (6.3 km) + East Loop (4.5 km)
- Punggol LRT: West Loop (4.44 km) + East Loop (5.24 km)

**Station order:**
- SK-West: Sengkang → Cheng Lim → Farmway → Kupang → Thanggam → Fernvale → Layar → Tongkang → Renjong → Sengkang
- SK-East: Sengkang → Compassvale → Rumbia → Bakau → Kangkar → Ranggung → Sengkang
- PG-West: Punggol → Soo Teck → Sumang → Nibong → Samudera → Punggol Point → Teck Lee → Sam Kee → Punggol
- PG-East: Punggol → Cove → Meridian → Coral Edge → Riviera → Kadaloor → Oasis → Damai → Punggol

---

## Current Dashboard State

### Working ✅
Dark theme UI, animated trains, clickable train detail panel, sidebar fleet stats, PM alerts list, train roster, colour coding (green/yellow/red), live SGT clock, depot section, map legend, stock change logic.

### Known Issues ❌
- Track geometry is from OpenStreetMap; OneMap verification pending
- No real backend — all data simulated with `Math.random()`
- No stock change UI
- No depot animation on map
- No maintenance history log

---

## Tech Stack

**Frontend (current):** Single-file HTML/CSS/JS, IBM Plex fonts, canvas map, `requestAnimationFrame` animation loop.

**Backend (to build — Weibo):** Node.js + Express or Python FastAPI, SQLite → PostgreSQL, WebSocket for real-time updates.

**API endpoints needed:**
- `GET /fleet` — all trains
- `GET /train/:id` — single train detail
- `POST /mileage/update` — sensor reading ingestion
- `GET /alerts` — PM-threshold trains
- `POST /stockchange` — log a stock change
- `GET /history/:id` — PM history for a train

**Hardware (EE scope):** ESP32/Raspberry Pi pushes sensor data to backend API via WiFi.

---

## Database Schema (SQLite)

```sql
CREATE TABLE trains (
  id TEXT PRIMARY KEY, type TEXT NOT NULL, loop TEXT,
  current_km REAL NOT NULL, session_km REAL DEFAULT 0,
  status TEXT DEFAULT 'op', serviceable INTEGER DEFAULT 1,
  service_run TEXT, last_pm_km REAL, last_updated TEXT
);
CREATE TABLE mileage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, train_id TEXT NOT NULL,
  km_reading REAL NOT NULL, source TEXT, recorded_at TEXT NOT NULL,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);
CREATE TABLE pm_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT, train_id TEXT NOT NULL,
  pm_type TEXT NOT NULL, mileage_at_pm REAL NOT NULL,
  performed_at TEXT NOT NULL, technician TEXT, notes TEXT,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);
CREATE TABLE stock_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  withdrawn_train_id TEXT NOT NULL, replacement_train_id TEXT NOT NULL,
  station TEXT, reason TEXT, changed_at TEXT NOT NULL,
  FOREIGN KEY (withdrawn_train_id) REFERENCES trains(id),
  FOREIGN KEY (replacement_train_id) REFERENCES trains(id)
);
```

---

## Feature Roadmap (Priority Order)
1. Fix map — correct station coordinates, proper loop shapes, legible train markers
2. Backend API integration — replace mock data, WebSocket updates, offline state
3. Stock change UI — modal to log train swaps, depot animation
4. Maintenance history — "History" tab in detail panel
5. Mileage manual override — authorised edit with audit log
6. CSV export — fleet mileage snapshot download
7. Fullscreen mode — for control room monitors

---

## Team

| Member | Role | Scope |
|--------|------|-------|
| Weibo | Project Lead + Backend | API, database, WebSocket, PM logic, report |
| Felix | Frontend | Dashboard, map, UI/UX |
| Haoran | Embedded / Firmware | Microcontroller, sensor reading, data transmission |
| Jun Feng | Hardware | Circuit design, sensor selection, PCB, power |
| Chaun Yong | Sensors + Testing | Calibration, accuracy testing, integration, report §6–7 |

---

## Judging Criteria

| Criterion | Our Approach |
|-----------|-------------|
| Technical Innovation | RFID waypoints + IMU hybrid; custom dashboard from scratch |
| Effectiveness | Eliminates manual spreadsheet; automated PM alerts |
| Feasibility | Low-cost hardware; web-based, no installation needed |
| Scalability | 59 trains covered; extendable to BPLRT and other lines |
