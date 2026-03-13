# Bio-Quant — AI Glucose Crash & Faint Predictor
## System Architecture Document

> **Version:** 1.0  
> **Status:** MVP Planning  
> **Stack:** Python 3.10+ | Nightscout API | scikit-learn | filterpy | Telegram Bot

---

## 1. Project Overview

**Bio-Quant** is a personalized, AI-powered metabolic monitor that warns individuals of dangerous glucose events. While it focuses on **Hypoglycemic crashes** (30-minute lead time), it is also designed to detect and alert for **Hyperglycemic fainting risks**.

---

## 2. System Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                         DATA SOURCES                                │
│                                                                     │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────────┐   │
│  │  CGM Sensor  │   │ Apple Health │   │   Manual Input       │   │
│  │ (Dexcom/     │   │ Google Fit   │   │ (Meals, Insulin,     │   │
│  │  Libre)      │   │ (HRV, Sleep) │   │  Stress Level)       │   │
│  └──────┬───────┘   └──────┬───────┘   └──────────┬───────────┘   │
│         │                  │                        │               │
└─────────┼──────────────────┼────────────────────────┼──────────────┘
          │                  │                        │
          ▼                  ▼                        ▼
┌─────────────────────────────────────────────────────────────────────┐
│                      NIGHTSCOUT API BRIDGE                          │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                   LAYER 3 — DSP PROCESSING                          │
│   Raw Glucose  →  [Kalman Filter]  →  Clean Glucose Trend           │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                 LAYER 2 — FEATURE ENGINEERING (MATH)                │
│   • Velocity / Acceleration    • Fatigue_Index    • IOB / COB       │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│              LAYER 4 — PERSONALIZED ML ENGINE                       │
│   Input: Features            Output: Predicted_Glucose_30min        │
└─────────────────────────────┬───────────────────────────────────────┘
                              │
          ┌───────────────────┴───────────────────┐
          ▼                                       ▼
┌───────────────────────────┐           ┌───────────────────────────┐
│     HYPO ALERT LOGIC      │           │     HYPER ALERT LOGIC     │
│   (Crash Prediction)      │           │     (Faint Detection)     │
└─────────────┬─────────────┘           └─────────────┬─────────────┘
              │                                       │
              └───────────────────┬───────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────┐
│                LAYER 5 — COMMUNICATION BRIDGE                       │
│   Telegram Bot → sends alert to user + designated caregiver         │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 3. Biology & Mathematics Engine

### Hypoglycemia (Glucose Crash)
- **Problem**: Life-threatening crashes (< 70 mg/dL).
- **Metric**: `Velocity` < -2 mg/dL/min while `Predicted_Glucose` < 70.

### Hyperglycemia (Faint Detector)
- **Problem**: Syncope/Fainting due to acute dehydration or ketoacidosis.
- **Metric**: `Glucose` > 300 mg/dL + Low `HRV` (Dehydration proxy) + `Acceleration` > 0.

### Core Equations
- **Velocity**: `V(t) = [G(t) - G(t - 15)] / 15`
- **Acceleration**: `A(t) = [V(t) - V(t - 15)] / 15`
- **Fatigue Index**: `F = Standard_Sleep / Last_Night_Sleep`

---

## 4. Layer 3 — DSP Signal Processing

The system uses a **Linear Kalman Filter** (`filterpy`) to handle sensor noise and 10-15 minute physiological lag.

**State Vector**: `x = [G, V]ᵀ` (Glucose, Velocity).

---

## 5. Layer 4 — Personalized ML Engine

- **MVP**: Per-user `RandomForestRegressor`.
- **Target**: `y = glucose_in_30_minutes`.
- **Base Data**: OhioT1DM dataset fine-tuned with personal Nightscout data.

---

## 6. Layer 5 — Alert & Communication System

### Alert Logic (Circuit Breaker)

```python
def check_status(predicted_g, current_g, velocity, fatigue_idx, hrv):
    # HYPO LOGIC
    hypo_threshold = 80 if fatigue_idx > 1.3 else 70
    if predicted_g < 54: return "CRITICAL_HYPO"
    if predicted_g < hypo_threshold and velocity < -2: return "WARNING_HYPO"
    
    # HYPER LOGIC
    if current_g > 350: return "CRITICAL_HYPER"
    if current_g > 300 and hrv < HRV_BASELINE * 0.7: return "FAINT_RISK_HYPER"

    return "OK"
```

---

## 7. Layer 6 — Microwave Hardware (Phase 2)

Integration of **non-invasive 2.4 GHz CSRR (Split Ring Resonator)** sensors to replace patch CGMs, measuring dielectric property changes in blood.

---

## 8. Development Roadmap

- **Day 1**: Nightscout API & Live Data
- **Day 2**: Kalman Filter Implementation
- **Day 3**: Feature Engineering
- **Day 4**: ML Model Training (OhioT1DM)
- **Day 5**: Bimodal Alert Logic
- **Day 6**: Telegram Bot Integration
- **Day 7**: System Validation & Testing
