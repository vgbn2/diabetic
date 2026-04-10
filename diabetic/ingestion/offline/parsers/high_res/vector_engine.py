"""
vector_engine.py — pdfplumber Curve & Line Extraction
======================================================
Responsibilities:
  - Identify glucose curves and metabolic event markers from PDF vector objects.
  - Concatenate fragmented line segments into continuous traces.
  - Classify objects by color into channels: glucose | bolus | basal | meal.
"""
from __future__ import annotations
import numpy as np
from typing import List, Tuple

from .models import GlucoseCurve, EventMarker, RowBBox


# -------- Color Channel Constants ------------------------------------------

# (R, G, B) triplets matching Ottai export palette
_CH_GLUCOSE_RGB: List[Tuple[float, float, float]] = [
    (0.2314, 0.4706, 1.0),
    (1.0,    0.7216, 0.0),
    (1.0,    0.8667, 0.5294),
    (0.949,  0.1569, 0.1569),
    (1.0,    0.5686, 0.5686),
]
_MATCH_TOL = 0.06           # Color matching tolerance


def _classify_channel(obj: dict) -> str:
    """
    Return the metabolic channel of a PDF graphics object.
    Channels: 'glucose' | 'bolus' | 'basal' | 'meal' | 'unknown'
    """
    color = obj.get("stroking_color") or obj.get("non_stroking_color")
    pts_list = obj.get("pts", [])
    pts_count = len(pts_list)
    col_str = str(color)

    # Pattern-based (device-space pattern colors in pdfplumber begin with P)
    if "P" in col_str:
        if pts_count > 100 or pts_count > 80:
            return "glucose"
        if "P50" in col_str:
            return "bolus"
        return "meal" if pts_count < 30 else "basal"

    if not isinstance(color, (list, tuple)) or len(color) < 3:
        return "unknown"

    rc, gc, bc = float(color[0]), float(color[1]), float(color[2])

    # Explicit glucose blue variants (cover slight PDF rendering differences)
    if (bc > 0.8 and gc > 0.3 and rc < 0.4) or (bc > 0.9 and rc > 0.8):
        return "glucose"

    # Palette matching
    for ref in _CH_GLUCOSE_RGB:
        if (abs(rc - ref[0]) < _MATCH_TOL
                and abs(gc - ref[1]) < _MATCH_TOL
                and abs(bc - ref[2]) < _MATCH_TOL):
            return "glucose"

    if gc > 0.45 and rc < 0.4 and bc < 0.5:
        return "bolus"
    if rc > 0.4 and bc > 0.4 and gc < 0.5:
        return "basal"
    if rc > 0.7 and gc > 0.6 and bc < 0.5:
        return "meal"

    return "unknown"


# -------- Normalisation -----------------------------------------------------

def _obj_pts(obj: dict) -> List[Tuple[float, float]]:
    """Return point list for curves or synthesise from line AABB."""
    if "pts" in obj:
        return list(obj["pts"])
    return [(obj["x0"], obj["top"]), (obj["x1"], obj["bottom"])]


# -------- Main API ----------------------------------------------------------

def extract_row_vectors(
    page,
    row: RowBBox,
) -> Tuple[List[GlucoseCurve], List[EventMarker]]:
    """
    Extract glucose curves and event markers from a page for a single row bbox.

    Uses page-level curves + lines to include reports that rasterise the
    glucose trace as many tiny line segments rather than a single curve.
    """
    all_objects = list(page.curves) + list(page.lines)

    raw_glucose: List[dict] = []
    events: List[EventMarker] = []

    for obj in all_objects:
        pts = _obj_pts(obj)
        if not pts:
            continue
        ys = [p[1] for p in pts]
        c_top, c_bot = min(ys), max(ys)
        # Filter: object must overlap the row's vertical range
        if c_bot < row.y_start - 5 or c_top > row.y_end + 5:
            continue

        channel = _classify_channel(obj)
        if channel == "glucose":
            raw_glucose.append({"pts": pts})
        elif channel in ("bolus", "basal", "meal"):
            xs = [p[0] for p in pts]
            events.append(EventMarker(
                type=channel,
                x=float(np.mean(xs)),
                y=float(np.mean(ys)),
            ))

    # Process rects for event markers too
    for rect in page.rects:
        if not (row.y_start - 30 < rect["top"] < row.y_end + 60):
            continue
        channel = _classify_channel(rect)
        if channel in ("bolus", "basal", "meal"):
            events.append(EventMarker(
                type=channel,
                x=(rect["x0"] + rect["x1"]) / 2,
                y=(rect["top"] + rect["bottom"]) / 2,
            ))

    curves = _concatenate_segments(raw_glucose)
    return curves, events


def _concatenate_segments(
    segs: List[dict],
    gap_tol: float = 5.0,
    min_width: float = 5.0,
) -> List[GlucoseCurve]:
    """
    Merge adjacent glucose segments into continuous curves.

    `gap_tol`  — max distance (pts) between end of one segment and start of next.
    `min_width` — minimum X span for a curve to be accepted (filters stray dots).
    """
    if not segs:
        return []

    segs.sort(key=lambda s: min(p[0] for p in s["pts"]))

    chains: List[List[Tuple[float, float]]] = []
    curr = list(segs[0]["pts"])

    for seg in segs[1:]:
        nxt = seg["pts"]
        dx = abs(nxt[0][0] - curr[-1][0])
        dy = abs(nxt[0][1] - curr[-1][1])
        if dx < gap_tol and dy < gap_tol:
            curr.extend(nxt)
        else:
            chains.append(curr)
            curr = list(nxt)
    chains.append(curr)

    result = []
    for chain in chains:
        xs = [p[0] for p in chain]
        if (max(xs) - min(xs)) >= min_width:
            result.append(GlucoseCurve(pts=chain))
    return result
