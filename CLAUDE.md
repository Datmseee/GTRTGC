# CLAUDE.md

## Project
SPLRT Fleet Management Dashboard — single-file HTML/CSS/JS app (`First_Dashboard.html`). No build tools. Open directly in browser or `python3 -m http.server 8080`.

## Map Stack
- **Leaflet.js 1.9.4** via CDN + **CartoDB Dark Matter** tiles (free, no API key)
- No canvas — trains are `L.marker` with `L.divIcon`, tracks are `L.polyline`

## Key Data Structures
- `STATIONS` — source of truth for station positions. Keyed by loop ID (`'SK-West'`, `'SK-East'`, `'PG-West'`, `'PG-East'`), each an ordered array of `{name, lat, lng, hub?}` in WGS84.
- `LOOPS` — real track points (OpenStreetMap monorail geometry). Used for polyline rendering and train position interpolation; stations are snapped to nearest track point for alignment.
- `LOOP_METRICS` — precomputed closed-loop points + cumulative distances for distance-based interpolation and loop length lookup.
- `TRACKS` / `TRACK_METRICS` — dual offset tracks per loop (cw/ccw) for bidirectional rendering and train placement.
- `DEPOT` — `{lat, lng, name}` for MMB Depot.
- `fleet` — 59 train objects from `makeFleet()`: `{id, type, mileage, status, loop, pos, speed, marker, _el, ...}`.
- `PM_CYCLES` — `[2000, 13000, 40000, 120000, 360000]` km thresholds.

## Where to Edit
| Task | Location |
|------|----------|
| Fix station positions | `STATIONS` object — edit `lat`/`lng` values |
| Track colours | `LOOP_COLORS` object |
| Theme colours | `--track-sk` / `--track-pg` CSS vars in `:root` |
| PM thresholds | `PM_CYCLES` array |
| Add/remove trains | `makeFleet()` |
| Depot position | `DEPOT` object |
| Map center/zoom | `L.map('map', { center, zoom })` call |

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

## Constraints
- **Single HTML file** — do not split
- **Do not change:** dark theme palette, IBM Plex Mono + IBM Plex Sans Condensed fonts, sidebar layout, detail panel, animation logic, PM threshold values
- All colours via `var(--name)` CSS variables
- Font refs: `var(--mono)` for numbers/data, `var(--sans)` for UI text
