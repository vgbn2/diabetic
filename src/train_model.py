import pandas as pd
import numpy as np
import os
from datetime import timedelta
from src.simulation.digital_twin import BergmanDigitalTwin
from src.filters.metabolic_ukf import MetabolicUKF
from src.models.registry import ModelRegistry
from src.nightscout_client import NightscoutClient
from src.logger import logger

def train_metabolic_model(days_to_simulate: int = 30):
    """
    Automated training pipeline: 
    Simulation -> UKF Feature Extraction -> Training -> Saving.
    """
    logger.info(f"--- METABOLIC TRAINING PIPELINE: STARTING ({days_to_simulate} Days) ---")
    
    # 1. Generate Synthetic Physiological Data (Ground Truth)
    twin = BergmanDigitalTwin()
    raw_df = twin.generate_dataset(days=days_to_simulate)
    
    # 2. Feature Extraction via UKF
    # We pass the raw data through the UKF to generate the 'Estimated' features
    # This aligns the training data with the real-time inference pipeline.
    ukf = MetabolicUKF(dt=5.0)
    processed_records = []
    
    logger.info("Running UKF feature extraction over simulated dataset...")
    for _, row in raw_df.iterrows():
        # Update UKF with the current simulated sample
        state = ukf.update(
            z_glucose=row['sgv'], 
            iob=row['iob'], 
            cob=row['cob'], 
            dsi=row['dsi']
        )
        
        # Capture the estimated state
        processed_records.append({
            "timestamp": row['timestamp'],
            "sgv": state['glucose'],
            "velocity": state['velocity'],
            "remote_insulin": state['remote_insulin'],
            "iob": state['iob'],
            "cob": state['cob'],
            "dsi": state['dsi']
        })
        
    df = pd.DataFrame(processed_records)
    
    # 3. Label Generation: Shift Target SGV 30 minutes (6 samples) into the future
    df['sgv_target_30m'] = df['sgv'].shift(-6)
    df.dropna(inplace=True)
    
    # 4. Model Training
    predictor = ModelRegistry.get_model("xgboost")
    logger.info(f"Training XGBoost on {len(df)} samples with UKF-derived features...")
    predictor.train(df, target_col='sgv_target_30m')
    
    # 5. Persistence
    model_dir = "models"
    os.makedirs(model_dir, exist_ok=True)
    model_path = os.path.join(model_dir, "xgboost_v1.json")
    predictor.save(model_path)
    
    logger.info(f"--- TRAINING COMPLETE. Weights saved to {model_path} ---")
    
    # Final Verification
    test_state = {
        "sgv": 110.0,
        "velocity": -0.5,
        "remote_insulin": 0.0001,
        "iob": 0.5,
        "cob": 0.0,
        "dsi": 1.0
    }
    pred = predictor.predict(test_state)
    logger.info(f"Verification Prediction (Steady State Low): {pred:.1f} mg/dL")

def train_from_nightscout(days: int = 14):
    """
    Fetches real historical data from Nightscout and fine-tunes the model.
    """
    logger.info(f"--- NIGHTSCOUT RETRAINING: STARTING ({days} Days) ---")
    client = NightscoutClient()
    
    # 1. Fetch historical entries (approx 288 per day)
    entries = client.fetch_entries(count=days * 300)
    if not entries:
        logger.error("No Nightscout data retrieved. Verify URL/Secret in .env.")
        return

    # 2. Convert to DataFrame
    records = []
    for e in entries:
        records.append({
            "timestamp": e.timestamp,
            "sgv": float(e.sgv),
            "iob": 0.0, # Baseline
            "cob": 0.0, # Baseline
            "dsi": 1.8  # Nominal baseline DSI
        })
    df_raw = pd.DataFrame(records).sort_values("timestamp")
    
    # 3. UKF Feature Enrichment
    ukf = MetabolicUKF(dt=5.0)
    processed = []
    for _, row in df_raw.iterrows():
        state = ukf.update(row['sgv'], row['iob'], row['cob'], row['dsi'])
        processed.append({
            "sgv": state['glucose'],
            "velocity": state['velocity'],
            "remote_insulin": state['remote_insulin'],
            "iob": state['iob'],
            "cob": state['cob'],
            "dsi": state['dsi']
        })
    
    df = pd.DataFrame(processed)
    df['sgv_target_30m'] = df['sgv'].shift(-6)
    df.dropna(inplace=True)

    # 4. Save/Train
    predictor = ModelRegistry.get_model("xgboost")
    predictor.train(df, target_col='sgv_target_30m')
    predictor.save("models/xgboost_v1.json")
    logger.info("--- PERSONALIZED TRAINING COMPLETE. Models updated. ---")

if __name__ == "__main__":
    train_metabolic_model()
