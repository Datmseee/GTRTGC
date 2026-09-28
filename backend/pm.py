"""Preventive-maintenance logic.

For each cycle (2K ... 360K km) the next PM is due at  last_pm_km + cycle.
A higher-level PM also counts for every lower level (a 40K check includes the 13K and 2K
checks), so "last PM" for a cycle is the latest PM of that level or any higher level.

Status per cycle (same thresholds as the dashboard):
  over - due mileage reached and no PM recorded since
  soon - less than 8% of the cycle remaining
  ok   - otherwise
"""
import config

LABEL_TO_CYCLE = dict(zip(config.PM_LABELS, config.PM_CYCLES))


def cycle_status(km, cycle, last_pm_km):
    due_at = last_pm_km + cycle
    remaining = due_at - km
    if remaining <= 0:
        status = "over"
    elif remaining < cycle * config.PM_SOON_FRACTION:
        status = "soon"
    else:
        status = "ok"
    pct = max(0, min(100, int((km - last_pm_km) / cycle * 100)))
    return {"due_at": round(due_at, 1), "remaining": round(remaining, 1), "status": status, "pct": pct}


def last_pm_per_cycle(pm_rows):
    """pm_rows: iterable of (pm_type, mileage_at_pm). Returns {cycle: last_km}."""
    last = {c: 0.0 for c in config.PM_CYCLES}
    for pm_type, km in pm_rows:
        done_cycle = LABEL_TO_CYCLE.get(pm_type)
        if done_cycle is None:
            continue
        for c in config.PM_CYCLES:
            if c <= done_cycle and km > last[c]:
                last[c] = km
    return last


def pm_summary(km, pm_rows):
    """Returns (worst, cycles). `worst` has the same shape as getPMStatus() in the dashboard."""
    last = last_pm_per_cycle(pm_rows)
    cycles = []
    for c, label in zip(config.PM_CYCLES, config.PM_LABELS):
        info = cycle_status(km, c, last[c])
        info.update({"name": f"{label} PM", "label": label, "cycle": c, "last_pm_km": last[c]})
        cycles.append(info)

    rank = {"over": 0, "soon": 1, "ok": 2}
    # on a tie prefer the bigger PM: it also covers the smaller ones
    worst = min(cycles, key=lambda x: (rank[x["status"]], x["remaining"], -x["cycle"]))
    return {k: worst[k] for k in ("name", "remaining", "status", "pct", "due_at")}, cycles
