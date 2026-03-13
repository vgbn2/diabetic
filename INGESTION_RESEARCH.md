# Data Ingestion Research Report: Ensuring High-Quality Metabolic Data

## 1. Data Quality & Cleansing (The "Garbage" Detection)
CGM data (Dexcom/Libre) is inherently noisy. To ensure the AI agent receives "usable" data, we must implement:
*   **Physiological Constraint Filtering:** Glucose cannot physiologically change faster than **3–4 mg/dL per minute**. Any jump exceeding this (e.g., 20 mg/dL in 5 mins) should be flagged as a sensor artifact or "noise."
*   **Compression Detection (PISA):** Programmatically detect "Pressure Induced Sensor Attenuation" (false lows from sleeping on the sensor) by identifying sharp drops (>3 mg/dL/min) followed immediately by sharp rises, with no corresponding insulin bolus.
*   **Outlier Removal:** Use a **Rolling Median Filter** (window size 3) to strip out single-point spikes before passing data to the Kalman filter.

## 2. Time-Series Alignment & Synchronization
To link intermittent "events" (Insulin/Carbs) with continuous CGM data:
*   **5-Minute Grid Resampling:** All incoming data (Nightscout, CSV, or Sensor) must be resampled to a uniform 5-minute grid using `pandas.resample('5T').mean()`.
*   **Smart Interpolation:** 
    *   **< 20 mins gap:** Linear interpolation.
    *   **20-60 mins gap:** Cubic Spline (to preserve the curve).
    *   **> 60 mins gap:** Do not interpolate; treat as a break in the session to avoid hallucinating metabolic states.

## 3. Feature Linking & Contextual Math
An AI agent needs context beyond just "current glucose." We will implement:
*   **IOB (Insulin on Board):** Using the **Scalable Exponential Model** (Novolog/Rapid-acting) with a customizable Peak (75m) and Duration of Insulin Action (DIA, typically 5h).
*   **COB (Carbs on Board):** Using a dynamic absorption model (starting with a linear 30g/hr decay) to predict the ongoing glucose impact of meals.
*   **Linking Logic:** The `IngestionEngine` will merge the `/entries` (CGM) and `/treatments` (Insulin/Carbs) datasets based on the 5-minute grid.

## 4. Scalability & Agent Linkability
*   **Storage Format:** Use **Apache Parquet**. It is highly compressed, preserves data types (unlike CSV), and is extremely fast for a Python/ML agent to query via `pyarrow`.
*   **Interface:** The `GlucoseDataSource` abstract class ensures that switching from Nightscout to a **WebSocket** (for 1-second microwave sensor data) only requires a new client, not a new pipeline.
