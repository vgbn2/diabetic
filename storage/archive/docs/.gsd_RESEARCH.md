# Hyperglycemia & Hypoglycemia Faint Predictor Research Report

## 1. Medical Context: Triggers for Loss of Consciousness
*   **Hypoglycemia (Low Blood Sugar):** The most common acute cause. Can lead to "Insulin Shock" where the brain is deprived of glucose, causing rapid loss of consciousness.
*   **Hyperglycemic Crisis (DKA/HHS):** High blood sugar leads to Diabetic Ketoacidosis (DKA) or Hyperosmolar Hyperglycemic State (HHS). These are usually slower-onset but can lead to coma or death if untreated.
*   **Autonomic Neuropathy:** A common complication where the body fails to regulate blood pressure (Orthostatic Hypotension), causing fainting when standing up, often exacerbated by high glucose levels.

## 2. Key Predictive Features
*   **CGM Data:** Continuous Glucose Monitor readings (Current level + Rate of Change).
*   **LBGI/HBGI:** Low/High Blood Glucose Indices—statistical risk scores for glucose extremes.
*   **IOB/COB:** Insulin on Board (active insulin) and Carbs on Board (active carbohydrates).
*   **Biometrics:** Heart Rate Variability (HRV) and Galvanic Skin Response (GSR) are early physiological indicators of a "crash."

## 3. Recommended Datasets
*   **OhioT1DM:** Gold standard for Type 1 Diabetes research (includes CGM, insulin, carbs, and activity).
*   **PhysioNet CGMacros:** Large-scale CGM datasets for trend analysis.
*   **Kaggle - Diabetes Dataset:** Good for static risk factors (Pima Indians dataset).

## 4. State-of-the-Art (SOTA) Models
*   **Temporal Fusion Transformers (TFT):** Excellent for multi-horizon time-series forecasting.
*   **LSTM / GRU:** Traditional deep learning approach for sequential glucose data.
*   **GluFormer:** A specialized transformer architecture for glucose prediction.

## 5. Proposed Project Structure
*   `data/`: Raw and processed datasets.
*   `notebooks/`: Exploratory Data Analysis (EDA) and model prototyping.
*   `src/`: Production-ready source code (preprocessing, modeling, utils).
*   `models/`: Saved model weights and configurations.
