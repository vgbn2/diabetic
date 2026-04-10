---
phase: 11
plan: 5
wave: 3
depends_on: ["11.3", "11.4"]
files_modified: ["diabetic/ingestion/offline/vision_parser/transformer.py", "requirements.txt"]
autonomous: true
must_haves:
  truths:
    - "Final output matches schema: timestamp (2.5m), glucose, temperature, insulin (predicted), airquality (hourly)"
  artifacts:
    - "diabetic/ingestion/offline/vision_parser/transformer.py exists"
---

# Plan 11.5: Schema Transformation & Integration

<objective>
Join the high-resolution parsed vision data with existing temporal sources to create the final unified clinical dataframe.

Purpose: The vision parser must produce a dataset compatible with the existing `diabetic` models. We need to merge the 2.5-minute glucose/insulin predictions with hourly weather and AQI.
Output: A final transformation module and updated requirements.
</objective>

<context>
Load for context:
- diabetic/ingestion/weather.py (WeatherIngestor class)
- C:\Users\Lenovo\.gemini\antigravity\brain\5091671b-1cbd-4697-ba65-e65f58f7a5a8\implementation_plan.md
</context>

<tasks>

<task type="auto">
  <name>Lock Vision Dependencies</name>
  <files>requirements.txt</files>
  <action>
    Append `opencv-python`, `pypdfium2`, `scipy` and `pandas` to the requirements.
    Ensure they are appended without breaking existing Phase 10 dependencies.
  </action>
  <verify>grep -q "opencv-python" requirements.txt</verify>
  <done>Environment is prepared for the Vision Parser.</done>
</task>

<task type="auto">
  <name>Implement Data Transformer</name>
  <files>diabetic/ingestion/offline/vision_parser/transformer.py</files>
  <action>
    Create the transformation logic.
    Imports: `pandas as pd`, `diabetic.ingestion.weather.WeatherIngestor`.
    Function:
    - `join_clinical_data(vision_df: pd.DataFrame) -> pd.DataFrame` -> Merges the 2.5m vision DataFrame with the hourly weather/AQI payload over the timestamp index. Left join is preferred.
    AVOID: overwriting the 2.5-min resolution when merging the hourly data (forward fill is recommended).
  </action>
  <verify>python -c "from diabetic.ingestion.offline.vision_parser.transformer import join_clinical_data"</verify>
  <done>Final clinical DataFrame is built and structured.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Dependencies resolve cleanly.
- [ ] `join_clinical_data` forward-fills AQI without duplicating rows.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
