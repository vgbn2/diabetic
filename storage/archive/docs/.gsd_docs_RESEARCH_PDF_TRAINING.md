# PDF Data Extraction & Pre-training Strategy

## 📑 THE CHALLENGE
PDFs are unstructured. Medical reports (Dexcom Clarity, LabCorp, etc.) vary in format. Feeding them directly into a model is high-risk.

## 🏛️ ARCHITECTURAL DECISION: The "Sub-Project" Approach
We will treat PDF extraction as a **Pre-training Pipeline** utility (`backend/research/`). This ensures the live monitor remains lean while the "knowledge" is baked into the model weights.

### Step 1: PDF Parsing (The Extractor)
- **Tool**: `unstructured` or `pdfplumber` + a custom regex parser.
- **Goal**: Export PDF tables/charts into `data/training/personal_history.csv`.
- **Identity**: Map PDF columns (Time, Glucose, Meal) to our `GlucoseReading` registry.

### Step 2: Transfer Learning (The Pre-trainer)
- **Base Model**: Pre-trained on OhioT1DM (General T1D physiology).
- **Fine-tuning**: Train on the `personal_history.csv` extracted from your PDFs.
- **Output**: Personal model weights used by the `backend/src/forecaster.py`.

## 🛠️ THE NEW PLAN (Plan 0.1)
I am adding a **Milestone 0: Data Enrichment** to the ROADMAP.

```markdown
- [ ] **Plan 0.1**: Research & Implement PDF Parser.
- [ ] **Plan 0.2**: Generate personal training set.
- [ ] **Plan 0.3**: Execution of Transfer Learning.
```
