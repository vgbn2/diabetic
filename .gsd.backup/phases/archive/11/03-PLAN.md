---
phase: 11
plan: 3
wave: 3
depends_on: ["11.2"]
files_modified: ["diabetic/ingestion/offline/vision_parser/render_engine.py", "diabetic/ingestion/offline/vision_parser/mapper.py"]
autonomous: true
must_haves:
  truths:
    - "PDF pages are rendered at exactly 576 DPI (8x scale)"
    - "X pixels map accurately to a 24-hour horizontal axis at 2.5-minute increments"
  artifacts:
    - "diabetic/ingestion/offline/vision_parser/render_engine.py exists"
    - "diabetic/ingestion/offline/vision_parser/mapper.py exists"
---

# Plan 11.3: Vision Parser Foundations (Render & Mapping)

<objective>
Establish the coordinate system and high-fidelity rendering pipeline for the new vision-based parser.

Purpose: To process Ottai PDF reports at high enough resolution (576 DPI) to find tiny icons, and to build the timestamp mapping logic (at 2.5-minute resolution).
Output: A render engine script and a temporal mapping script.
</objective>

<context>
Load for context:
- scratch/super_zoom.py (shows pypdfium2 rendering logic)
- C:\Users\Lenovo\.gemini\antigravity\brain\5091671b-1cbd-4697-ba65-e65f58f7a5a8\implementation_plan.md
</context>

<tasks>

<task type="auto">
  <name>Implement PDF Render Engine & Color Preprocessor</name>
  <files>diabetic/ingestion/offline/vision_parser/render_engine.py</files>
  <action>
    Create the `PDFRenderer` class. 
    Imports: `pypdfium2 as pdfium`, `cv2`, `numpy as np`, `from PIL import Image`.
    Functions:
    - `__init__(self, pdf_path: str, scale: float = 8.0)`
    - `render_page(self, page_idx: int) -> np.ndarray` (return cv2 format)
    - `generate_masks(self, img_rgb: np.ndarray) -> dict`: 
      - Convert to HSV.
      - Create `syringe_mask` isolating Deep Purple (ignoring all grid noise).
      - Create `meal_mask` isolating Orange/Yellow dots.
    AVOID: Grayscale template matching, as grid lines destroy correlation scores. Rely exactly on the HSV masks.
  </action>
  <verify>python -c "from diabetic.ingestion.offline.vision_parser.render_engine import PDFRenderer"</verify>
  <done>Class renders high-res arrays and cleanly produces Purple/Orange masks without grid lines.</done>
</task>

<task type="auto">
  <name>Implement Coordinate Mapper</name>
  <files>diabetic/ingestion/offline/vision_parser/mapper.py</files>
  <action>
    Create the `CoordinateMapper` class.
    Imports: `datetime`, `pandas as pd`
    Functions:
    - `map_x_to_time(self, x_pixel: int, chart_width: int, date: datetime.date) -> datetime.datetime` -> calculates horizontal percentage and snaps to nearest 2.5-minute increment.
    - `map_y_to_glucose(self, y_pixel: int, chart_height: int) -> float` -> maps an inverted Y percentage to the standard glucose range.
    AVOID: hardcoding pixel ranges; assume arbitrary scaled widths from the renderer.
  </action>
  <verify>pytest or manual script mapping x=0 to 00:00 and x=width to 24:00</verify>
  <done>Yields precise 2.5-min temporal representations from X coordinates.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] pypdfium2 renders page 1 cleanly.
- [ ] Mapper successfully converts test X boundaries to start/end of day.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
