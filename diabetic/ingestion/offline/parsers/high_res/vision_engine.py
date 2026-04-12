"""
vision_engine.py — OpenCV Icon Detection (Lazy-Loaded)
=======================================================
Responsibilities:
  - Render PDF pages at configurable DPI (default 400 — 2x faster than 576).
  - Detect bolus/meal icon centroids via HSV masking.
  - Map pixel coordinates back to PDF point space.
  - Only initialises the renderer on first use (lazy loading).
"""
from __future__ import annotations
from pathlib import Path
from typing import List, Optional, Tuple

from .models import EventMarker

# DPI for rendering — 400 gives adequate icon resolution with 2x less RAM
_RENDER_DPI = 400
_SCALE = _RENDER_DPI / 72.0   # pixels per PDF point


class VisionEngine:
    """
    Lazy-loading vision wrapper around PDFRenderer + IconDetector.

    Usage:
        engine = VisionEngine(pdf_path)
        markers = engine.extract_events(page_idx, y_start, y_end)
    """

    def __init__(self, pdf_path: Path):
        self._pdf_path = pdf_path
        self._renderer = None   # lazy
        self._detector = None   # lazy

    def _ensure_loaded(self):
        if self._renderer is None:
            from diabetic.ingestion.offline.vision_parser.render_engine import PDFRenderer
            from diabetic.ingestion.offline.vision_parser.icon_detector import IconDetector
            _scale = _RENDER_DPI / 72.0   # convert DPI -> scale factor
            self._renderer = PDFRenderer(self._pdf_path, scale=_scale)
            self._detector = IconDetector()

    def extract_trace_mask(
        self,
        page_idx: int,
        y_start: float,
        y_end: float,
    ) -> Optional[np.ndarray]:
        """
        Generates a clean binary mask of the glucose trace by removing grid lines.
        Returns a binary mask where 255 = glucose, 0 = background/grid.
        """
        try:
            import cv2
            import numpy as np
            self._ensure_loaded()
            
            # Render and get glucose mask
            img_bgr = self._renderer.render_page(page_idx)
            masks = self._renderer.generate_masks(img_bgr)
            mask = masks.get("glucose")
            
            if mask is None:
                return None

            # --- Morphological Grid Removal ---
            # 1. Detect long horizontal lines (Grid Lines)
            # Typically grid lines are > 50 pixels wide, while trace segments are shorter or curved.
            h_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (40, 1))
            h_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, h_kernel)
            
            # 2. Detect long vertical lines (Hour Markers)
            v_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (1, 40))
            v_lines = cv2.morphologyEx(mask, cv2.MORPH_OPEN, v_kernel)
            
            # 3. Subtract grid from mask
            # We use bitwise_and with bitwise_not to clear the detected grid regions
            clean_mask = cv2.bitwise_and(mask, cv2.bitwise_not(cv2.bitwise_or(h_lines, v_lines)))
            
            # 4. Clean up noise with a small closing operation
            noise_kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
            clean_mask = cv2.morphologyEx(clean_mask, cv2.MORPH_CLOSE, noise_kernel)
            
            return clean_mask
            
        except Exception as exc:
            print(f"[vision_engine] Mask generation error on page {page_idx}: {exc}")
            return None

    def extract_events(
        self,
        page_idx: int,
        y_start: float,
        y_end: float,
        existing_events: Optional[List[EventMarker]] = None,
    ) -> List[EventMarker]:
        """
        Render the page and detect bolus/meal icons. Returns new markers only
        (de-duplicated against existing_events from the vector engine).

        Args:
            page_idx:        Zero-based page number.
            y_start:         Row top boundary in PDF points.
            y_end:           Row bottom boundary in PDF points.
            existing_events: Already-detected events to deduplicate against.
        """
        existing_events = existing_events or []
        new_markers: List[EventMarker] = []

        try:
            self._ensure_loaded()
            img_bgr = self._renderer.render_page(page_idx)
            masks = self._renderer.generate_masks(img_bgr)

            for event_type, mask_key in [("bolus", "syringe"), ("meal", "meal")]:
                for cx, cy in self._detector.detect_centroids(masks[mask_key]):
                    # Convert pixel → PDF point space
                    pt_x = cx / _SCALE
                    pt_y = cy / _SCALE
                    # Filter to this row's vertical range
                    if not (y_start - 30 < pt_y < y_end + 60):
                        continue
                    # Deduplication: skip if already found by vector engine
                    if any(
                        abs(e.x - pt_x) < 10 and abs(e.y - pt_y) < 10
                        for e in existing_events
                    ):
                        continue
                    new_markers.append(EventMarker(type=event_type, x=pt_x, y=pt_y))

        except Exception as exc:
            print(f"[vision_engine] Warning on page {page_idx}: {exc}")

        return new_markers
