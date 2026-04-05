# AGENTS.md

## Running the App

```bash
python3 -m http.server 8080
# Open http://localhost:8080/First_Dashboard.html
```

## Key Constraints

- **Single HTML file** — do NOT split into multiple files
- **Do NOT change:** dark theme, IBM Plex fonts, sidebar layout, detail panel, animation logic, PM thresholds
- All colors via CSS `var(--name)` variables in `:root`
- Font refs: `var(--mono)` for numbers, `var(--sans)` for UI text

## Map Stack

- Leaflet.js 1.9.4 via CDN + CartoDB Dark Matter tiles (no API key needed)
- Trains are `L.marker` with `L.divIcon`; tracks are `L.polyline` (NOT canvas)

## Where to Edit

| Task | Location in `First_Dashboard.html` |
|------|-------------------------------------|
| Station positions | `STATIONS` object (WGS84 lat/lng) |
| Track colors | `LOOP_COLORS` object |
| Theme colors | `--track-sk` / `--track-pg` CSS vars in `:root` |
| PM thresholds | `PM_CYCLES` array — `[2000, 13000, 40000, 120000, 360000]` |
| Add/remove trains | `makeFleet()` function |
| Depot position | `DEPOT` object |
| Map center/zoom | `L.map('map', { center, zoom })` call |

## GitHub Pages Deploy

- Deploys automatically on push to `main` or `UI-Improvements` branches
- Workflow: `.github/workflows/deploy.yml`
- Uses `actions/upload-pages-artifact` with path: `.`

## Data Structures

- `STATIONS` — source of truth, keyed by loop ID (`'SK-West'`, `'SK-East'`, `'PG-West'`, `'PG-East'`)
- `LOOPS` — track points for polyline rendering + position interpolation
- `LOOP_METRICS` — closed-loop points + cumulative distances
- `TRACKS` / `TRACK_METRICS` — dual offset tracks (cw/ccw) for bidirectional rendering
- `fleet` — 59 train objects from `makeFleet()`

## Station GPS Coordinates (WGS84)

```
SENGKANG:  1.39149, 103.89517
SK-West:   Cheng Lim(1.39641,103.88582) Farmway(1.39882,103.87928) Kupang(1.39628,103.87480)
            Thanggam(1.39185,103.87380) Fernvale(1.38745,103.87540) Layar(1.38382,103.87992)
            Tongkang(1.38375,103.88598) Renjong(1.38648,103.89128)
SK-East:   Compassvale(1.39608,103.90028) Rumbia(1.39820,103.90598) Bakau(1.39618,103.91118)
            Kangkar(1.39238,103.91178) Ranggung(1.38928,103.90848)
PUNGGOL:   1.40528, 103.90218
PG-West:   Soo Teck(1.40198,103.90218) Sumang(1.39978,103.89898) Nibong(1.39848,103.89518)
            Samudera(1.39938,103.89118) Punggol Point(1.40298,103.88948)
            Teck Lee(1.40628,103.89178) Sam Kee(1.40728,103.89678)
PG-East:   Cove(1.40778,103.90618) Meridian(1.40818,103.91048) Coral Edge(1.40618,103.91478)
            Riviera(1.40258,103.91518) Kadaloor(1.39948,103.91298)
            Oasis(1.39798,103.90878) Damai(1.39928,103.90478)
DEPOT:     1.38906, 103.88626
```
