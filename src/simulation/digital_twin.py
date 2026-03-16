import numpy as np
import pandas as pd
from typing import List, Dict, Tuple
from datetime import datetime, timedelta
from ..logger import logger

class BergmanDigitalTwin:
    """
    Physiology Simulator based on the Bergman Minimal Model.
    Generates realistic blood glucose trajectories based on Insulin (I), 
    Carbohydrates (G_meal), and Stress (DSI).
    """
    
    def __init__(self, dt: float = 1.0):
        """
        :param dt: Simulation step size in minutes.
        """
        self.dt = dt
        
        # Bergman Parameters (Physiological constants)
        self.p1 = 0.02   # Glucose effectiveness (1/min)
        self.p2 = 0.01   # Insulin disappearance rate (1/min)
        self.p3 = 0.000013 # Insulin-dependent glucose uptake rate
        self.Gb = 90.0   # Basal Glucose (mg/dL)
        self.Ib = 10.0   # Basal Insulin (uU/mL)
        
        # Current State
        self.G = self.Gb
        self.X = 0.0 # Remote insulin action
        self.I = self.Ib

    def step(self, insulin_bolus: float = 0.0, carb_intake: float = 0.0, dsi: float = 1.0) -> float:
        """
        Computes one minute of glucose dynamics.
        :param dsi: Dynamic Stress Index (1.0 = Baseline, >1.0 = Stress-induced resistance)
        """
        # 1. Insulin Resistance from Stress (DSI-aware)
        # Stress (DSI) reduces the effectiveness of remote insulin (X)
        dsi_safe = max(0.1, dsi)
        p3_effective = self.p3 / (dsi_safe ** 1.5)
        
        # 2. Bergman Equations (ODE)
        # dG/dt = -p1(G - Gb) - X*G + meal_input
        # dX/dt = -p2*X + p3(I - Ib)
        
        # Simplify meal/carb absorption as a linear input for the simulation
        meal_input = carb_intake * 0.1 # Very simplified
        
        dG = -self.p1 * (self.G - self.Gb) - self.X * self.G + meal_input
        dX = -self.p2 * self.X + p3_effective * (self.I - self.Ib)
        
        # Update State
        self.G += dG * self.dt
        self.X += dX * self.dt
        
        # Simple Insulin bolus impact (spikes I)
        self.I += (insulin_bolus * 5.0) - (self.I - self.Ib) * 0.1 
        
        return self.G

    def generate_dataset(self, days: int = 7) -> pd.DataFrame:
        """
        Generates a 5-minute interval dataset for ML training.
        Simulates random meals, insulin boluses, and stress spikes.
        """
        logger.info(f"Digital Twin: Simulating {days} days of metabolic data...")
        
        total_minutes = days * 24 * 60
        data = []
        current_time = datetime.now()
        
        # State variables for randomized events
        meal_timer = 0
        stress_timer = 0
        current_dsi = 1.0
        
        for t in range(total_minutes):
            insulin = 0.0
            carbs = 0.0
            
            # Random Meals (3 per day + snacks)
            if meal_timer <= 0 and np.random.random() < 0.001:
                carbs = np.random.uniform(20, 80)
                insulin = carbs / 10.0 # Standard 1:10 ratio
                meal_timer = 240 # Wait 4 hours for next meal
            
            # Random Stress Spikes
            if stress_timer <= 0 and np.random.random() < 0.0005:
                current_dsi = np.random.uniform(1.8, 2.5) # Acute stress
                stress_timer = 120 # Stress lasts 2 hours
            elif stress_timer > 0:
                stress_timer -= 1
                if stress_timer == 0: current_dsi = 1.0
            
            if meal_timer > 0: meal_timer -= 1
            
            # Run simulation step
            g = self.step(insulin_bolus=insulin, carb_intake=carbs, dsi=current_dsi)
            
            # Record every 5 minutes (standard CGM interval)
            if t % 5 == 0:
                data.append({
                    "timestamp": current_time + timedelta(minutes=t),
                    "sgv": g + np.random.normal(0, 2), # Add sensor noise
                    "dsi": current_dsi,
                    "iob": insulin, # Simplified for dataset
                    "cob": carbs
                })
                
        df = pd.DataFrame(data)
        logger.info(f"Digital Twin: Simulation complete. {len(df)} samples generated.")
        return df

if __name__ == "__main__":
    twin = BergmanDigitalTwin()
    df = twin.generate_dataset(days=1)
    print(df.head())
    print(df.describe())
