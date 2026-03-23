---
phase: 1
plan: 1
wave: 1
depends_on: []
files_modified:
  - src/registry.py
  - src/config.py
autonomous: true
must_haves:
  truths:
    - "Project directory structure is modular and reflects function"
    - "Glucose and HeartRate schemas enforce strict medical-grade typing"
  artifacts:
    - "src/registry.py exists with Pydantic models"
    - "src/config.py exists for environment management"
---

# Plan 1.1: Foundation & Type Registry

<objective>
Establish the structural and linguistic foundation of Bio-Quant, ensuring every data point has a clear identity and every component a clear function.

Output: Directory structure and core type definitions.
</objective>

<context>
Load for context:
- .gsd/docs/SPEC.md
- .gsd/docs/MASTERPLAN.md
</context>

<tasks>

<task type="auto">
  <name>Initialize Project Hierarchy</name>
  <files>None (Directories Only)</files>
  <action>
    Create the following hierarchy:
    - src/ingestion/ (Data entry)
    - src/smoothing/ (DSP/Kalman)
    - src/features/ (Math logic)
    - src/forecasting/ (ML logic)
    - src/alert_engine/ (Decision logic)
    - src/comms/ (Notifications)
  </action>
  <verify>ls -R src/</verify>
  <done>Directories created according to functional naming</done>
</task>

<task type="auto">
  <name>Implement Type Registry</name>
  <files>src/registry.py</files>
  <action>
    Create Pydantic models for:
    - GlucoseReading (timestamp, value: float, trend: str, source: str)
    - CardiacReading (timestamp, bpm: int, hrv: float)
    - MetabolicSnapshot (aggregated state for features)

    ```python
    from pydantic import BaseModel
    from datetime import datetime
    from typing import Optional

    class GlucoseReading(BaseModel):
        timestamp: datetime
        value: float  # mmol/L support
        trend: str
        source: str = "nightscout"
        unit: str = "mmol/L"

    class InsulinDose(BaseModel):
        timestamp: datetime
        units: float
        type: str  # rapid, long-acting
        
    class MealEvent(BaseModel):
        timestamp: datetime
        is_breakfast: bool = False
        is_lunch: bool = False
        is_dinner: bool = False
        carbs: Optional[float] = None
        
    class MetabolicSnapshot(BaseModel):
        glucose: GlucoseReading
        cardiac: Optional[CardiacReading] = None
        filtered_value: float = 0.0
        velocity: float = 0.0
    ```
  </action>
  <verify>python -c "from src.registry import GlucoseReading; print('Import Success')"</verify>
  <done>registry.py contains validated Pydantic models reflecting device-to-cloud identity</done>
</task>

<task type="auto">
  <name>Setup Configuration Handler</name>
  <files>src/config.py</files>
  <action>
    Implement Config class to read environment variables.

    ```python
    from pydantic_settings import BaseSettings, SettingsConfigDict

    class Settings(BaseSettings):
        NIGHTSCOUT_URL: str
        API_SECRET: str
        TELEGRAM_TOKEN: str
        USER_ID: int
        CAREGIVER_ID: Optional[int] = None
        
        model_config = SettingsConfigDict(env_file=".env")

    config = Settings()
    ```
  </action>
  <verify>python src/config.py</verify>
  <done>Configuration is centralized and environment-aware</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] `GlucoseReading` rejects values that are not floats.
- [ ] `src/smoothing` exists as a functional unit.
</verification>

<success_criteria>
- [ ] All foundational directories exist.
- [ ] Type registry validates input data correctly.
</success_criteria>
