"""
calibrator.py — The 'Crystal' Logic
====================================
Determines:
  1. ScaleAnchor  (Y-axis: glucose mmol/L)
  2. TemporalAnchor (X-axis: minutes since midnight)

Strategy cascade (highest fidelity first):
  - Scale:  Label pairs (0+10, 10+30) > single label > fallback
  - Time:   Text time-labels ("0 00", "6 00") > vertical gridlines > fallback
"""
from __future__ import annotations
import re
import numpy as np
from typing import List, Optional

from .models import ScaleAnchor, TemporalAnchor


# -------- Y-Axis (Glucose Scale) ------------------------------------------

def calibrate_scale(
    words: list,
    lines: list,
    y_start: float,
    y_end: float,
    page_width: float,
) -> Optional[ScaleAnchor]:
    """
    Detect the glucose Y-axis scale using label words on the left margin.
    Label margin is first searched within the row bbox, then globally.

    Returns None only if no calibration data exists at all.
    """
    def _labels_in_bbox(ws, x_max=100):
        return [
            w for w in ws
            if w["text"] in ("0", "10", "30")
            and w["x0"] < x_max
        ]

    # 1. Local row search
    local = [w for w in _labels_in_bbox(words) if y_start < w["top"] < y_end]

    # 2. Global page search fallback
    candidates = local if local else _labels_in_bbox(words)

    y_map: dict[int, list] = {}
    for w in candidates:
        val = int(w["text"])
        y_map.setdefault(val, []).append(w["top"])
    
    # Clustering: if a page has 4 rows, we'll see multiple labels for '10'.
    # Pick the one closest to y_start for this specific row.
    averaged = {}
    for val, ys in y_map.items():
        relevant = [y for y in ys if y_start - 20 < y < y_start + 200]
        if relevant:
            averaged[val] = float(np.mean(relevant))
        elif ys:
            # Fallback to absolute closest if nothing in range
            averaged[val] = float(ys[np.argmin(np.abs(np.array(ys) - y_start))])

    if 0 in averaged and 10 in averaged:
        v0, v10 = averaged[0], averaged[10]
        # BINGO: Grid Snapping Logic
        # Text is usually ~4.05 pts above the actual grid line in some Ottai reports.
        # We find the nearest horizontal vector line within 6pts of the text.
        grid_0 = [l for l in lines if abs(l.get('top', 0) - v0) < 6.0 and abs(l.get('top', 0) - l.get('bottom', 0)) < 0.2]
        grid_10 = [l for l in lines if abs(l.get('top', 0) - v10) < 6.0 and abs(l.get('top', 0) - l.get('bottom', 0)) < 0.2]
        
        y0 = grid_0[0]['top'] if grid_0 else v0
        y10 = grid_10[0]['top'] if grid_10 else v10
        
        ppm = (y0 - y10) / 10.0
        return ScaleAnchor(zero_y=y0, pts_per_mmol=ppm,
                           source="grid_labels" if grid_0 else "text_labels")

    if 10 in averaged and 30 in averaged:
        v10, v30 = averaged[10], averaged[30]
        grid_10 = [l for l in lines if abs(l.get('top', 0) - v10) < 6.0 and abs(l.get('top', 0) - l.get('bottom', 0)) < 0.2]
        grid_30 = [l for l in lines if abs(l.get('top', 0) - v30) < 6.0 and abs(l.get('top', 0) - l.get('bottom', 0)) < 0.2]
        
        y10 = grid_10[0]['top'] if grid_10 else v10
        y30 = grid_30[0]['top'] if grid_30 else v30
        
        ppm = (y10 - y30) / 20.0
        return ScaleAnchor(zero_y=y10 + 10.0 * ppm, pts_per_mmol=ppm,
                           source="grid_labels" if grid_10 else "text_labels")

    # Complete fallback — geometric estimate
    chart_height = max(1.0, y_end - y_start)
    return ScaleAnchor(
        zero_y=y_start + chart_height * 0.8,
        pts_per_mmol=PPM_DEFAULT,
        source="fallback",
    )


# -------- X-Axis (Temporal Calibration) ------------------------------------

_TIME_WORD_RE = re.compile(r"^(\d{1,2})[:\s](\d{2})$")
_HOUR_WORD_RE = re.compile(r"^(\d{1,2})$")


def calibrate_time(
    words: list,
    lines: list,
    y_start: float,
    y_end: float,
    x_start: float,
    x_end: float,
) -> TemporalAnchor:
    """
    Detect the temporal X-axis using one of:
      1. HH:MM time labels printed above the chart
      2. Vertical grid lines (equally spaced tick marks)
      3. Fallback: use cell x_start / x_end as chart bounds

    Returns a TemporalAnchor with left_x (00:00) and right_x (23:59).
    """
    # --- Strategy 1: Time labels ---
    time_words = []
    for w in words:
        # Accept labels in the row's header band (10 pts above y_start)
        if not (y_start - 25 < w["top"] < y_start + 40):
            continue
        if not (x_start - 10 <= w["x0"] <= x_end + 10):
            continue
        m = _TIME_WORD_RE.match(w["text"])
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            time_words.append((w["x0"], hour * 60 + minute))
        # Single-digit hour labels (bare "0", "6", "12" etc.)
        m2 = _HOUR_WORD_RE.match(w["text"])
        if m2 and int(m2.group(1)) in (0, 3, 6, 9, 12, 15, 18, 21):
            hour = int(m2.group(1))
            time_words.append((w["x0"], hour * 60))

    if len(time_words) >= 2:
        time_words.sort(key=lambda t: t[0])
        # Linear regression: x -> minutes
        xs = np.array([t[0] for t in time_words])
        ms = np.array([t[1] for t in time_words])
        if np.ptp(xs) > 5:
            slope = np.polyfit(xs, ms, 1)   # [minutes/pt, intercept]
            # Solve for x at minutes=0 and minutes=1440
            pts_per_min = 1.0 / slope[0] if abs(slope[0]) > 1e-6 else 1.0
            left  = -slope[1] / slope[0]
            right = (1440 - slope[1]) / slope[0]
            return TemporalAnchor(left_x=left, right_x=right, source="time_labels")

    # --- Strategy 2: Vertical gridlines ---
    vlines = []
    for ln in lines:
        if abs(ln.get("x0", 0) - ln.get("x1", 0)) < 1.5:  # vertical
            mid_y = (ln.get("top", 0) + ln.get("bottom", 0)) / 2
            if y_start < mid_y < y_end:
                height = ln.get("bottom", 0) - ln.get("top", 0)
                if height > (y_end - y_start) * 0.4:  # spans at least 40% of row
                    vlines.append(ln.get("x0", 0))

    if len(vlines) >= 2:
        vlines_sorted = sorted(set(round(x, 1) for x in vlines))
        # Cluster nearby lines
        clustered = _cluster(vlines_sorted, tol=3.0)
        if len(clustered) >= 2:
            # Assume evenly spaced hours, detect period
            gaps = np.diff(clustered)
            median_gap = float(np.median(gaps))
            # Standard Ottai: 4 gridlines in 24h → 6h gap
            if len(clustered) == 4:
                # gridlines at 0, 6, 12, 18 hours
                left  = clustered[0]
                right = clustered[0] + median_gap * 4
            else:
                left  = clustered[0]
                right = clustered[-1] + median_gap   # extend to 24h
            return TemporalAnchor(left_x=left, right_x=right, source="gridlines")

    # --- Strategy 3: Fallback ---
    return TemporalAnchor(left_x=x_start, right_x=x_end, source="fallback")


def _cluster(vals: list, tol: float) -> list:
    """Merge values within `tol` of each other into their mean."""
    if not vals:
        return []
    groups, curr = [], [vals[0]]
    for v in vals[1:]:
        if v - curr[-1] <= tol:
            curr.append(v)
        else:
            groups.append(float(np.mean(curr)))
            curr = [v]
    groups.append(float(np.mean(curr)))
    return groups
