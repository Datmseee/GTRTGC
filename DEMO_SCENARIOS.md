# Demo scenarios

Ready-made cases for the event-day demo. Dashboard in **Demo** mode → **▶ SCENARIOS**.
Hover a case to see what it sets up, what you do and which LTA requirement it answers.

Loading a case only changes the demo trains' mileage, location and PM history. It never touches
devices, track tags, wheel size, track lengths, settings, MQTT or the WebSocket, so the live
encoder and RFID data keep flowing while you switch, rerun or reset.

## The 4 sections

| Section | Story for the judges | Cases |
|---|---|---|
| **TRACK** | Mileage is captured automatically | A1 Live mileage · A2 Station check-in · A3 Depot moves |
| **PLAN** | The system tells you when maintenance is due | B1 PM due soon · B2 PM overdue · B3 Bundled checks |
| **ACT** | Decisions take one click and are logged | C1 Stock change · C2 PM sign-off · C3 Fleet overview |
| **TRUST** | The numbers can be relied on | D1 Wheel wear check · D2 Restart recovery |

## Cases

| Case | You do | Judges see | LTA link |
|---|---|---|---|
| A1 Live mileage | Spin the knob | Mileage counts up live | Objective 1, real-time tracking |
| A2 Station check-in | Spin, tap ST2 card | Position fix + measured vs track distance | Check-in: accuracy |
| A3 Depot moves | Spin out, tap ST1 card | Depot run added to mileage | Stabling yard to mainline (850 m) |
| B1 PM due soon | ~4 turns, pick a slot | Amber warning + slot choice | Objective 3, PM planning |
| B2 PM overdue | ~4 turns, choose | Red alert: Recall / Withdraw / Defer | Step 2, recall is manual today |
| B3 Bundled checks | ~4 turns | 2K + 13K merged into one visit | Bonus |
| C1 Stock change | Recall now, drive to depot, tap DEPOT | Standby train takes over | Stock change in service |
| C2 PM sign-off | Type a name, Sign off | Next check from real mileage, no hubometer | Step 3, hubometer read by hand |
| C3 Fleet overview | Click a train | Every train, mileage, status, place | Objective 2, centralised info |
| D1 Wheel wear check | Drive CAL 0 → CAL END | New wheel size measured | Bonus |
| D2 Restart recovery | Unplug 15 s, plug in, spin | Mileage carries on | Bonus |
| ↺ Clean start | Nothing | Both trains healthy in the depot | Use between visitors |

1 knob turn ≈ 94 m of real mileage (30 mm wheel × demo scale 1000). Cases start ~3.5 turns before the line.

## Controls

| What | How |
|---|---|
| Pick any case, any order | **▶ SCENARIOS**, click a card |
| Previous / rerun / next | ‹ ↻ › in the case banner on the map |
| Rehearsal notes (what to say + do) | Press **`** (backtick) or double-click the section chip. Always hidden after a page reload. |
| Close panel | Esc |

The audience only sees the banner: section + case title.

## Demo trains

The backend IDs stay `810D-001` / `810D-002` (linked to `LRV01` / `LRV02`). Demo mode shows them as
**810A-001 / 810A-002, type C810A**, because C810D already has onboard mileage (MVCS) and the
hubometer problem is on C810 / C810A. Display only.

With one ESP32 (two encoder ports): encoder 1 → `LRV01` → 810A-001, encoder 2 → `LRV02` → 810A-002.
Station RFID reads carry no train ID and go to the train in **Demo settings → "Station-reader RFID reads belong to"** (default `LRV01`).
Scenarios drive that train; the other is the standby.

## Table layout (floor mat)

**Event setup: A4 mat, visual props.** `demo_layout/SGRTGC_floor_mat_light_6xA4.pdf` (or `_dark_`):
6 A4 landscape sheets, 3 across x 2 down, **print at 100% / actual size**. Cut each sheet along the red
dotted line (left or top edge) and lay it over its neighbour. Finished mat about 874 x 411 mm, audience
along the bottom edge. Check: CAL 0 to CAL END = 70.7 mm. Props are the A3 design scaled x0.7071.

The electronics (ESP32, knob encoder, RFID reader) sit beside the mat as the "on-board unit".
Move the train prop by hand, spin the knob, and tap the RFID card when the train reaches a diamond.

The dashboard's demo track is drawn from the same geometry (`demo_layout/layout.py`), so the table and
the screen match. Enter these in **Demo settings** (double-click each length on the demo track):

| Segment | A4 mat | (A3 mat) |
|---|---|---|
| ST1 → ST2 | 0.334 m | 0.472 m |
| ST2 → ST1 | 1.626 m | 2.300 m |
| Depot → ST1 | 0.840 m | 1.188 m |
| Branch → Depot | 0.206 m | 0.291 m |

Leave the calibration zone length as it is: it defines the wheel calibration, not the mat.

To change the layout: edit `demo_layout/layout.py`, then run `python mat.py` (new PDFs) and
`python dash_svg.py ../First_Dashboard.html` (new dashboard track).
