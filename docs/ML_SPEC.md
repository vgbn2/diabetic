# Diabetic: Multi-Layer Metabolic Intelligence Specification

This document defines the five data layers used by the digital-twin and CNN
prediction path. They isolate **Static Traits**, **Environmental Forcing**,
**Human Agency**, **Systemic Error**, and **Subjective Truth**.

---

## 🏗️ Layer 1: The Bio-Basal Vessel (Static & Predictable)
*Focus: Personal baseline and real-time biometric telemetry.*

| Feature | Type | Frequency | Rationale |
| :--- | :--- | :--- | :--- |
| **Blood Glucose (BG)** | Continuous | 5-min | Core signal for temporal pattern extraction. |
| **Heart Rate (HR-BPM)** | Continuous | 1-min | Real-time physiological stress/arousal index. |
| **Age** | Predictable | Yearly | Shifts metabolic baseline and ISF/CSF parameters. |
| **Weight / Height** | Fixed/Manual | Monthly | Biological mass for volume-of-distribution math. |
| **Ethnicity / Nationality** | Static | Constant | Genetic/Cultural metabolic traits (e.g. higher T1D risk groups). |
| **GENDER**|STATIC|Constant|Genetics, determine hormone|
---

## 🌊 Layer 2: The Adaptive Regimes (Uncontrollable Cycles)
*Focus: External and internal forced oscillations.*

| Feature | Type | Cycle | Rationale |
| :--- | :--- | :--- | :--- |
| **Climate (Temp/Hum)** | Stochastic | Hourly | Affects subcutaneous insulin absorption rates. |
| **Air Quality (AQI)** | Stochastic | Hourly | Pollution-driven systemic inflammation / resistance. |
| **Biphasic Hormones** | Sinusoidal | 24h & 28d | Male/Female hormonal resistance waves. |
| **Seasonality** | Slow Wave | Yearly | Broad shifts in insulin sensitivity (Summer vs Winter). |
| **Regime Detection** | Computed | Adaptive | Real-time resistance gain (Normal vs Sick/High Stress). |

---

## 🎮 Layer 3: The Behavioral Engine (Controllable Agency)
*Focus: User-driven inputs and lifestyle choices.*

| Feature | Type | Source | Rationale |
| :--- | :--- | :--- | :--- |
| **Dietary Intake** | Discrete | Manual/App | Carb counts, GI index, and nutritional density. |
| **Drink/Hydration** | Discrete | Manual | Impacts blood viscosity and glucose concentration. |
| **Insulin Dosing** | Discrete | App/Pump | Direct pharmacodynamic dropping events. |
| **Sleep Quality** | Periodic | Sensor | Circadian recovery state and cortisol clearing. |
| **Exercise Intensity** | Stochastic | HR-Relay | Aerobic vs Anaerobic glucose utilization. |

---

## 🎯 Layer 4: The Meta-Correction Layer (Audit & Feedback)
*Focus: Systemic self-awareness and forensic back-audit.*

| Feature | Type | Source | Rationale |
| :--- | :--- | :--- | :--- |
| **Model Residuals** | Analytic | Back-Audit | Tracks the error delta between validated forecasts and actual outcomes. |
| **Sensor Integrity** | Diagnostic | Signal Jitter | Detects compression artifacts or sensor end-of-life failures. |
| **Metabolic Inertia** | Longitudinal | History | Long-term HbA1c/Fructosamin drift (3-month baselines). |
| **Confidence Score** | Computed | Ensemble | A meta-index defining how much to "trust" the Layer 1-3 synthesis. |

---

## 🔄 Layer 5: The Interaction & Calibration Layer (RLHF)
*Focus: Subjective truth and user-labeled ground truth.*

| Feature | Type | Source | Rationale |
| :--- | :--- | :--- | :--- |
| **User Flags** | Subjective | UI / Manual | Marking "False Alarms" or "Missed Faints" to tune thresholds. |
| **Symptom Mapping** | Event | Survey | Linking L1-2 signal patterns to felt symptoms (fog, dizziness). |
| **Threshold Bias** | Control | App Settings | Customizing the aggressive vs. conservative alert sensitivity. |

---

## Canonical glucose units

All five layers exchange glucose internally as mmol/L. Provider adapters normalize
at ingestion; model features, forecasts, thresholds, and audit state never switch
units. `PREFER_MMOL` affects presentation formatting only and cannot alter a safety
decision.

## 🧠 Model Ensemble Strategy
1. **Digital Twin (Behavioral)**: Simulates meal, insulin, and basal effects.
2. **1D-CNN (Signal)**: Recognizes Layer 1 temporal signatures when validated
   weights and real cardiac telemetry are available.
3. **Meta-Oracle (Layer 4)**: Estimates circadian basal drift.
4. **Safety Gate (Layer 5)**: Applies conservative confidence and physiology
   constraints before an alert is considered.
