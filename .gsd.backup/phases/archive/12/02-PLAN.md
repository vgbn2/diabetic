---
phase: 12
plan: 2
wave: 1
depends_on: ["12.1"]
files_modified: ["diabetic/ingestion/offline/parsers/high_res/orchestrator.py"]
autonomous: true

must_haves:
  truths:
    - "Ghost headers from summary pages are filtered out, preventing day-collision"
    - "Extraction window is strictly bound to the visible page segment"
  artifacts:
    - "diabetic/ingestion/offline/parsers/high_res/orchestrator.py is updated with strict area filtering"
---

# Plan 12.2: Ghost Hunter (Precision Area Filtering)

<objective>
Eliminate 'Ghost Data' collisions caused by the normalizer's non-destructive translation logic. High-res parser will now strictly filter objects to the visible page segment [0, height] before processing.

Purpose: Fix the 'On-Off' coverage pattern where summary table rows steal data from the actual daily charts due to large overhang windows.
Output: A robust parser that ignores any object not physically within the current page segment's mediabox.
</objective>

<context>
Load for context:
- .gsd/SPEC.md
- diabetic/ingestion/offline/parsers/high_res/orchestrator.py
- scratch/debug_page_10.py (Findings)
</context>

<tasks>

<task type="auto">
  <name>Implement Strict Area Filtering</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    Update `_process_page` to filter all objects BEFORE min_y shifting.
    - Since normalized segments contain the full original scroll content (just translated), we must identify the 'Active Window'.
    - Find the 'Main Content Cluster' by looking for words with high density, OR simply filter to a reasonable range around the words that are intended for this page.
    - REVISED ACTION: Instead of filtering by `top < height`, we must filter relative to the FIRST legitimate header OR the expected segment range.
    - ACTUAL FIX: In `_process_page`, after `words = page.extract_words()`, calculate `min_y` as the top-most word. Then immediately filter `words`, `lines`, and `curves` to only include those in `[min_y - 10, min_y + page.height + 10]`.
    - Also update `min_y` calculation to include lines and curves: `min_y = min(all_active_elements)` to prevent clipping of orphan data.
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator as o; print('Syntax OK')"</verify>
  <done>Junk objects at Y=0 or Y=10000 are discarded before processing.</done>
</task>

<task type="auto">
  <name>Dynamic Overhang Correction</name>
  <files>diabetic/ingestion/offline/parsers/high_res/orchestrator.py</files>
  <action>
    Update `_compute_y_end` to be less aggressive when next_y is found.
    - Instead of forcing a 400px floor blindly, make the floor `min(y_start + 400, page.height)`.
    - This ensures we don't 'Overhang' past the end of the page and pick up data from the NEXT day that might have been shifted into the phantom space below.
  </action>
  <verify>python -c "import diabetic.ingestion.offline.parsers.high_res.orchestrator"</verify>
  <done>Overhang search is bounded by the physical segment height.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Orphan data recovery still works (no clipping).
- [ ] Summary headers from Page 1 are no longer found on Page 10.
- [ ] Average rows/day returns to >200 (70%+ yield).
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Coverage > 70% across all historical days
</success_criteria>
