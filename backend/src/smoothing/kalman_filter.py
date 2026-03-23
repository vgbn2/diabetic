import numpy as np
from filterpy.kalman import KalmanFilter
from backend.src.registry import GlucoseReading, MetabolicSnapshot

class GlucoseFilter:
    """
    2D Kalman Filter for glucose tracking.
    State vector [x, v]:
    x = glucose concentration (mmol/L)
    v = velocity (mmol/L per minute)
    """
    def __init__(self, dt: float = None):
        if dt is None:
            from backend.src.config import config
            dt = config.SAMPLING_INTERVAL_MINS
        self.kf = KalmanFilter(dim_x=2, dim_z=1)
        
        # State Transition Matrix (Constant Velocity Model)
        self.kf.F = np.array([[1., dt],
                              [0., 1.]])
        
        # Measurement Function (We only measure glucose, not velocity)
        self.kf.H = np.array([[1., 0.]])
        
        # Initial State Covariance
        self.kf.P *= 1000.
        
        # Measurement Noise (Estimated sensor error ~0.5 mmol/L)
        self.kf.R = np.array([[0.25]])
        
        # Process Noise (Physiological variability)
        self.kf.Q = np.array([[0.01, 0.01],
                              [0.01, 0.01]])
        
    def update(self, reading: GlucoseReading) -> MetabolicSnapshot:
        """Processes a new reading and returns a smoothed snapshot."""
        z = np.array([[reading.value]])
        
        self.kf.predict()
        self.kf.update(z)
        
        x, v = self.kf.x
        
        return MetabolicSnapshot(
            glucose=reading,
            filtered_value=float(x),
            velocity=float(v),
            acceleration=0.0 # Will be calculated in features module
        )

if __name__ == "__main__":
    # Test smoothing
    from datetime import datetime
    f = GlucoseFilter()
    readings = [
        GlucoseReading(timestamp=datetime.now(), value=8.0, trend="Flat"),
        GlucoseReading(timestamp=datetime.now(), value=8.5, trend="FortyFiveUp"),
        GlucoseReading(timestamp=datetime.now(), value=9.2, trend="Up"),
        GlucoseReading(timestamp=datetime.now(), value=10.0, trend="Up")
    ]
    
    for r in readings:
        snap = f.update(r)
        print(f"RAW: {r.value} -> FILTERED: {snap.filtered_value:.2f} (V: {snap.velocity:.4f})")
