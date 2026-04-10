"""
Shared data structures for the high-res parser pipeline.
All engines communicate through these typed dicts/dataclasses.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple


# -----------------------------------------------------------------
# Primitive coordinate types
# -----------------------------------------------------------------
Point = Tuple[float, float]   # (x, y) in PDF points


@dataclass
class ScaleAnchor:
    """Y-axis glucose scale calibration result."""
    zero_y: float           # PDF Y coordinate of glucose == 0 mmol/L
    pts_per_mmol: float     # PDF points per 1 mmol/L (Y axis)
    source: str = "labels"  # "labels" | "gridlines" | "fallback"


@dataclass
class TemporalAnchor:
    """X-axis time calibration result."""
    left_x: float           # PDF X of 00:00
    right_x: float          # PDF X of 23:59
    source: str = "labels"  # "labels" | "gridlines" | "fallback"

    def x_to_minutes(self, x: float) -> float:
        """Convert PDF X coordinate to minutes since midnight (0-1440)."""
        span = max(1.0, self.right_x - self.left_x)
        rel = (x - self.left_x) / span
        return max(0.0, min(1439.99, rel * 1440.0))


@dataclass
class RowBBox:
    """Vertical bounding box for one chart row on a page."""
    y_start: float
    y_end: float
    page_idx: int


@dataclass
class GlucoseCurve:
    """A single extracted glucose curve segment."""
    pts: List[Point]


@dataclass
class EventMarker:
    """A single bolus / basal / meal event."""
    type: str            # "bolus" | "basal" | "meal"
    x: float
    y: float


@dataclass
class DayCell:
    """One calendar day's extraction result."""
    date: datetime
    scale: ScaleAnchor
    time_anchor: TemporalAnchor
    glucose_curves: List[GlucoseCurve] = field(default_factory=list)
    events: List[EventMarker] = field(default_factory=list)

    def to_records(self) -> list:
        """Flatten into a list of row dicts for DataFrame construction."""
        from datetime import timedelta
        import numpy as np
        records = []
        seen_minutes: set = set()

        for curve in self.glucose_curves:
            for px, py in curve.pts:
                if not (self.time_anchor.left_x - 3 <= px <= self.time_anchor.right_x + 3):
                    continue
                minutes = self.time_anchor.x_to_minutes(px)
                glucose = (self.scale.zero_y - py) / max(0.01, self.scale.pts_per_mmol)
                if not (0.5 < glucose < 40.0):
                    continue
                # Round to nearest 0.5-minute bucket to deduplicate
                bucket = round(minutes * 2) / 2
                if bucket in seen_minutes:
                    continue
                seen_minutes.add(bucket)
                ts = self.date + timedelta(minutes=minutes)
                records.append({
                    "timestamp": ts,
                    "glucose": round(float(glucose), 3),
                    "bolus": 0, "basal": 0, "meal": 0,
                })

        for ev in self.events:
            if not (self.time_anchor.left_x - 3 <= ev.x <= self.time_anchor.right_x + 3):
                continue
            minutes = self.time_anchor.x_to_minutes(ev.x)
            ts = self.date + timedelta(minutes=minutes)
            row = {"timestamp": ts, "glucose": float("nan"),
                   "bolus": 0, "basal": 0, "meal": 0}
            row[ev.type] = 1
            records.append(row)

        return records
