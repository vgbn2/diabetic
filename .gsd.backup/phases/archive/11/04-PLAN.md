---
phase: 11
plan: 4
wave: 3
depends_on: ["11.3"]
files_modified: ["diabetic/ingestion/offline/vision_parser/icon_detector.py", "diabetic/ingestion/offline/vision_parser/titration_engine.py"]
autonomous: true
must_haves:
  truths:
    - "System correctly identifies Syringe and Meal icons using OpenCV template matching"
    - "Inverse modeling correctly clusters predicted ISF (Insulin Sensitivity Factor) to infer discretionary doses"
  artifacts:
    - "diabetic/ingestion/offline/vision_parser/icon_detector.py exists"
    - "diabetic/ingestion/offline/vision_parser/titration_engine.py exists"
---

# Plan 11.4: Icon Detection & Titration Engine

<objective>
Implement computer vision to identify unlabelled clinical markers, and inverse-model the intended doses based on historical visual patterns.

Purpose: We must extract events from images where numerical text is missing, requiring OpenCV for position and "titration logic" to guess the unit value based on how deep the glucose line drops.
Output: Icon detector and Titration (Prediction) Engine.
</objective>

<context>
Load for context:
- scratch/super_zoom.py
- scratch/pdf_view_page1.png
</context>

<tasks>

<task type="auto">
  <name>Implement High-Fidelity Icon Detector</name>
  <files>diabetic/ingestion/offline/vision_parser/icon_detector.py</files>
  <action>
    Create the `IconDetector` class.
    Imports: `cv2`, `numpy as np`
    Functions:
    - `__init__(self, debug=False)`
    - `detect_syringes(self, purple_mask: np.ndarray) -> list[tuple[int, int]]`
    - `detect_meals(self, orange_mask: np.ndarray) -> list[tuple[int, int]]`
    Logic:
    - Instead of naive template matching, use `cv2.findContours` directly on the pre-processed color masks.
    - Filter contours by area to ignore noise (e.g., small dust pixels).
    - Calculate the centroid `(cX, cY)` of each valid contour using image moments (`cv2.moments`).
    - Return a list of `(cX, cY)` tuples representing the exact pixel coordinates of insulin and meal events.
    AVOID: using `cv2.matchTemplate` on grayscale images, as it is highly vulnerable to grid line intersections crossing the markers.
  </action>
  <verify>python -c "from diabetic.ingestion.offline.vision_parser.icon_detector import IconDetector"</verify>
  <done>Class successfully ingests HSV masks, finds contours, and returns exact centroid coordinates without false positives from grid lines.</done>
</task>

<task type="auto">
  <name>Implement Inverse-Model Titration Engine</name>
  <files>diabetic/ingestion/offline/vision_parser/titration_engine.py</files>
  <action>
    Create the `StateAwareTitrator` class.
    Imports: `numpy as np`, `scipy.signal`
    Functions:
    - `estimate_dose(self, pre_icon_glucose: list[float], post_icon_glucose: list[float], time_of_day: str)` -> Calculates the derivative (drop) in the 2-4 hours post-icon.
    - `_cluster_personal_isf(self)` -> Groups the observed drops by time segment to predict discretionary unit ranges.
    AVOID: hardcoding a permanent fixed ISF (e.g. "1 unit = 2 mmol/L"). Rely on the clustered historical curves.
  </action>
  <verify>python -c "from diabetic.ingestion.offline.vision_parser.titration_engine import StateAwareTitrator"</verify>
  <done>Returns a predicted unit range based on curve analysis.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Ensure non-max suppression works (no double-counting icons).
- [ ] Titrator correctly initializes.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
