"""Floor mat: 6 x A3 landscape tiles (3 x 2, 12 mm overlap), dark (dashboard) and light (ink saver)."""
import math, os, sys
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Rectangle, Polygon
import layout as Ly

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "mat")
os.makedirs(OUT, exist_ok=True)
MM = 1 / 25.4
PT_PER_MM = 72 / 25.4

THEMES = {
    "dark": dict(bg="#0b1220", grid="#13203a", loop="#1a9a80", depot="#4a6a8c", core="#0b1220",
                 txt0="#d6e6f0", txt1="#7d9cb8", tag="#00d4e8", tagfill="#0b1220", foot="#5a7a98",
                 title="#00d4e8", arrow="#7fe0c8"),
    "light": dict(bg="#ffffff", grid="#e8eef3", loop="#1a9a80", depot="#7d93aa", core="#ffffff",
                  txt0="#102030", txt1="#4a6680", tag="#0096a8", tagfill="#ffffff", foot="#7d93aa",
                  title="#0b6f7c", arrow="#1a9a80"),
}
RAIL_W, CORE_W = 46.0, 20.0     # mm


def line(ax, pts, color, w_mm, z, ls="-", cap="round", alpha=1.0):
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=color, lw=w_mm * PT_PER_MM, solid_capstyle=cap, solid_joinstyle="round",
            linestyle=ls, zorder=z, alpha=alpha)


def text(ax, x, y, s, size_mm, color, weight="normal", ha="center", va="center", family="DejaVu Sans", z=20, spacing=None):
    ax.text(x, y, s, fontsize=size_mm * PT_PER_MM, color=color, ha=ha, va=va, fontweight=weight,
            family=family, zorder=z)


def diamond(ax, p, r, th, z=15):
    d = [(p[0], p[1] + r), (p[0] + r, p[1]), (p[0], p[1] - r), (p[0] - r, p[1])]
    ax.add_patch(Polygon(d, closed=True, fc=th["tagfill"], ec=th["tag"], lw=1.4 * PT_PER_MM, zorder=z))


def chevron(ax, prims, at, th, size=9.0):
    p = Ly.point_at(prims, at); q = Ly.point_at(prims, at + 1.0)
    a = math.atan2(q[1] - p[1], q[0] - p[0])
    c, s = math.cos(a), math.sin(a)
    pts = [(-size * 0.6, size * 0.7), (size * 0.6, 0), (-size * 0.6, -size * 0.7)]
    pts = [(p[0] + x * c - y * s, p[1] + x * s + y * c) for x, y in pts]
    xs, ys = zip(*pts)
    ax.plot(xs, ys, color=th["arrow"], lw=2.2 * PT_PER_MM, solid_capstyle="round", solid_joinstyle="round", zorder=12)


def draw(ax, th):
    W, H = Ly.MAT_W, Ly.MAT_H
    ax.add_patch(Rectangle((-50, -50), W + 100, H + 100, fc=th["bg"], ec="none", zorder=0))
    for x in range(0, int(W) + 1, 50):
        ax.plot([x, x], [-50, H + 50], color=th["grid"], lw=0.25 * PT_PER_MM, zorder=1)
    for y in range(0, int(H) + 1, 50):
        ax.plot([-50, W + 50], [y, y], color=th["grid"], lw=0.25 * PT_PER_MM, zorder=1)

    # track: coloured rail + dark core, like the dashboard
    depot = Ly.sample(Ly.DEPOT_DRAW); loop = Ly.sample(Ly.LOOP_DRAW)
    line(ax, depot, th["depot"], RAIL_W, 4)
    line(ax, loop, th["loop"], RAIL_W, 5)
    line(ax, depot, th["core"], CORE_W, 6)
    line(ax, loop, th["core"], CORE_W, 6)

    # running direction
    L = Ly.path_len(Ly.PATHS["bottom"])
    for f in (0.15, 0.45, 0.62, 0.9):
        chevron(ax, Ly.PATHS["bottom"], L * f, th)
    chevron(ax, Ly.PATHS["top"], Ly.path_len(Ly.PATHS["top"]) * 0.5, th)
    chevron(ax, Ly.PATHS["depot_in"], Ly.path_len(Ly.PATHS["depot_in"]) * 0.35, th, 7)
    chevron(ax, Ly.PATHS["depot_out"], Ly.CAL0_AT + 50, th, 7)

    # prop footprints (dashed) so everything goes back in the same place
    for sid, (name, sx) in Ly.STATIONS.items():
        cy = Ly.YT + Ly.ST_TRACK_OFFSET
        x0, x1, y0, y1 = Ly.ST_PLAT
        tx0, tx1, ty0, ty1 = Ly.ST_TOWER
        outline = [(sx + x0, cy + y0), (sx + tx1, cy + y0), (sx + tx1, cy + ty1), (sx + x0, cy + y1), (sx + x0, cy + y0)]
        outline = [(sx + x0, cy + y0), (sx + x1, cy + y0), (sx + x1, cy + ty0), (sx + tx1, cy + ty0),
                   (sx + tx1, cy + ty1), (sx + x0, cy + y1), (sx + x0, cy + y0)]
        line(ax, outline, th["foot"], 0.8, 8, ls=(0, (6, 4)), cap="butt")
        text(ax, sx, cy + 4, name, 17, th["txt0"], weight="bold")
        text(ax, sx, cy - 15, f"{sid}  STATION", 6.5, th["txt1"], family="DejaVu Sans Mono")
        # name again inside the loop, always visible
        text(ax, sx, Ly.YT - 48, f"{sid}  {name}", 9, th["txt0"], weight="bold", family="DejaVu Sans Mono")
    x0, x1, y0, y1 = Ly.DEPOT_FOOT
    dx, dy = Ly.DEPOT_X, Ly.DEPOT_Y
    line(ax, [(dx + x0, dy + y0), (dx + x1, dy + y0), (dx + x1, dy + y1), (dx + x0, dy + y1), (dx + x0, dy + y0)],
         th["foot"], 0.8, 8, ls=(0, (6, 4)), cap="butt")
    text(ax, dx, dy + 78, Ly.DEPOT_NAME, 12, th["txt0"], weight="bold")
    text(ax, dx, dy + 62, "MAIN MAINTENANCE BUILDING (MMB)", 5.5, th["txt1"], family="DejaVu Sans Mono")

    # RFID card spots
    lbl = {"ST1": ("ST1", (0, -34)), "ST2": ("ST2", (0, -34)), "DEPOT": ("DEPOT", (0, -34)),
           "BRANCH": ("BRANCH", (34, -4)), "CAL0": ("CAL 0", (-38, 8)), "CAL100": ("CAL END", (38, -8))}
    for k, p in Ly.TAGS.items():
        diamond(ax, p, 8.5, th)
        s, (ox, oy) = lbl[k]
        if k in ("ST1", "ST2"):
            continue        # station name label already sits right there
        ha = "left" if ox > 0 else "right" if ox < 0 else "center"
        text(ax, p[0] + ox, p[1] + oy, s, 5.5, th["tag"], weight="bold", ha=ha, family="DejaVu Sans Mono")

    # title
    tx, ty = Ly.XL + 52, 372
    text(ax, tx, ty, "SPLRT MILEAGE TRACKING", 15, th["title"], weight="bold", ha="left")
    text(ax, tx, ty - 22, "Live demo track  ·  Sengkang Punggol LRT", 7, th["txt1"], ha="left")
    text(ax, tx, ty - 36, "Every wheel turn and RFID read appears on the dashboard", 5.5, th["txt1"], ha="left")

    # legend
    lx, ly = 805, 372
    text(ax, lx, ly, "LEGEND", 6, th["txt1"], weight="bold", ha="left", family="DejaVu Sans Mono")
    rows = [("loop", "Main line loop"), ("depot", "Depot track"), ("tag", "RFID tag point"),
            ("foot", "Station / depot model"), ("arrow", "Direction of travel")]
    for i, (k, s) in enumerate(rows):
        y = ly - 17 - i * 15
        if k in ("loop", "depot"):
            line(ax, [(lx, y), (lx + 26, y)], th[k], 9, 9, cap="butt")
            line(ax, [(lx, y), (lx + 26, y)], th["core"], 3.5, 10, cap="butt")
        elif k == "tag":
            diamond(ax, (lx + 13, y), 5, th)
        elif k == "foot":
            line(ax, [(lx, y - 4), (lx + 26, y - 4), (lx + 26, y + 4), (lx, y + 4), (lx, y - 4)], th["foot"], 0.6, 9,
                 ls=(0, (3, 2)), cap="butt")
        else:
            xs = [lx + 9, lx + 17, lx + 9]; ys = [y + 5, y, y - 5]
            ax.plot(xs, ys, color=th["arrow"], lw=1.8 * PT_PER_MM, solid_capstyle="round", zorder=12)
        text(ax, lx + 34, y, s, 6, th["txt0"], ha="left")


def tile_window(c, r):
    x0 = c * (Ly.SHEET_W - Ly.OVERLAP)
    y1 = Ly.MAT_H - r * (Ly.SHEET_H - Ly.OVERLAP)
    return x0, y1 - Ly.SHEET_H


def tile_marks(ax, c, r, th):
    x0, y0 = tile_window(c, r)
    cutc = "#ff3a5c"
    code = f"{'ABC'[c]}{r + 1}"
    if c > 0:
        ax.plot([x0 + 6, x0 + 6], [y0, y0 + Ly.SHEET_H], color=cutc, lw=0.35 * PT_PER_MM, ls=(0, (2, 2)), zorder=50)
        text(ax, x0 + 9, y0 + Ly.SHEET_H / 2, "✂ cut, lay over the sheet on the left", 3.2, cutc, ha="left", z=51)
    if r > 0:
        ax.plot([x0, x0 + Ly.SHEET_W], [y0 + Ly.SHEET_H - 6] * 2, color=cutc, lw=0.35 * PT_PER_MM, ls=(0, (2, 2)), zorder=50)
        text(ax, x0 + Ly.SHEET_W / 2, y0 + Ly.SHEET_H - 9, "✂ cut, lay over the sheet above", 3.2, cutc, va="top", z=51)
    text(ax, x0 + Ly.SHEET_W - 9, y0 + 9, f"SHEET {code}  ·  print at 100% (actual size)", 3.2, th["txt1"], ha="right", z=51)


def page(fig_w, fig_h):
    fig = plt.figure(figsize=(fig_w * MM, fig_h * MM))
    ax = fig.add_axes([0, 0, 1, 1]); ax.set_axis_off()
    return fig, ax


def build(theme):
    th = THEMES[theme]
    pdf_path = f"{OUT}/SGRTGC_floor_mat_{theme}_6xA3.pdf"
    with PdfPages(pdf_path) as pdf:
        for r in range(Ly.ROWS):
            for c in range(Ly.COLS):
                fig, ax = page(Ly.SHEET_W, Ly.SHEET_H)
                draw(ax, th); tile_marks(ax, c, r, th)
                x0, y0 = tile_window(c, r)
                ax.set_xlim(x0, x0 + Ly.SHEET_W); ax.set_ylim(y0, y0 + Ly.SHEET_H)
                pdf.savefig(fig); plt.close(fig)
    fig, ax = page(Ly.MAT_W, Ly.MAT_H)
    draw(ax, th); ax.set_xlim(0, Ly.MAT_W); ax.set_ylim(0, Ly.MAT_H)
    fig.savefig(f"{OUT}/SGRTGC_floor_mat_{theme}_preview.png", dpi=40)
    plt.close(fig)
    return pdf_path


if __name__ == "__main__":
    for t in sys.argv[1:] or ["dark", "light"]:
        print(build(t))
