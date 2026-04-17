# Project Vision: The Bio-Quant Metabolic Command Center

## 🌌 The Mission
To transform metabolic management from a reactive clinical burden into a proactive, state-aware predictive intelligence system. The Bio-Quant Engine utilizes high-fidelity sensor data fused with biological and cultural context to protect the user from metabolic shocks (Hyperglycemia/Hypoglycemia/Fainting) through a neural-first Telegram interface.

## 📱 The Interaction Paradigm (TWA)
The system is hosted entirely within a **Telegram Web App (TWA)**, providing a premium, multi-tenant experience:
- **Bio-Cultural Profiling**: Personalized modeling that accounts for Age, Biology, Nationality, and Religion.
- **Vessel Control**: Direct toggles for "Sick Mode," "Fever," and "Dawn Phenomenon" to instantly re-calibrate the predictive engine.
- **Unified Logging**: Minimal-friction entry for hydration, meals, and insulin.

## 📊 The "Big JSON" Data Engine
The core intelligence rests on the **Unified 5-Layer State Frame**:
1. **Layer 1 (Vessel)**: Raw Biometrics (Glucose, HR, HRV, BMI).
2. **Layer 2 (Environment)**: Atmospheric forcing (Weather, Temp, Air Quality).
3. **Layer 3 (Agency)**: Behavioral events (Insulin on Board, Carbs, Hydration).
4. **Layer 4 (Audit)**: Systemic Meta-Correction (Forecast Residuals, Sensor Health).
5. **Layer 5 (Interaction)**: The Human-in-the-Loop (Subjective Feedback, RLHF weights).

## 🔮 Predictive Intelligence (Alpha-Gating)
- **Engine**: 1D-CNN + LSTM hybrid architecture.
- **Decision Matrix**: Predictive alarms fire ONLY when neural certainty ($P$) exceeds the dynamic user-threshold ($\alpha$).
- **Transparency**: Charts show **Probabilistic Uncertainty Ranges** (P5-P95) to communicate system doubt.

## 🔁 The RLHF Loop (Recursive Calibration)
Real-world performance is tuned via a **30-minute Binary Feedback loop**. Following every alert, the user confirms the prediction's validity, which recursively updates the system's sensitivity ($\alpha$)—minimizing false-positive fatigue while maintaining clinical safety.
