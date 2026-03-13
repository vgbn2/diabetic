import numpy as np
from filterpy.kalman import UnscentedKalmanFilter as UKF
from filterpy.kalman import MerweScaledSigmaPoints
from typing import Dict, Any, Optional
from ..logger import logger

class MetabolicUKF:
    """
    Unscented Kalman Filter for non-linear metabolic state estimation.
    State Vector (x): [Glucose, Velocity, Acceleration, IOB, COB, DSI]
    """
    
    def __init__(self, dt: float = 5.0):
        """
        :param dt: Time step in minutes (default 5.0 for CGM).
        """
        self.dt = dt
        
        # 1. Define the State Dimension (6) and Measurement Dimension (1: just Glucose)
        # Note: We can expand measurement to 2 if we add Microwave HR as an observation.
        points = MerweScaledSigmaPoints(n=6, alpha=0.1, beta=2., kappa=1.)
        
        self.ukf = UKF(dim_x=6, dim_z=1, fx=self.transition_function, 
                       hx=self.observation_function, points=points)
        
        # 2. Process Noise (Q) - How much we trust our internal model
        # Higher values allow the state to change more rapidly.
        self.ukf.Q = np.diag([
            1.0,    # Glucose (mg/dL)
            0.1,    # Velocity (mg/dL/min)
            0.01,   # Acceleration (mg/dL/min^2)
            0.05,   # IOB (Units)
            0.5,    # COB (Grams)
            0.02    # DSI (Stress)
        ])
        
        # 3. Measurement Noise (R) - How much we trust the CGM sensor
        self.ukf.R = np.array([[25.0]]) # mg/dL variance (standard for CGMs)
        
        # 4. Initial Covariance (P)
        self.ukf.P *= 10.0
        
        # 5. Initial State (x)
        self.ukf.x = np.array([100.0, 0.0, 0.0, 0.0, 0.0, 1.0])

    def transition_function(self, x, dt):
        """
        Non-linear metabolic transition model.
        x = [G, V, A, IOB, COB, DSI]
        """
        G, V, A, IOB, COB, DSI = x
        
        # Standard Kinematics for Glucose
        new_G = G + V * dt + 0.5 * A * dt**2
        new_V = V + A * dt
        new_A = A # Assume constant acceleration for now
        
        # Metobolic Impact: 
        # - IOB reduces glucose (simplified linear model for the filter's 'expectations')
        # - COB increases glucose
        # - High DSI (stress) causes an additional glucose 'drift' (Insulin resistance)
        
        insulin_sensitivity = 40.0 # 1 unit of insulin drops glucose by 40 mg/dL (example)
        carb_impact = 3.0       # 1 gram of carbs raises glucose by 3 mg/dL (example)
        stress_drift = 0.2 * (DSI - 1.0) # Higher stress causes a drift up
        
        new_G -= (IOB * insulin_sensitivity / 60.0) * dt # Integrated impact
        new_G += (COB * carb_impact / 60.0) * dt
        new_G += stress_drift * dt
        
        # Kinetics Decay (Simplified)
        new_IOB = IOB * 0.95 # ~5% decay per 5 mins
        new_COB = COB * 0.90 # ~10% absorption per 5 mins
        new_DSI = DSI        # Stress is slow-moving unless updated by biometrics
        
        return np.array([new_G, new_V, new_A, new_IOB, new_COB, new_DSI])

    def observation_function(self, x):
        """Maps the 6D internal state to the 1D CGM measurement (Glucose)."""
        return np.array([x[0]])

    def update(self, z_glucose: float, iob: float = 0.0, cob: float = 0.0, dsi: float = 1.0):
        """
        Runs one step of the UKF (Predict + Update).
        """
        # Inject known external inputs directly into the state before prediction
        self.ukf.x[3] = iob
        self.ukf.x[4] = cob
        self.ukf.x[5] = dsi
        
        self.ukf.predict(dt=self.dt)
        self.ukf.update(np.array([z_glucose]))
        
        state = self.ukf.x
        return {
            "glucose": state[0],
            "velocity": state[1],
            "acceleration": state[2],
            "iob": state[3],
            "cob": state[4],
            "dsi": state[5],
            "uncertainty": np.trace(self.ukf.P) # Sum of variances (Confidence metric)
        }

if __name__ == "__main__":
    # UKF Simulation Test
    filter = MetabolicUKF()
    
    print("Running UKF Simulation (Post-Meal Spike)...")
    for i in range(10):
        # Mock a rising glucose (100 -> 150) with high COB and low DSI
        z = 100 + (i * 5) 
        result = filter.update(z_glucose=z, iob=0.0, cob=30.0, dsi=1.2)
        
        print(f"T+{i*5}m | Meas: {z} | Filtered G: {result['glucose']:.1f} | Velocity: {result['velocity']:.2f}")
