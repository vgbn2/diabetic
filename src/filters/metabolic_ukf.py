import numpy as np
from filterpy.kalman import UnscentedKalmanFilter as UKF
from filterpy.kalman import MerweScaledSigmaPoints
from typing import Dict, Any, Optional
from ..logger import logger

class MetabolicUKF:
    """
    Unscented Kalman Filter for non-linear metabolic state estimation.
    State Vector (x): [Glucose (G), Velocity (V), Remote Insulin (X), IOB, COB, DSI]
    
    Refined: Implements Bergman Minimal Model ODEs for non-linear transitions.
    """
    
    def __init__(self, dt: float = 5.0):
        self.dt = dt
        
        # Bergman Parameters (Physiological constants)
        self.p1 = 0.02   # Glucose effectiveness
        self.p2 = 0.01   # Insulin disappearance rate
        self.p3 = 0.000013 # Insulin-dependent glucose uptake rate
        self.Gb = 90.0   # Basal Glucose (mg/dL)
        
        # Scaled Sigma Points for UKF
        points = MerweScaledSigmaPoints(n=6, alpha=0.1, beta=2., kappa=1.)
        
        self.ukf = UKF(dim_x=6, dim_z=1, dt=self.dt, fx=self.transition_function, 
                       hx=self.observation_function, points=points)
        
        # Process Noise (Q)
        self.ukf.Q = np.diag([
            1.0,    # G (Glucose)
            0.1,    # V (Kinematic Velocity)
            1e-6,   # X (Remote Insulin Action - very small magnitude)
            0.05,   # IOB
            0.5,    # COB
            0.02    # DSI (Stress)
        ])
        
        # Measurement Noise (R)
        self.ukf.R = np.array([[25.0]]) 
        
        # Initial State: [G, V, X, IOB, COB, DSI]
        self.ukf.x = np.array([100.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        self.ukf.P *= 10.0

    def transition_function(self, x, dt):
        """
        Non-linear physiological transition model (Bergman-based).
        x = [G, V, X, IOB, COB, DSI]
        """
        G, V, X, IOB, COB, DSI = x
        
        # 1. Stress-Adjusted Sensitivity
        # High DSI (stress) dampens the effectiveness of remote insulin (X)
        # We use max(0.1, DSI) to prevent NaNs during sigma point generation if DSI becomes negative in P
        dsi_safe = max(0.1, DSI)
        p3_effective = self.p3 / (dsi_safe ** 1.5)
        
        # 2. Bergman ODEs
        # dG/dt = -p1(G - Gb) - X*G + carb_release
        # dX/dt = -p2*X + p3*Insulin_Input
        
        carb_impact = 3.0 # mg/dL per gram
        carb_release = (COB * carb_impact * 0.05) # 5% release per min
        
        dG = -self.p1 * (G - self.Gb) - X * G + carb_release
        dX = -self.p2 * X + p3_effective * (IOB * 10.0) # Scale IOB to plasma insulin approx
        
        # 3. Kinematic fallbacks (to capture short term trends not explained by Bergman)
        new_G = G + dG * dt + (V * dt) # Fuse physics-model with kinematic trend
        new_V = V # Velocity remains as a latent kinematic trend
        new_X = X + dX * dt
        
        # 4. Metabolic Decay
        new_IOB = IOB * 0.95
        new_COB = COB * 0.90
        new_DSI = DSI
        
        return np.array([new_G, new_V, new_X, new_IOB, new_COB, new_DSI])

    def observation_function(self, x):
        """Maps 6D state to 1D Glucose measurement."""
        return np.array([x[0]])

    def update(self, z_glucose: float, iob: float = 0.0, cob: float = 0.0, dsi: float = 1.0):
        """Runs one step of the non-linear UKF."""
        self.ukf.x[3] = iob
        self.ukf.x[4] = cob
        self.ukf.x[5] = dsi
        
        self.ukf.predict(dt=self.dt)
        self.ukf.update(np.array([z_glucose]))
        
        state = self.ukf.x
        return {
            "glucose": state[0],
            "velocity": state[1],
            "remote_insulin": state[2],
            "iob": state[3],
            "cob": state[4],
            "dsi": state[5],
            "confidence": 1.0 / (np.trace(self.ukf.P) + 1e-6)
        }
