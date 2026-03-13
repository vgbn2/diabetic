# Technical Review: Hyperglycemia Faint Detection

This document reviews the specific logic and physiological basis for the **Hyperglycemia Faint Detector** within the Bio-Quant system.

## 1. Physiological Context
Hyperglycemia (>180 mg/dL) can lead to fainting (syncope) through several pathways that Bio-Quant monitors:
- **Diabetic Ketoacidosis (DKA)**: High ketones and metabolic shifts.
- **Hyperosmolar Hyperglycemic State (HHS)**: Extreme dehydration leading to blood pressure drops.
- **Autonomic Neuropathy**: Impaired heart rate/blood pressure regulation.

## 2. Detection Markers & Equations

### A. Primary Marker: Glucose Level ($G$)
Thresholds are set higher than standard hyperglycemia to capture acute risk:
- **Warning**: $G > 300\ \text{mg/dL}$
- **Critical/Faint Risk**: $G > 350\ \text{mg/dL}$

### B. Secondary Marker: Dehydration (HRV)
High glucose causes osmotic diuresis (excessive urination), leading to dehydration.
- **Logic**: A significant drop in **Heart Rate Variability (HRV)** serves as a proxy for physical stress and dehydration.
- **Trigger**: $HRV < 0.7 \times \text{Baseline}$

### C. Predictive Marker: Velocity ($V$)
A positive velocity while already high indicates an uncontrolled spike.
- **Trigger**: $G > 250$ AND $V > 2.0\ \text{mg/dL/min}$

---

## 3. Integrated Alert Logic (The "Circuit Breaker")

| Risk Level | Condition | Action |
|---|---|---|
| **Low** | $180 < G < 300$ | Log & Track |
| **Moderate** | $G > 300$ AND $V > 0$ | Warn User: "Glucose rising, stay hydrated." |
| **High (Faint Risk)** | $G > 300$ AND $HRV < \text{Baseline} \cdot 0.7$ | **ALERT**: "High faint risk detected. Check for ketones." |
| **Critical** | $G > 400$ OR ($G > 350$ AND $V > 1$) | **CRITICAL**: "Immediate medical attention/Insulin required." |

---

## 4. Hardware Synergy (Microwave Sensor)

The **Cole-Cole Model** is particularly important for Hyperglycemia because:
- Extreme glucose levels significantly alter the **complex permittivity** ($\varepsilon^*$) of blood.
- The shift in resonant frequency ($\Delta f$) is largest and most distinct at these higher concentrations, making the MW sensor highly reliable for detecting "Danger Zone" highs.

---

## 5. Summary Recommendation
For the MVP, we should prioritize the **Glucose + HRV** fusion. While glucose alone shows the state, HRV provides the "biological context" of how the body is handling that state, which is the key to predicting a faint versus just a high reading.
