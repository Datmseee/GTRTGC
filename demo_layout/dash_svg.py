"""Rewrite the dashboard's demo-track SVG from layout.py so the screen matches the floor mat."""
import re, sys
import layout as Ly

HTML = sys.argv[1]
S = 1000 / Ly.MAT_W
OY = (560 - Ly.MAT_H * S) / 2


def P(p):
    return (round(p[0] * S, 1), round(OY + (Ly.MAT_H - p[1]) * S, 1))


def d_of(prims):
    out = []
    x, y = P(prims[0][1]); out.append(f"M{x},{y}")
    for q in prims:
        ex, ey = P(q[2])
        if q[0] == "L":
            out.append(f"L{ex},{ey}")
        else:
            r = round(q[4] * S, 1)
            out.append(f"A{r},{r} 0 0 {0 if q[5] else 1} {ex},{ey}")
    return " ".join(out)


def rect(x0, x1, y0, y1):
    a, b = P((x0, y1)), P((x1, y0))
    return f'<rect class="dt-foot" x="{a[0]}" y="{a[1]}" width="{round(b[0]-a[0],1)}" height="{round(b[1]-a[1],1)}"/>'


T = {k: P(v) for k, v in Ly.TAGS.items()}
cy = Ly.YT + Ly.ST_TRACK_OFFSET
foot = []
for sid, (nm, sx) in Ly.STATIONS.items():
    x0, x1, y0, y1 = Ly.ST_PLAT
    foot.append(rect(sx + x0, sx + Ly.ST_TOWER[1], cy + y0, cy + y1))
x0, x1, y0, y1 = Ly.DEPOT_FOOT
foot.append(rect(Ly.DEPOT_X + x0, Ly.DEPOT_X + x1, Ly.DEPOT_Y + y0, Ly.DEPOT_Y + y1))

L = lambda k: Ly.SEG_LEN_M[k]
tl = P(((Ly.ST1_X + Ly.ST2_X) / 2, Ly.YT - 30))
bl = P((Ly.DEPOT_X, Ly.YB + 30))
dl = P((360, 175)); il = P((880, 175))
svg = f'''          <!-- generated from demo_layout/layout.py: same geometry as the printed floor mat -->
          {''.join(foot)}
          <path class="dt-rail depot" d="{d_of(Ly.DEPOT_DRAW)}"/>
          <path class="dt-rail" d="{d_of(Ly.LOOP_DRAW)}"/>
          <path class="dt-core" d="{d_of(Ly.DEPOT_DRAW)}"/>
          <path class="dt-core" d="{d_of(Ly.LOOP_DRAW)}"/>
          <!-- route geometry used to place the trains (not drawn) -->
          <path id="dtPath-top" class="dt-route" d="{d_of(Ly.PATHS['top'])}"/>
          <path id="dtPath-bottom" class="dt-route" d="{d_of(Ly.PATHS['bottom'])}"/>
          <path id="dtPath-depot_out" class="dt-route" d="{d_of(Ly.PATHS['depot_out'])}"/>
          <path id="dtPath-depot_in" class="dt-route" d="{d_of(Ly.PATHS['depot_in'])}"/>
          <text class="dt-len" id="dtLen-ST1" x="{tl[0]}" y="{tl[1]}" text-anchor="middle" ondblclick="editSegment(event,'ST1')">ST1 → ST2 · {L('top')} m</text>
          <text class="dt-len" id="dtLen-ST2" x="{bl[0]}" y="{bl[1]}" text-anchor="middle" ondblclick="editSegment(event,'ST2')">ST2 → ST1 · {L('bottom')} m</text>
          <text class="dt-len" id="dtLen-DEPOT" x="{dl[0]}" y="{dl[1]}" text-anchor="end" ondblclick="editSegment(event,'DEPOT')">Depot → ST1 · {L('depot_out')} m</text>
          <text class="dt-len" id="dtLen-BRANCH" x="{il[0]}" y="{il[1]}" ondblclick="editSegment(event,'BRANCH')">Branch → Depot · {L('depot_in')} m</text>
          <!-- track tags that are not stations: depot branch + wheel calibration zone -->
          <g class="dt-tag ed" transform="translate({T['BRANCH'][0]},{T['BRANCH'][1]})" ondblclick="editTrackTag(event,'BRANCH')"><title>Depot branch tag - double-click to set its UID</title><rect x="-6" y="-6" width="12" height="12" transform="rotate(45)"/></g>
          <text class="dt-tag-lbl ed" x="{T['BRANCH'][0] + 14}" y="{T['BRANCH'][1] + 4}" ondblclick="editTrackTag(event,'BRANCH')">BRANCH</text>
          <g class="dt-tag ed" transform="translate({T['CAL0'][0]},{T['CAL0'][1]})" ondblclick="editTrackTag(event,'CAL0')"><title>Calibration 0 m tag - double-click to set its UID</title><rect x="-6" y="-6" width="12" height="12" transform="rotate(45)"/></g>
          <text class="dt-tag-lbl ed" id="dtCal0" x="{T['CAL0'][0] - 14}" y="{T['CAL0'][1] - 6}" text-anchor="end" ondblclick="editCalZone(event)"><title>Double-click to set the calibration zone length</title>CAL 0 m</text>
          <g class="dt-tag ed" transform="translate({T['CAL100'][0]},{T['CAL100'][1]})" ondblclick="editTrackTag(event,'CAL100')"><title>Calibration end tag - double-click to set its UID</title><rect x="-6" y="-6" width="12" height="12" transform="rotate(45)"/></g>
          <text class="dt-tag-lbl ed" id="dtCal100" x="{T['CAL100'][0] + 14}" y="{T['CAL100'][1] + 14}" ondblclick="editCalZone(event)"><title>Double-click to set the calibration zone length</title>CAL 100 m</text>
          <g class="dt-sta ed" ondblclick="editTrackTag(event,'ST1')"><title>Sengkang (ST1) - double-click to set its tag UID</title><circle class="halo" cx="{T['ST1'][0]}" cy="{T['ST1'][1]}" r="24"/><circle class="core" cx="{T['ST1'][0]}" cy="{T['ST1'][1]}" r="12"/></g>
          <g class="dt-sta ed" ondblclick="editTrackTag(event,'ST2')"><title>Punggol (ST2) - double-click to set its tag UID</title><circle class="halo" cx="{T['ST2'][0]}" cy="{T['ST2'][1]}" r="24"/><circle class="core" cx="{T['ST2'][0]}" cy="{T['ST2'][1]}" r="12"/></g>
          <g class="dt-sta depot ed" ondblclick="editTrackTag(event,'DEPOT')"><title>Sengkang Depot - double-click to set its tag UID</title><circle class="halo" cx="{T['DEPOT'][0]}" cy="{T['DEPOT'][1]}" r="24"/><circle class="core" cx="{T['DEPOT'][0]}" cy="{T['DEPOT'][1]}" r="12"/></g>
'''
h = open(HTML, encoding="utf8").read()
a = h.find('          <!-- generated from demo_layout/layout.py')
if a < 0:
    a = h.index('          <!-- double rail, like the LRT map')
b = h.index('        </svg>', a)
h = h[:a] + svg + h[b:]
# overlay labels
h = re.sub(r'(<div class="sta-label dt-sta-label" )data-x="[\d.]+" data-y="[\d.]+"(><span>ST1)', rf'\1data-x="{T["ST1"][0]}" data-y="{T["ST1"][1]}"\2', h)
h = re.sub(r'(<div class="sta-label dt-sta-label" )data-x="[\d.]+" data-y="[\d.]+"(><span>ST2)', rf'\1data-x="{T["ST2"][0]}" data-y="{T["ST2"][1]}"\2', h)
h = re.sub(r'(<div class="sta-label dt-sta-label depot" )data-x="[\d.]+" data-y="[\d.]+"(><span>DEPOT</span><span class="sta-name-small">)Depot', rf'\1data-x="{T["DEPOT"][0]}" data-y="{T["DEPOT"][1]}"\2Sengkang', h)
# placement data
pts = "  points: {" + ", ".join(f"{k}:{{x:{T[k][0]},y:{T[k][1]}}}" for k in ("ST1", "ST2", "DEPOT", "BRANCH")) + "},"
h = re.sub(r"  points: \{ST1:\{x:[^\n]*\},\n", pts + "\n", h, count=1)
tags = f"  segTags: {{ DEPOT: [{{id:'CAL0', x:{T['CAL0'][0]}, y:{T['CAL0'][1]}}}, {{id:'CAL100', x:{T['CAL100'][0]}, y:{T['CAL100'][1]}}}] }},"
h = re.sub(r"  segTags: \{ DEPOT: [^\n]*\n", tags + "\n", h, count=1)
# styles: route geometry invisible, prop footprints faint
if ".dt-route{" not in h:
    h = h.replace(".dt-core{", ".dt-route{fill:none;stroke:none}\n.dt-foot{fill:none;stroke:var(--txt2);stroke-width:1;stroke-dasharray:4 3;opacity:0.7}\n.dt-core{", 1)
open(HTML, "w", encoding="utf8").write(h)
print("ok", pts, tags, Ly.SEG_LEN_M)
