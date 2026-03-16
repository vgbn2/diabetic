import pandas as pd
import numpy as np
from typing import List, Optional
from datetime import datetime, timedelta
from .data_models import GlucoseReading, TreatmentEvent
from .kinetics import MetabolicKinetics
from .logger import logger

class IngestionEngine:
    """
    The 'Garbage Out' preventer. Cleans, resamples, and synchronizes 
    CGM data with Insulin/Carb events.
    """
    
    def __init__(self, kinetics: Optional[MetabolicKinetics] = None):
        self.kinetics = kinetics or MetabolicKinetics()
        self.max_rate_of_change = 4.0 # mg/dL per minute (Physiological max)
        
    def process_data(self, 
                     glucose_records: List[GlucoseReading], 
                     treatments: List[TreatmentEvent]) -> pd.DataFrame:
        """
        Main pipeline to transform raw records into a clean, 5-minute grid DataFrame.
        """
        if not glucose_records:
            logger.warning("No glucose records provided to IngestionEngine.")
            return pd.DataFrame()

        # 1. Convert to DataFrame and deduplicate
        df_g = pd.DataFrame([
            {'timestamp': r.timestamp, 'sgv': r.sgv, 'source': r.source} 
            for r in glucose_records
        ])
        df_g = df_g.sort_values('timestamp').drop_duplicates(subset='timestamp')
        df_g.set_index('timestamp', inplace=True)

        # 2. Resample to 5-minute grid
        df_g = df_g.resample('5T').mean()

        # 3. Clean Noise (Physiological Filter + Rolling Median)
        df_g['sgv_raw'] = df_g['sgv']
        
        # Simple rolling median to strip spikes
        df_g['sgv'] = df_g['sgv'].rolling(window=3, center=True).median()
        
        # 4. Interpolate Short Gaps (< 20 mins)
        # Limit=4 for 5-minute intervals = 20 mins
        df_g['sgv'] = df_g['sgv'].interpolate(method='linear', limit=4)

        # 5. Calculate Velocity & Acceleration
        df_g['velocity'] = df_g['sgv'].diff() / 5.0 # mg/dL/min
        df_g['acceleration'] = df_g['velocity'].diff() / 5.0 # mg/dL/min^2
        
        # Remove points violating physiological constraints (Rate of Change > 4mg/dL/min)
        # This flags 'garbage' sensor jumps
        mask = df_g['velocity'].abs() > self.max_rate_of_change
        if mask.any():
            logger.warning(f"Detected {mask.sum()} points violating physiological constraints. Cleaning...")
            df_g.loc[mask, 'sgv'] = np.nan
            # Re-interpolate if needed
            df_g['sgv'] = df_g['sgv'].interpolate(method='linear', limit=2)

        # 6. Synchronize Treatments (IOB / COB)
        treat_list = [
            {'timestamp': t.timestamp, 'insulin': t.insulin, 'carbs': t.carbs} 
            for t in treatments
        ]
        
        def calculate_kinetics(row):
            impact = self.kinetics.get_bolus_impact(treat_list, row.name)
            return pd.Series(impact)

        # Map IOB/COB to every grid point
        kinetics_df = df_g.apply(calculate_kinetics, axis=1)
        df_final = pd.concat([df_g, kinetics_df], axis=1)

        # 7. Final Clean up
        # Remove any rows where glucose is still missing (Long gaps)
        df_final.dropna(subset=['sgv'], inplace=True)
        
        logger.info(f"Ingestion complete. Processed {len(df_final)} synchronized data points.")
        return df_final

    def save_to_parquet(self, df: pd.DataFrame, file_path: str):
        """Saves processed data to Parquet for fast, linkable access by the agent."""
        try:
            df.to_parquet(file_path)
            logger.info(f"Data successfully persisted to {file_path}")
        except Exception as e:
            logger.error(f"Failed to save parquet: {e}")

if __name__ == "__main__":
    # Integration Test / Mock Data
    from datetime import datetime
    
    # Mock some data
    now = datetime.now()
    mock_glucose = [
        GlucoseReading(timestamp=now - timedelta(minutes=i*5), sgv=100 + (i % 5))
        for i in range(20)
    ]
    # Add a 'garbage' spike
    mock_glucose[5] = GlucoseReading(timestamp=now - timedelta(minutes=25), sgv=300) 
    
    mock_treatments = [
        TreatmentEvent(timestamp=now - timedelta(minutes=45), insulin=2.0, carbs=45.0)
    ]
    
    engine = IngestionEngine()
    df = engine.process_data(mock_glucose, mock_treatments)
    
    print("\nProcessed Data Sample (Last 5 mins):")
    print(df[['sgv', 'velocity', 'iob', 'cob']].tail())
    
    if 300 in df['sgv'].values:
        print("\nFAILURE: Garbage spike was not filtered.")
    else:
        print("\nSUCCESS: Garbage spike was filtered/smoothed.")
