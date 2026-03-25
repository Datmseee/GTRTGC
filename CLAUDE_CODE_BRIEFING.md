# SPLRT Fleet Management Dashboard — Claude Code Project Briefing
> Prepared for: Claude Code continuation session  
> Project: Singapore RailTech Grand Challenge (SGRTGC) 2026 — Open Innovation Challenge  
> Team: Weibo (lead/backend), Felix, Haoran (Computer Engineering), Jun Feng, Chaun Yong (Electronics)

---

## 1. COMPETITION CONTEXT

We are participating in the **SGRTGC 2026 Open Innovation Challenge**, organised by LTA (Land Transport Authority) with SBST and SMRT as judges. The competition requires teams to design, build, and demonstrate a **working prototype** — not just a concept.

**Key dates:**
- Registration deadline: 20 Mar 2026
- Check-in 1 (online, MS Teams): Week of 8–12 Jun 2026
- Check-in 2 (physical): Week of 10–15 Aug 2026
- Final submission (report + video + poster): **1 Oct 2026, 6pm**
- Event Day (presentation + judging): **24 Oct 2026**
- Prize ceremony / SUMW: 4 Nov 2026

**Budget:** $500 seed money per team (reimbursed only if all deliverables are submitted)

**Deliverables required:**
1. Proposal/Report in Word Doc or PDF (template: Abstract → ToC → Introduction → Literature Review → Methodology → Measurements for Feasibility → Results → Conclusion)
2. Short video presentation (max 3 minutes, MP4)
3. Summary poster (A1 size, PowerPoint format)

---

## 2. PROBLEM STATEMENT

**"Automation of Light Rail Transit (LRT) Vehicle Mileage Tracking to Enhance the Effectiveness of Maintenance Planning"**

### Current Pain Points (what we are solving):
- **No automated mileage tracking** — mileage is recorded manually by staff reading a physical Hubometer (wheel-hub odometer) only when a train is shunted into the MMB depot for Preventive Maintenance (PM) inspection
- **Labour intensive** — Daily checking of Hubometers takes excessive man-hours
- **Error prone** — Manual estimation based on number of rounds × loop distance is inaccurate
- **No centralised dashboard** — No single view of fleet mileage, serviceability status, or deployment info
- **Reactive, not data-driven** — Maintenance scheduling cannot be optimised without accurate real-time mileage

### Current Process (3 steps we must replace/automate):
1. **Daily estimation** — OCC (Operations Control Centre) and WC (Workshop Controller) manually estimate mileage based on number of rounds × loop distance. Logged in a spreadsheet.
2. **Recall decision** — Accumulated estimated mileage in spreadsheet triggers manual recall of a specific train for inspection
3. **Hubometer reading** — When train returns to depot, staff physically read the Hubometer on the A1 tyre. Actual mileage = current Hubometer value − previous Hubometer value.

### Operational Constraints:
- **Revenue hours:** 5am–1am daily
- **Peak hours:** 7am–9:30am (AM), 5pm–8pm (PM)
- **Headways:** Peak = 3 min, Off-peak = 8 min
- **Legacy fleet** — uses wheel-hub Hubometers; full onboard system replacement is NOT feasible (10–20 years remaining asset life)
- **Budget constraint** — any hardware solution must be low-cost
- **Stock changes** — a train can be withdrawn mid-service and replaced by another from the depot; tracking must handle this
- **Mileage scope** — must track: mainline loops AND depot-to-reception track movements (850m from S5/Unison to reception tracks)

### PM Trigger Mileages (what the system must track and alert on):
| Cycle | Action |
|-------|--------|
| 2,000 km | Visual inspection |
| 13,000 km | Function checks (Emergency Door, Saloon Door) |
| 40,000 km | Extended system checks (Air-con, Brakes) |
| 120,000 km | Component detail checks (Greasing, Air Compressor, Filter Cleaning) |
| 360,000 km | Full overhaul (Bogie removal, major parts) |

---

## 3. THE FLEET — SPLRT (Sengkang-Punggol LRT)

### Train Types:
| Type | Count | Mileage System | Notes |
|------|-------|---------------|-------|
| C810 | 20 | Hubometer (requires shunt to MMB) | Oldest fleet |
| C810A (Mod + New) | 32 | Hubometer (requires shunt to MMB) | Most common |
| C810D | 7 | MVCS (requires authorised personnel onboard) | Newest, different system |
| **Total** | **59** | | |

### Line Overview:
**Sengkang LRT:**
- West Loop: 6.3 km
- East Loop: 4.5 km
- Total: 13 stations (including Sengkang interchange)

**Punggol LRT:**
- West Loop: 4.44 km
- East Loop: 5.24 km
- Total: 14 stations (including Punggol interchange)

### Correct Station Lists (in loop order):

**Sengkang West Loop** (anti-clockwise, 6.3 km):
Sengkang → Cheng Lim → Farmway → Kupang → Thanggam → Fernvale → Layar → Tongkang → Renjong → (back to Sengkang)

**Sengkang East Loop** (clockwise, 4.5 km):
Sengkang → Compassvale → Rumbia → Bakau → Kangkar → Ranggung → (back to Sengkang)

**Punggol West Loop** (anti-clockwise, 4.44 km):
Punggol → Soo Teck → Sumang → Nibong → Samudera → Punggol Point → Teck Lee → Sam Kee → (back to Punggol)

**Punggol East Loop** (clockwise, 5.24 km):
Punggol → Cove → Meridian → Coral Edge → Riviera → Kadaloor → Oasis → Damai → (back to Punggol)

### ⚠️ KNOWN BUG IN CURRENT DASHBOARD:
The SVG station positions in the current `splrt-dashboard.html` are **geographically inaccurate**. The station names are correct but the x/y coordinates are wrong — they were approximated rather than based on real geography. The loops need to be redrawn.

**Correct approximate SVG coordinates (viewBox 820×500, Sengkang on left ~x=200, Punggol on right ~x=580):**

```
SENGKANG INTERCHANGE: x=200, y=260

Sengkang WEST Loop (forms a rough teardrop going left/northwest):
  Cheng Lim:   x=160, y=210
  Farmway:     x=112, y=205
  Kupang:      x=78,  y=238
  Thanggam:    x=72,  y=278
  Fernvale:    x=90,  y=318
  Layar:       x=128, y=348
  Tongkang:    x=168, y=355
  Renjong:     x=196, y=325

Sengkang EAST Loop (forms a smaller loop going right/northeast):
  Compassvale: x=248, y=208
  Rumbia:      x=296, y=200
  Bakau:       x=336, y=232
  Kangkar:     x=334, y=278
  Ranggung:    x=296, y=308

PUNGGOL INTERCHANGE: x=580, y=260

Punggol WEST Loop (forms a loop going left/northwest):
  Soo Teck:      x=556, y=308
  Sumang:        x=520, y=338
  Nibong:        x=476, y=328
  Samudera:      x=444, y=294
  Punggol Point: x=442, y=248
  Teck Lee:      x=468, y=214
  Sam Kee:       x=516, y=206

Punggol EAST Loop (forms a loop going right/east):
  Cove:        x=620, y=214
  Meridian:    x=664, y=218
  Coral Edge:  x=704, y=252
  Riviera:     x=700, y=296
  Kadaloor:    x=666, y=332
  Oasis:       x=626, y=344
  Damai:       x=586, y=318

MMB DEPOT (Sengkang): approximately x=128, y=430
  - Connected to Sengkang West Loop near Tongkang/Renjong area
  - 850m from S5/Unison station area to reception tracks
```

**Note on loop direction:** Trains run in a single direction around each loop (not bidirectional). The actual physical direction for rendering should look like proper loops, not straight lines.

---

## 4. CURRENT STATE OF THE DASHBOARD

### File: `splrt-dashboard.html`
A single-file HTML/CSS/JS dashboard has been built as a prototype. It is **fully functional** with simulated/mock data. Here is what it currently does:

### ✅ Already Working:
1. **Dark theme UI** — navy/dark blue palette, JetBrains Mono + DM Sans fonts
2. **Animated trains** — trains move around their loops in real-time using `requestAnimationFrame`
3. **Clickable trains** — click any train marker on the SVG map to open a detail panel
4. **Detail panel** — shows: train ID, type, status, mileage, next PM distance, service run, session km, last PM mileage, all 5 PM cycle progress bars
5. **Sidebar stats** — Total fleet (59), In Service count, PM Alert count, In Depot count
6. **PM Alerts list** — top 5 most urgent trains sorted by PM proximity
7. **Train roster** — scrollable list of all active trains with per-train PM progress bar
8. **Colour coding** — green (operational), yellow (PM due within 200km), red (PM overdue)
9. **Live clock** — SGT time, auto-switches peak/off-peak/out-of-service tag based on real SPLRT hours
10. **Depot section** — 5 depot/maintenance trains tracked separately
11. **Map legend** — colour key for loops and statuses
12. **Stock change logic** — train status updates dynamically as mileage accumulates

### ❌ Known Issues / To Fix:
1. **Wrong station positions** — SVG x/y coordinates don't reflect actual geography (see correct coordinates above)
2. **Loop shapes inaccurate** — loops need to look like the real Sengkang/Punggol LRT geography
3. **No real backend** — everything is simulated in JS with `Math.random()`; needs to be connected to a real data source eventually
4. **No stock change UI** — stock change events happen but there's no visual indication or log
5. **No depot animation** — depot trains are listed in sidebar but not shown on the map
6. **Train labels too small** — the ID numbers on train markers are hard to read
7. **No headway/spacing display** — doesn't show train-to-train spacing on the loop
8. **No maintenance history log** — detail panel shows current state but no history

### 🆕 Features to Add:
See Section 6 below.

---

## 5. TECH STACK DECISIONS

### Frontend (dashboard):
- **Single-file HTML/CSS/JS** — no build tools, no frameworks, runs directly in browser
- Fonts: Google Fonts — JetBrains Mono (data/numbers) + DM Sans (UI text)
- Map: Custom SVG drawn in code (no Leaflet or Google Maps — keeps it self-contained)
- Animation: `requestAnimationFrame` loop
- No external JS libraries required

### Backend (to be built — Weibo's scope):
- **Recommended:** Node.js + Express or Python FastAPI
- **Database:** SQLite for prototype (easy to set up, file-based, no server needed) → can migrate to PostgreSQL for production
- **Real-time updates:** WebSocket (Socket.io for Node, or websockets library for Python) to push mileage updates to the dashboard
- **API endpoints needed:**
  - `GET /fleet` — returns all trains and their current data
  - `GET /train/:id` — single train detail
  - `POST /mileage/update` — receives mileage reading from hardware sensor
  - `GET /alerts` — trains at or near PM thresholds
  - `POST /stockchange` — logs a stock change event
  - `GET /history/:id` — PM history for a specific train

### Hardware integration (EE scope):
- Sensor data will be pushed to the backend API via WiFi (ESP32/Raspberry Pi)
- Dashboard polls or receives WebSocket push from backend
- Frontend does NOT need to know hardware details — it just consumes the API

---

## 6. FULL FEATURE REQUIREMENTS (priority ordered)

### Priority 1 — Fix and complete the map:
- Redraw all 4 loops with correct station positions (coordinates in Section 3)
- Loops should look like proper oval/teardrop geographic shapes
- Show Sengkang and Punggol interchange stations clearly as hub nodes
- Show MMB Depot with a dashed connection line to the mainline
- Station labels should not overlap — consider angling or offsetting labels
- Train markers should be legible (bigger label, distinct shape)

### Priority 2 — Backend API integration:
- Replace all `Math.random()` mock data with real API calls
- `fetch('/api/fleet')` on load, then WebSocket or polling every 5s for updates
- Show a "connecting…" / "offline" state if API is unreachable
- All mileage values must persist in a database (SQLite schema provided below)

### Priority 3 — Stock change feature:
- Add a "Stock Change" button or modal in the UI
- When triggered: select a train from service, select a replacement from depot, log the swap with timestamp
- Map should animate the train moving from mainline back to depot icon
- Both trains' mileage records must update correctly after swap

### Priority 4 — Maintenance log / history:
- Detail panel should have a "History" tab
- Shows table of past PM events: date, mileage at PM, type of PM, technician (optional)
- Backend endpoint: `GET /history/:id`

### Priority 5 — Mileage manual override:
- Small "edit" button on detail panel for authorised override of mileage reading
- Required for initial calibration / syncing with Hubometer physical reads
- Must log who changed it and the before/after value

### Priority 6 — Export / reporting:
- "Export CSV" button that downloads current fleet mileage snapshot
- Useful for maintenance planners to take offline

### Priority 7 — Responsive / full-screen mode:
- Dashboard is currently fixed to viewport height
- Add a "fullscreen" button for display on control room monitors

---

## 7. DATABASE SCHEMA (SQLite)

```sql
CREATE TABLE trains (
  id TEXT PRIMARY KEY,          -- e.g. 'C810A-05'
  type TEXT NOT NULL,           -- 'C810', 'C810A', 'C810D'
  loop TEXT,                    -- 'skWest', 'skEast', 'pgWest', 'pgEast', 'depot'
  current_km REAL NOT NULL,     -- total cumulative mileage
  session_km REAL DEFAULT 0,    -- km since last depot return
  status TEXT DEFAULT 'op',     -- 'op', 'pm', 'ov', 'maint', 'depot'
  serviceable INTEGER DEFAULT 1,-- 1 = serviceable, 0 = withdrawn
  service_run TEXT,             -- current run ID e.g. 'SK-W-301'
  last_pm_km REAL,              -- mileage at last PM
  last_updated TEXT             -- ISO timestamp
);

CREATE TABLE mileage_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id TEXT NOT NULL,
  km_reading REAL NOT NULL,
  source TEXT,                  -- 'sensor', 'manual', 'hubometer'
  recorded_at TEXT NOT NULL,    -- ISO timestamp
  FOREIGN KEY (train_id) REFERENCES trains(id)
);

CREATE TABLE pm_history (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  train_id TEXT NOT NULL,
  pm_type TEXT NOT NULL,        -- '2000km', '13000km', etc.
  mileage_at_pm REAL NOT NULL,
  performed_at TEXT NOT NULL,   -- ISO timestamp
  technician TEXT,
  notes TEXT,
  FOREIGN KEY (train_id) REFERENCES trains(id)
);

CREATE TABLE stock_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  withdrawn_train_id TEXT NOT NULL,
  replacement_train_id TEXT NOT NULL,
  station TEXT,                 -- station where change occurred
  reason TEXT,
  changed_at TEXT NOT NULL,     -- ISO timestamp
  FOREIGN KEY (withdrawn_train_id) REFERENCES trains(id),
  FOREIGN KEY (replacement_train_id) REFERENCES trains(id)
);
```

---

## 8. TEAM ROLES & SCOPE DIVISION

| Member | Diploma | Role | Scope |
|--------|---------|------|-------|
| **Weibo** | Computer Engineering | Project Lead + Backend | Backend API (Node/Python), database, WebSocket server, PM alert logic, project coordination, report writing |
| **Felix** | Computer Engineering | Frontend / Dashboard | HTML/CSS/JS dashboard, map accuracy, UI features, UX polish |
| **Haoran** | Computer Engineering | Embedded / Firmware | Microcontroller code (Arduino/Raspberry Pi), sensor reading logic, data transmission to backend API |
| **Jun Feng** | Electronics | Hardware Engineer | Circuit design, sensor selection, PCB/breadboard build, power supply, physical mounting |
| **Chaun Yong** | Electronics | Sensors + Testing | Sensor calibration, accuracy testing, data logging, integration testing, writes Sections 6 & 7 of report |

---

## 9. JUDGING CRITERIA (what we need to score on)

| Criterion | What judges look for | How we address it |
|-----------|---------------------|-------------------|
| **Technical Innovation & Creativity** | Novel approach, not just off-the-shelf; original data collection method | RFID waypoints + IMU hybrid; custom centralised dashboard built from scratch |
| **Effectiveness** | Addresses core pain points; evidence of improvement; automation reducing manual effort | Dashboard eliminates manual spreadsheet; automated PM alerts; real test data in report |
| **Feasibility** | Works in live operational environment; realistic action plan; maintainable | Low-cost hardware; web-based dashboard needs no installation; documented migration path |
| **Visibility & Scalability** | Cost-benefit justified; room for expansion to other lines | Covers all 59 trains; could extend to BPLRT; dashboard scalable to any LRT line |

**Pro tip from briefing slides:** "Aim for a simple, user-friendly system — strong UI/UX clarity makes navigation much easier for our technicians."

---

## 10. INSTRUCTIONS FOR CLAUDE CODE

### Immediate task (what to work on first):
1. **Fix the station coordinates** in `splrt-dashboard.html` using the correct positions in Section 3 of this document
2. The file is a single self-contained HTML file — do not split into multiple files unless specifically asked
3. All station names, loop names, and train types are correct — only the SVG coordinate positions need fixing
4. After fixing coordinates, verify the loops look like proper closed oval/teardrop shapes, not straight lines or awkward polygons
5. Make sure station labels don't overlap each other after repositioning

### Code conventions to follow:
- Keep everything in a single HTML file (inline CSS + JS)
- Use CSS variables for all colours (already defined in `:root`)
- Font families: `var(--font)` for UI text, `var(--mono)` for numbers/IDs
- All SVG drawn with `createElementNS(NS, tag)` in JavaScript (no static SVG markup for dynamic elements)
- Train positions are calculated from `stations[]` arrays using linear interpolation between waypoints
- The `LOOPS` object is the single source of truth for station data — edit station coordinates there

### File location:
The current dashboard file is `splrt-dashboard.html`. It is a standalone single file. All edits should be made to this file.

### Do NOT change:
- The overall dark theme colour palette
- The font choices (JetBrains Mono + DM Sans)
- The sidebar layout structure (stats → alerts → train list)
- The detail panel design
- The train animation logic (only the station coordinates change)
- The PM threshold values (2000, 13000, 40000, 120000, 360000 km)
