"""
Demo table layout: ONE source of truth for the floor mat, the dashboard's demo-track SVG
and the Fusion assembly. All mm, mat origin bottom-left, y up (audience at the bottom edge).

Mat = 3 x 2 A3 landscape sheets, 12 mm overlap  ->  1236 x 582 mm.
"""
import math

SHEET_W, SHEET_H, OVERLAP = 420.0, 297.0, 12.0
COLS, ROWS = 3, 2
MAT_W = COLS * SHEET_W - (COLS - 1) * OVERLAP      # 1236
MAT_H = ROWS * SHEET_H - (ROWS - 1) * OVERLAP      # 582

# ---- loop (track centreline) ----
XL, XR = 62.0, MAT_W - 62.0       # left / right straights
YB, YT = 62.0, 465.0              # bottom / top straights
R_LOOP = 150.0
# ---- props (from demo_models.py) ----
CAR_L, CAR_W = 210.0, 80.0
ST_PLAT = (-120.0, 120.0, -29.0, 29.0)      # platform x0,x1,y0,y1 about its centre
ST_TOWER = (120.0, 160.0, -8.0, 29.0)
ST_CANOPY = (-128.0, 120.0, -101.0, 35.0)
ST_TRACK_OFFSET = 70.0                       # platform centre is this far above the track centreline
ST1_X, ST2_X = 362.0, 834.0
STATIONS = {"ST1": ("SENGKANG", ST1_X), "ST2": ("PUNGGOL", ST2_X)}
DEPOT_X, DEPOT_Y = 618.0, 215.0               # depot centre = depot stop
DEPOT_FOOT = (-130.0, 130.0, -61.0, 98.0)     # walls + pilasters + annex (+y)
DEPOT_NAME = "SENGKANG DEPOT"
# depot line + spurs
D_LEFT, D_RIGHT = DEPOT_X - 150.0, DEPOT_X + 150.0        # depot line ends (20 mm past the walls)
J_LEFT = D_LEFT - (DEPOT_Y - YB)                           # 45 deg spur meets the bottom straight
J_RIGHT = D_RIGHT + (DEPOT_Y - YB)
R_SPUR = 60.0
CAL_GAP = 100.0      # CAL 0 -> CAL END physical spacing on the mat (= cal_distance_m 0.1 m)


# ---------------- path maths: polyline with filleted corners -> lines + arcs ----------------
def fillet_path(pts, radii):
    """pts: waypoints; radii[i] = fillet radius at pts[i] (ends ignored).
    Returns primitives: ('L', p0, p1) and ('A', p0, p1, centre, r, ccw)."""
    prims, cur = [], pts[0]
    for i in range(1, len(pts)):
        p = pts[i]
        if i < len(pts) - 1 and radii[i] > 0:
            a, b = pts[i - 1], pts[i + 1]
            u = _unit(p[0] - a[0], p[1] - a[1]); v = _unit(b[0] - p[0], b[1] - p[1])
            cosang = max(-1, min(1, u[0] * v[0] + u[1] * v[1]))
            theta = math.acos(cosang)
            r = radii[i]
            t = r * math.tan(theta / 2)
            s = (p[0] - u[0] * t, p[1] - u[1] * t)
            e = (p[0] + v[0] * t, p[1] + v[1] * t)
            cross = u[0] * v[1] - u[1] * v[0]
            n = (-u[1], u[0]) if cross > 0 else (u[1], -u[0])
            c = (s[0] + n[0] * r, s[1] + n[1] * r)
            prims.append(("L", cur, s))
            prims.append(("A", s, e, c, r, cross > 0))
            cur = e
        else:
            prims.append(("L", cur, p))
            cur = p
    return [q for q in prims if not (q[0] == "L" and _dist(q[1], q[2]) < 1e-6)]


def _unit(x, y):
    d = math.hypot(x, y); return (x / d, y / d)


def _dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def prim_len(q):
    if q[0] == "L":
        return _dist(q[1], q[2])
    _, s, e, c, r, ccw = q
    a0 = math.atan2(s[1] - c[1], s[0] - c[0]); a1 = math.atan2(e[1] - c[1], e[0] - c[0])
    d = (a1 - a0) % (2 * math.pi) if ccw else (a0 - a1) % (2 * math.pi)
    return r * d


def path_len(prims):
    return sum(prim_len(q) for q in prims)


def sample(prims, step=2.0):
    out = []
    for q in prims:
        if q[0] == "L":
            n = max(1, int(_dist(q[1], q[2]) / step))
            out += [(q[1][0] + (q[2][0] - q[1][0]) * k / n, q[1][1] + (q[2][1] - q[1][1]) * k / n) for k in range(n + 1)]
        else:
            _, s, e, c, r, ccw = q
            a0 = math.atan2(s[1] - c[1], s[0] - c[0])
            d = prim_len(q) / r
            n = max(2, int(prim_len(q) / step))
            sg = 1 if ccw else -1
            out += [(c[0] + r * math.cos(a0 + sg * d * k / n), c[1] + r * math.sin(a0 + sg * d * k / n)) for k in range(n + 1)]
    return out


def point_at(prims, dist):
    for q in prims:
        L = prim_len(q)
        if dist <= L:
            if q[0] == "L":
                f = dist / L if L else 0
                return (q[1][0] + (q[2][0] - q[1][0]) * f, q[1][1] + (q[2][1] - q[1][1]) * f)
            _, s, e, c, r, ccw = q
            a0 = math.atan2(s[1] - c[1], s[0] - c[0]); sg = 1 if ccw else -1
            a = a0 + sg * dist / r
            return (c[0] + r * math.cos(a), c[1] + r * math.sin(a))
        dist -= L
    q = prims[-1]
    return q[2]


# ---------------- the paths ----------------
def corners_loop():
    return [(XL, YT), (XL, YB), (XR, YB), (XR, YT)]


ST1 = (ST1_X, YT); ST2 = (ST2_X, YT); DEPOT = (DEPOT_X, DEPOT_Y)

PATHS = {
    # ST1 -> ST2 along the top straight
    "top": fillet_path([ST1, ST2], [0, 0]),
    # ST2 -> right curve -> bottom straight (leftwards) -> left curve -> ST1
    "bottom": fillet_path([ST2, (XR, YT), (XR, YB), (XL, YB), (XL, YT), ST1],
                          [0, R_LOOP, R_LOOP, R_LOOP, R_LOOP, 0]),
    # DEPOT -> out of the left end -> spur down -> bottom straight -> left curve -> ST1
    "depot_out": fillet_path([DEPOT, (D_LEFT, DEPOT_Y), (J_LEFT, YB), (XL, YB), (XL, YT), ST1],
                             [0, R_SPUR, R_SPUR, R_LOOP, R_LOOP, 0]),
}
# the train turns off the bottom straight (coming from ST2) up the right spur into the depot
_spur_in = fillet_path([(J_RIGHT, YB), (D_RIGHT, DEPOT_Y), DEPOT], [0, R_SPUR, 0])
_in_switch = fillet_path([(XR, YB), (J_RIGHT, YB), (D_RIGHT, DEPOT_Y), DEPOT], [0, R_SPUR, R_SPUR, 0])
BRANCH_AT = 70.0    # mm along the spur from where it leaves the bottom straight
_branch_len = path_len(fillet_path([(XR, YB), (J_RIGHT, YB)], [0, 0])) + BRANCH_AT
BRANCH = point_at(_in_switch, _branch_len)
PATHS["depot_in"] = None   # set below: from BRANCH to DEPOT along _in_switch


def _sub_from(prims, d0):
    """primitives of `prims` from distance d0 to the end (only cuts inside a straight or arc)."""
    out, acc = [], 0.0
    for q in prims:
        L = prim_len(q)
        if acc + L <= d0:
            acc += L; continue
        if acc < d0:
            p = point_at([q], d0 - acc)
            if q[0] == "L":
                q = ("L", p, q[2])
            else:
                q = ("A", p, q[2], q[3], q[4], q[5])
        out.append(q); acc += L
    return out


PATHS["depot_in"] = _sub_from(_in_switch, _branch_len)

# calibration tags: on the left spur, first CAL0 then CAL END CAL_GAP further, both on the straight part
_out_len_to_spur = abs(DEPOT_X - D_LEFT) - R_SPUR * math.tan(math.radians(22.5))
CAL0_AT = _out_len_to_spur + 40.0
CAL0 = point_at(PATHS["depot_out"], CAL0_AT)
CAL100 = point_at(PATHS["depot_out"], CAL0_AT + CAL_GAP)

# whole drawn network (visual): the loop, plus the depot line with both spurs
LOOP_DRAW = fillet_path([(XL + R_LOOP, YT), (XR, YT), (XR, YB), (XL, YB), (XL, YT), (XL + R_LOOP + 1, YT)],
                        [0, R_LOOP, R_LOOP, R_LOOP, R_LOOP, 0])
DEPOT_DRAW = fillet_path([(J_LEFT - 60, YB), (J_LEFT, YB), (D_LEFT, DEPOT_Y), (D_RIGHT, DEPOT_Y), (J_RIGHT, YB), (J_RIGHT + 60, YB)],
                         [0, R_SPUR, R_SPUR, R_SPUR, R_SPUR, 0])

TAGS = {"ST1": ST1, "ST2": ST2, "DEPOT": DEPOT, "BRANCH": BRANCH, "CAL0": CAL0, "CAL100": CAL100}

SEG_LEN_M = {k: round(path_len(v) / 1000.0, 3) for k, v in PATHS.items()}

if __name__ == "__main__":
    print("mat", MAT_W, "x", MAT_H)
    print("segments (m):", SEG_LEN_M)
    print("tags:", {k: (round(v[0], 1), round(v[1], 1)) for k, v in TAGS.items()})
    print("cal gap check", round(_dist(CAL0, CAL100), 1))
