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

    # Palette matching (ONLY include variants that are confirmed to be glucose)
    # Avoid red/orange if they overlap with event colors too much.
    for ref in _CH_GLUCOSE_RGB:
        if (abs(rc - ref[0]) < 0.03
                and abs(gc - ref[1]) < 0.03
                and abs(bc - ref[2]) < 0.03):
            return "glucose"

    # More specific event colors
    if rc > 0.8 and gc < 0.4 and bc > 0.5: # Purple-ish
        return "bolus"
    if rc > 0.8 and gc > 0.6 and bc < 0.4: # Orange-ish
        return "meal"
    if bc > 0.4 and rc < 0.3 and gc < 0.5: # Blue-grey
        return "basal"

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
    trace_mask: Optional[np.ndarray] = None,
) -> Tuple[List[GlucoseCurve], List[EventMarker]]:
    """
    Extract glucose curves and event markers from a page for a single row bbox.
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

    curves = _concatenate_segments(raw_glucose, trace_mask=trace_mask)
    return curves, events


def _concatenate_segments(
    segs: List[dict],
    gap_tol: float = 5.0,
    min_width: float = 5.0,
    trace_mask: Optional[np.ndarray] = None,
) -> List[GlucoseCurve]:
    """
    Merge adjacent glucose segments into continuous curves.
    Uses an optional vision-based trace_mask to filter out grid-line interference.
    """
    if not segs:
        return []

    # Scale factor for mapping PDF pts -> Mask pixels
    _V_SCALE = 400 / 72.0 

    filtered = []
    for s in segs:
        pts = s["pts"]
        all_x = [p[0] for p in pts]
        all_y = [p[1] for p in pts]
        dx = max(all_x) - min(all_x)
        dy = max(all_y) - min(all_y)
        
        # 1. Vision-Guided Validation
        if trace_mask is not None:
            # Check the centroid of the segment in mask space
            cx, cy = np.mean(all_x), np.mean(all_y)
            mx, my = int(cx * _V_SCALE), int(cy * _V_SCALE)
            
            # Bounds check for mask
            if 0 <= my < trace_mask.shape[0] and 0 <= mx < trace_mask.shape[1]:
                # If the mask is 0 (grid removed), skip this segment
                if trace_mask[my, mx] == 0:
                    continue
        
        # 2. Geometric Constraints (Legacy Fallback/Refinement)
        if dx < 0.05:
            if dy < 4.0:
                cx = sum(all_x) / len(all_x)
                cy = sum(all_y) / len(all_y)
                filtered.append({"pts": [(cx, cy)]})
        else:
            if (dy / max(0.01, dx)) < 15.0 and dy < 15.0:
                filtered.append(s)
    
    if not filtered: return []
    filtered.sort(key=lambda s: min(p[0] for p in s["pts"]))

    chains: List[List[Tuple[float, float]]] = []
    curr = list(filtered[0]["pts"])

    for seg in filtered[1:]:
        nxt = seg["pts"]
        dx = abs(nxt[0][0] - curr[-1][0])
        dy = abs(nxt[0][1] - curr[-1][1])
        
        # Sawtooth prevention: don't join if Y-jump is too large relative to X
        # Physiological limit: max ~1 mmol/L per minute. 
        # In PDF terms: if dy >> dx, it's a jump.
        if dx < gap_tol and dy < (gap_tol * 3): 
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
