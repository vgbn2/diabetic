"""
orchestrator.py — Slim High-Res Parser (Phase 1.5)
====================================================
Wires together:
  - calibrator   (Crystal Y/X scale detection)
  - vector_engine (pdfplumber curve/line extraction)
  - vision_engine (OpenCV icon detection — lazy)

Output: list of record dicts → DataFrame → CSV
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import numpy as np
import pandas as pd
import pdfplumber

from .calibrator import calibrate_scale, calibrate_time
from .models import DayCell, GlucoseCurve, EventMarker, RowBBox, TemporalAnchor
from .vector_engine import extract_row_vectors
from .vision_engine import VisionEngine


VN_MONTH = {
    "th01": 1, "th1": 1, "thg 1": 1, "thg 01":1,
    "th02": 2, "th2": 2, "thg 2": 2, "thg 02":2,
    "th03": 3, "th3": 3, "thg 3": 3, "thg 03":3,
    "th04": 4, "th4": 4, "thg 4": 4, "thg 04":4,
    "th05": 5, "th5": 5, "thg 5": 5, "thg 05":5,
    "th06": 6, "th6": 6, "thg 6": 6, "thg 06":6,
    "th07": 7, "th7": 7, "thg 7": 7, "thg 07":7,
    "th08": 8, "th8": 8, "thg 8": 8, "thg 08":8,
    "th09": 9, "th9": 9, "thg 9": 9, "thg 09":9,
    "th10": 10, "thg 10": 10,
    "th11": 11, "thg 11": 11,
    "th12": 12, "thg 12": 12,
}
# Supports: '25-Th03', '25 Th03', '25/03', '25 thg 03'
_DATE_PATTERN = re.compile(r"(\d{1,2})[-/\s]+((?:th\d{2}|thg\s+\d{1,2}|th\d{1,2}|jan|feb|fed|mar|apr|may|jun|jul|aug|sep|oct|nov|dec|tháng\s+\d{1,2}))(?:[-/\s]+(\d{4}))?", re.IGNORECASE)
_YEAR_PATTERN = re.compile(r"\b(202\d)\b")


def _parse_vn_date(day_str: str, month_str: str, year_str: Optional[str], default_year: int) -> Optional[datetime]:
    try:
        y = int(year_str) if year_str else default_year
        m_key = month_str.lower().strip()
        
        # English/Typo support: Feb, Fed, Mar, etc.
        m_map = {
            "jan": 1, "feb": 2, "fed": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
            "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12
        }
        for k, v in m_map.items():
            if k in m_key:
                return datetime(y, v, int(day_str))

        # Numeric month (like '03' in '25/03')
        if m_key.isdigit():
            return datetime(y, int(m_key), int(day_str))
            
        month = VN_MONTH.get(m_key)
        if not month:
            # Try to extract the number if it's 'Th03'
            digits = re.findall(r"\d+", m_key)
            if digits: month = int(digits[0])
            
        if month:
            return datetime(y, month, int(day_str))
    except Exception: pass
    return None


class HighResParser:
    """
    Modular high-resolution glucose parser for Ottai clinical PDF reports.
    """

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        self._records: List[dict] = []
        self._vision: Optional[VisionEngine] = None
        self._prev_date: Optional[datetime] = None  # Cross-page continuation

    def parse(self) -> "HighResParser":
        active_path = self._maybe_normalize(self.pdf_path)
        self._vision = VisionEngine(active_path)
        print(f"[parser] Processing: {active_path.name}")

        self._prev_date = None
        with pdfplumber.open(active_path) as pdf:
            for page_idx, raw_page in enumerate(pdf.pages):
                page = self._localize(raw_page)
                print(f"  Page {page_idx + 1}/{len(pdf.pages)}", end="\r")
                self._process_page(page, page_idx, "normalized" in active_path.name.lower())
        print()
        return self

    def save_csv(self, output_path: str | Path, date_range: tuple = None) -> Path:
        """Save extracted data to CSV.
        
        Args:
            output_path: Where to save the CSV.
            date_range: Optional (start_date, end_date) tuple to filter records.
                        Both should be datetime objects. Records outside this range are dropped.
        """
        output_path = Path(output_path)
        if not self._records:
            print("[parser] No data extracted.")
            return output_path

        df = pd.DataFrame(self._records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        
        # --- Date Range Filter ---
        if date_range:
            start, end = date_range
            before = len(df)
            df = df[(df["timestamp"] >= pd.Timestamp(start)) & (df["timestamp"] <= pd.Timestamp(end))]
            dropped = before - len(df)
            if dropped > 0:
                print(f"[parser] Date filter: dropped {dropped} out-of-range records")
        
        # --- Global Clinical Binning & Smoothing ---
        # Ottai clinical reports have ~2.5min native resolution. 
        # 5-minute bins ensure a rock-solid clinical trace.
        
        # 1. Round to 5-min buckets
        df["time_group"] = df["timestamp"].dt.round("5min")
        
        # 2. Separate Glucose and Events
        glu = df[df["glucose"].notna()].copy()
        evs = df[df["glucose"].isna()].copy()
        
        # 3. Aggregate Glucose by Median (Sawtooth Killer)
        if not glu.empty:
            # Re-bin to 5-min intervals and take median to kill noise spikes
            glu = glu.groupby("time_group").agg({
                "timestamp": "first",
                "glucose": "median",
                "bolus": "max", "basal": "max", "meal": "max"
            }).reset_index(drop=True)
            
            # Smoothing (light rolling median)
            glu["glucose"] = glu["glucose"].rolling(window=3, center=True).median().fillna(glu["glucose"])

        # 4. Integrate Events (ensure they aren't lost)
        final_df = pd.concat([glu, evs], sort=False).sort_values("timestamp")
        
        # Ensure final timestamps are strictly 5-min aligned for the clinical trace
        final_df["timestamp"] = final_df["timestamp"].dt.floor("5min")
        final_df = final_df.sort_values("glucose", ascending=False) # Keep highest glucose in collision
        final_df = final_df.drop_duplicates(subset=["timestamp"], keep="first").sort_values("timestamp")
        
        final_df.to_csv(output_path, index=False)
        print(f"[parser] Saved {len(final_df)} binned clinical rows -> {output_path}")
        return output_path

    def _maybe_normalize(self, path: Path) -> Path:
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) == 1 and pdf.pages[0].height > 2000:
                print("[parser] Detected Share format — normalising...")
                try:
                    from diabetic.ingestion.offline.normalize_ottai_share import normalize_share_report
                    norm = normalize_share_report(path)
                    if norm and norm.exists():
                        return norm
                except ImportError: pass
        return path

    @staticmethod
    def _localize(raw_page) -> object:
        try: return raw_page.within_bbox(raw_page.cropbox)
        except Exception: return raw_page

    def _process_page(self, page, page_idx: int, is_share_normalized: bool = False):
        words = page.extract_words()
        if not words: return

        # --- Coordinate Origin Flattening ---
        # Shift all elements so the topmost word starts at y≈0.
        # Normalized long-scrolls can have negative or very large min_y.
        min_y = min(w["top"] for w in words)
        if abs(min_y) > 5:  # Shift for any non-trivial offset
            for w in words:
                w["top"] -= min_y
                w["bottom"] -= min_y

        text = " ".join(w["text"] for w in words).lower()
        lines = page.lines
        curves = page.curves
        
        # Shift lines and curves too
        if abs(min_y) > 5:
            for l in lines:
                if "top" in l: l["top"] -= min_y; l["bottom"] -= min_y
                if "y0" in l: l["y0"] -= min_y; l["y1"] -= min_y
            for c in curves:
                if "top" in c: c["top"] -= min_y; c["bottom"] -= min_y
                if "y0" in c: c["y0"] -= min_y; c["y1"] -= min_y
                if "pts" in c:
                    c["pts"] = [(p[0], p[1] - min_y) for p in c["pts"]]

        year_m = _YEAR_PATTERN.search(text)
        year = int(year_m.group(1)) if year_m else datetime.now().year

        recon = " ".join(w["text"] for w in words)
        spans = _build_word_spans(words)
        raw_headers = _find_date_headers(recon, spans, words, year, is_share_normalized)
        if not raw_headers: return
        
        print(f"    Dates: {[h['date'].strftime('%m-%d') for h in raw_headers]}")

        raw_headers.sort(key=lambda h: h["coords"]["top"])
        rows = _group_into_rows(raw_headers)

        # --- Cross-Page Continuation ---
        # On normalized two-date pages, the second day's chart extends onto
        # the next page. That next page starts with orphaned curves (no header).
        # If we have a _prev_date and there are curves ABOVE the first header,
        # recover them as a continuation of the previous day.
        first_header_y = rows[0][0]["coords"]["top"]
        if self._prev_date and first_header_y > 10:
            # Relaxed threshold: recover orphans even on tightly packed pages
            orphan_bbox = RowBBox(y_start=0, y_end=first_header_y - 5, page_idx=page_idx)
            orphan_curves, orphan_events = extract_row_vectors(page, orphan_bbox)
            if orphan_curves:
                # Use the previous page's scale/time calibration for these curves
                orphan_scale = calibrate_scale(words, lines, 0, first_header_y - 5, page.width)
                orphan_time = calibrate_time(words, lines, 0, first_header_y - 5, 0, page.width)
                if orphan_scale:
                    cell = DayCell(
                        date=self._prev_date,
                        scale=orphan_scale,
                        time_anchor=orphan_time,
                        glucose_curves=orphan_curves,
                        events=orphan_events,
                    )
                    cont_records = cell.to_records()
                    if cont_records:
                        print(f"    [continuation] +{len(cont_records)} records for {self._prev_date.strftime('%m-%d')}")
                        self._records.extend(cont_records)

        for row_idx, row_headers in enumerate(rows):
            row_headers.sort(key=lambda h: h["coords"]["x0"])
            y_start = row_headers[0]["coords"]["top"]
            y_end = _compute_y_end(row_idx, rows, page, words, y_start)

            labels = [w for w in words if y_start - 30 < w["top"] < y_end + 30 and w["x0"] < 100]
            numeric_scales = [w["text"] for w in labels if w["text"] in ("0", "10", "20", "30")]
            
            row_bbox = RowBBox(y_start=y_start, y_end=y_end, page_idx=page_idx)
            scale = calibrate_scale(words, lines, y_start, y_end, page.width)
            
            if scale is None or (len(set(numeric_scales)) < 2 and scale.source == "fallback"):
                if len(words) < 50:
                    continue

            gl_curves, vec_events = extract_row_vectors(page, row_bbox)
            vision_events = self._vision.extract_events(page_idx, y_start, y_end, existing_events=vec_events)
            all_events = vec_events + vision_events

            for col_idx, header in enumerate(row_headers):
                x_start = max(0, header["coords"]["x0"] - 10)
                x_end = (row_headers[col_idx + 1]["coords"]["x0"] if col_idx + 1 < len(row_headers) else page.width) - 5
                time_anchor = calibrate_time(words, lines, y_start, y_end, x_start, x_end)

                cell = DayCell(
                    date=header["date"],
                    scale=scale,
                    time_anchor=time_anchor,
                    glucose_curves=gl_curves,
                    events=[e for e in all_events if time_anchor.left_x - 3 <= e.x <= time_anchor.right_x + 3],
                )
                self._records.extend(cell.to_records())

        # Track last date on this page for cross-page continuation
        last_row_headers = rows[-1]
        last_row_headers.sort(key=lambda h: h["coords"]["top"])
        self._prev_date = last_row_headers[-1]["date"]


def _build_word_spans(words: list) -> list:
    spans, pos = [], 0
    for w in words:
        spans.append((pos, pos + len(w["text"])))
        pos += len(w["text"]) + 1
    return spans


def _find_date_headers(recon: str, spans: list, words: list, year: int, is_share_normalized: bool = False) -> list:
    headers = []
    for match in _DATE_PATTERN.finditer(recon):
        day_str = match.group(1).zfill(2)
        month_str = match.group(2)
        year_str = match.group(3)
        
        dt = _parse_vn_date(day_str, month_str, year_str, year)
        if not dt: continue
        
        # Determine the word index in the word list
        idx = next((i for i, s in enumerate(spans) if s[0] <= match.start() < s[1]), 0)
        
        # Robust token matching:
        # We search around idx for a word that contains the day. 
        # If we find it, and it's not noise, use it as anchor.
        coords = None
        for i in range(max(0, idx - 2), min(len(words), idx + 5)):
            w_text = words[i]["text"].strip("-,/ ").lower()
            
            # Match day string exactly (or padded)
            if day_str in w_text or match.group(1) in w_text:
                # Basic noise filter: charts start low-ish on first page, 
                # but in segments they are at the very top.
                if words[i]["top"] < 50 and not is_share_normalized:
                    continue
                    
                coords = {"x0": words[i]["x0"], "x1": words[i]["x1"], "top": words[i]["top"], "bottom": words[i]["bottom"]}
                break
                
        if coords: headers.append({"date": dt, "coords": coords})
    return headers


def _group_into_rows(headers: list, tol: float = 25.0) -> list:
    rows, curr = [], [headers[0]]
    for h in headers[1:]:
        if abs(h["coords"]["top"] - curr[0]["coords"]["top"]) < tol: curr.append(h)
        else: rows.append(curr); curr = [h]
    rows.append(curr); return rows


def _compute_y_end(row_idx: int, rows: list, page, words: list, y_start: float) -> float:
    next_y = (rows[row_idx + 1][0]["coords"]["top"] if row_idx + 1 < len(rows) else page.height)
    agp = [w for w in words if "AGP" in w["text"] and w["top"] > y_start]
    agp_stop = min(w["top"] for w in agp) - 5 if agp else page.height
    # Overhang geometry: charts on tightly packed pages can extend far below
    # the next day's header. The minimum height of 400px ensures we capture the
    # full glucose trace. X-range time-calibration prevents cross-day contamination.
    return max(min(next_y, agp_stop, y_start + 500), y_start + 400)
