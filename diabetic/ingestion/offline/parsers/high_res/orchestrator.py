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
    "Th01": 1, "Th1": 1,  "thg 1": 1,
    "Th02": 2, "Th2": 2,  "thg 2": 2,
    "Th03": 3, "Th3": 3,  "thg 3": 3,
    "Th04": 4, "Th4": 4,  "thg 4": 4,
    "Th05": 5, "Th5": 5,  "thg 5": 5,
    "Th06": 6, "Th6": 6,  "thg 6": 6,
    "Th07": 7, "Th7": 7,  "thg 7": 7,
    "Th08": 8, "Th8": 8,  "thg 8": 8,
    "Th09": 9, "Th9": 9,  "thg 9": 9,
    "Th10": 10, "thg 10": 10,
    "Th11": 11, "thg 11": 11,
    "Th12": 12, "thg 12": 12,
}
_DATE_PATTERN = re.compile(r"\b(\d{1,2}\s+(?:Th\d{2}|thg\s+\d{1,2}))\b")
_YEAR_PATTERN = re.compile(r"\b(202\d)\b")


def _parse_vn_date(text: str, year: int) -> Optional[datetime]:
    text = text.strip()
    m = re.match(r"(\d{1,2})\s+thg\s+(\d{1,2}),?\s*(\d{4})?", text)
    if m:
        y = int(m.group(3)) if m.group(3) else year
        return datetime(y, int(m.group(2)), int(m.group(1)))
    m = re.match(r"(\d{1,2})\s+(Th\d{2})", text)
    if m:
        month = VN_MONTH.get(m.group(2))
        if month:
            return datetime(year, month, int(m.group(1)))
    return None


class HighResParser:
    """
    Modular high-resolution glucose parser for Ottai clinical PDF reports.

    Supports:
    - Standard multi-page 'Normal' reports
    - Long-scroll 'Share' reports (auto-normalised)
    """

    def __init__(self, pdf_path: str | Path):
        self.pdf_path = Path(pdf_path)
        self._records: List[dict] = []
        self._vision: Optional[VisionEngine] = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def parse(self) -> "HighResParser":
        active_path = self._maybe_normalize(self.pdf_path)
        self._vision = VisionEngine(active_path)
        print(f"[parser] Processing: {active_path.name}")

        with pdfplumber.open(active_path) as pdf:
            for page_idx, raw_page in enumerate(pdf.pages):
                page = self._localize(raw_page)
                print(f"  Page {page_idx + 1}/{len(pdf.pages)}", end="\r")
                self._process_page(page, page_idx)
        print()
        return self

    def save_csv(self, output_path: str | Path) -> Path:
        output_path = Path(output_path)
        if not self._records:
            print("[parser] No data extracted.")
            return output_path

        df = pd.DataFrame(self._records)
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").drop_duplicates(subset=["timestamp"], keep="first")
        df.to_csv(output_path, index=False)
        print(f"[parser] Saved {len(df)} rows -> {output_path}")
        return output_path

    @property
    def records(self) -> List[dict]:
        return list(self._records)

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _maybe_normalize(self, path: Path) -> Path:
        """Auto-convert long-scroll Share PDFs to multi-page format."""
        with pdfplumber.open(path) as pdf:
            if len(pdf.pages) == 1 and pdf.pages[0].height > 2000:
                print("[parser] Detected Share format — normalising...")
                try:
                    from diabetic.ingestion.offline.normalize_ottai_share import normalize_share_report
                    norm = normalize_share_report(path)
                    if norm and norm.exists():
                        print(f"[parser] Normalised -> {norm.name}")
                        return norm
                except ImportError:
                    print("[parser] ERROR: normalize_ottai_share not found.")
        return path

    @staticmethod
    def _localize(raw_page) -> object:
        """Crop page to its cropbox so all coordinates are page-local."""
        try:
            return raw_page.within_bbox(raw_page.cropbox)
        except Exception:
            return raw_page

    def _process_page(self, page, page_idx: int):
        text  = page.extract_text() or ""
        words = page.extract_words()
        lines = page.lines

        year_m = _YEAR_PATTERN.search(text)
        year   = int(year_m.group(1)) if year_m else datetime.now().year

        # ---- Date header detection ----------------------------------------
        recon  = " ".join(w["text"] for w in words)
        spans  = _build_word_spans(words)
        raw_headers = _find_date_headers(recon, spans, words, year)
        if not raw_headers:
            return

        raw_headers.sort(key=lambda h: h["coords"]["top"])
        rows = _group_into_rows(raw_headers)

        # ---- Per-row processing -------------------------------------------
        for row_idx, row_headers in enumerate(rows):
            row_headers.sort(key=lambda h: h["coords"]["x0"])

            y_start = row_headers[0]["coords"]["top"]
            y_end   = _compute_y_end(row_idx, rows, page, words, y_start)

            if (y_end - y_start) > 2000:
                continue   # AGP / global header — skip

            row_bbox = RowBBox(y_start=y_start, y_end=y_end, page_idx=page_idx)

            # Scale calibration (Crystal Y-axis)
            scale = calibrate_scale(words, y_start, y_end, page.width)
            if scale is None:
                continue

            # Vector extraction
            gl_curves, vec_events = extract_row_vectors(page, row_bbox)

            # Vision extraction (lazy — only called when needed)
            vision_events = self._vision.extract_events(
                page_idx, y_start, y_end, existing_events=vec_events
            )
            all_events = vec_events + vision_events

            # Per-column (day) iteration
            for col_idx, header in enumerate(row_headers):
                x_start = max(0, header["coords"]["x0"] - 10)
                x_end   = (row_headers[col_idx + 1]["coords"]["x0"]
                            if col_idx + 1 < len(row_headers)
                            else page.width) - 5

                # Temporal calibration (Crystal X-axis)
                time_anchor = calibrate_time(
                    words, lines, y_start, y_end, x_start, x_end
                )

                cell = DayCell(
                    date=header["date"],
                    scale=scale,
                    time_anchor=time_anchor,
                    glucose_curves=gl_curves,
                    events=[e for e in all_events
                            if time_anchor.left_x - 3 <= e.x <= time_anchor.right_x + 3],
                )
                self._records.extend(cell.to_records())


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _build_word_spans(words: list) -> list:
    spans, pos = [], 0
    for w in words:
        spans.append((pos, pos + len(w["text"])))
        pos += len(w["text"]) + 1
    return spans


def _find_date_headers(recon: str, spans: list, words: list, year: int) -> list:
    headers = []
    for match in _DATE_PATTERN.finditer(recon):
        dt = _parse_vn_date(f"{match.group(1)} {year}", year)
        if not dt:
            continue
        idx = next((i for i, s in enumerate(spans) if s[0] <= match.start() < s[1]), 0)
        parts = match.group(1).replace(",", "").split()
        coords = None
        for i in range(idx, min(idx + 10, len(words) - len(parts) + 1)):
            if all(words[i + k]["text"].replace(",", "") == parts[k]
                   for k in range(len(parts))):
                coords = {
                    "x0": words[i]["x0"],
                    "x1": words[i + len(parts) - 1]["x1"],
                    "top": words[i]["top"],
                    "bottom": words[i]["bottom"],
                }
                break
        if coords:
            headers.append({"date": dt, "coords": coords})
    return headers


def _group_into_rows(headers: list, tol: float = 25.0) -> list:
    rows, curr = [], [headers[0]]
    for h in headers[1:]:
        if abs(h["coords"]["top"] - curr[0]["coords"]["top"]) < tol:
            curr.append(h)
        else:
            rows.append(curr)
            curr = [h]
    rows.append(curr)
    return rows


def _compute_y_end(row_idx: int, rows: list, page, words: list, y_start: float) -> float:
    next_y = (rows[row_idx + 1][0]["coords"]["top"]
              if row_idx + 1 < len(rows) else page.height)
    agp = [w for w in words if "AGP" in w["text"] and w["top"] > y_start]
    agp_stop = min(w["top"] for w in agp) - 5 if agp else page.height
    return max(min(next_y, agp_stop), y_start + 80)
