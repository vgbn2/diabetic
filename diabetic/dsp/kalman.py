import numpy as np
from filterpy.kalman import KalmanFilter
from filterpy.common import Q_discrete_white_noise
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic import medical_constants
from diabetic.dsp.metabolic_math import MetabolicMath

class GlucoseFilter:
    """
    2D Kalman Filter for glucose tracking.
    State vector [x, v]:
    x = glucose concentration (mmol/L)
    v = velocity (mmol/L per minute)
    
    Handles variable dt and uses innovation-based clamping for outlier rejection.
    """
    def __init__(self, dt: float = None):
        if dt is None:
            from diabetic.config import config
            dt = config.SAMPLING_INTERVAL_MINS
            
        self.kf = KalmanFilter(dim_x=3, dim_z=1)
        self.dt = dt  # Default dt
        self.last_ts = None
        self.initialized = False
        
        # Measurement Function (We only measure glucose: z = [1 0 0] * [x v a]')
        self.kf.H = np.array([[1.0, 0.0, 0.0]])
        
        # Initial State Covariance (High uncertainty to start, focusing on measurement)
        self.kf.P = np.eye(3) * 10.0
        self.kf.P[0,0] = 1.0 # High confidence in initial glucose reading
        
        # Measurement Noise (Estimated sensor error variance)
        self.kf.R = np.array([[medical_constants.KALMAN_MEASUREMENT_NOISE]])
        
        # Process Noise spectral density (tuned for metabolic changes)
        # We assume the metabolic process is somewhat smooth (low q_var).
        self.q_var = 1e-5 

    def _update_matrices(self, dt: float):
        """Updates Transition Matrix F and Process Noise Q based on actual dt."""
        from diabetic import medical_constants
        
        # Damping factor: current momentum tapers over time (Wave 6)
        # Ensures velocity doesn't project to infinity during data gaps.
        damping = np.exp(-dt / medical_constants.KINEMATIC_DECAY_MINS)
        
        # F = [[1, dt, 0.5*dt^2],
        #      [0, damping, dt],
        #      [0, 0, damping]]
        self.kf.F = np.array([
            [1.0, dt, 0.5 * (dt**2)],
            [0.0, damping, dt],
            [0.0, 0.0, damping]
        ])
        
        # Q = Process Noise Matrix
        self.kf.Q = Q_discrete_white_noise(dim=3, dt=dt, var=self.q_var)

    def update(self, reading: GlucoseReading) -> MetabolicSnapshot:
        """Processes a new reading and returns a smoothed snapshot."""
        
        # 1. Handle Initialization
        if not self.initialized:
            self.kf.x = np.array([[reading.value], [0.],[0.]])
            self.last_ts = reading.timestamp
            self.initialized = True
            self._update_matrices(self.dt) 
            return MetabolicSnapshot(
                glucose=reading,
                filtered_value=float(reading.value),
                velocity=0.0,
                acceleration=0.0
            )

        # 2. Calculate actual dt from timestamps
        dt = MetabolicMath.get_dt(reading.timestamp, self.last_ts)
        
        if dt > medical_constants.STALE_DATA_TIMEOUT_SECS / 60.0:
            self.initialized = False
            return self.update(reading)
            
        self._update_matrices(dt)
        self.last_ts = reading.timestamp
        
        # 3. Predict & Innovation-based clamping (Outlier handling)
        self.kf.predict()
        
        # Calculate Innovation (Residual): y = z - Hx
        z_raw = reading.value
        y = z_raw - (self.kf.H @ self.kf.x)[0,0]
        
        # Innovation Covariance: S = HPH' + R
        # For H = [[1, 0]], S is simply P[0,0] + R
        S = self.kf.P[0,0] + self.kf.R[0,0]
        std_dev = np.sqrt(S)
        
        # 3-Sigma Clamping:
        # If the gap between measurement and prediction is too large,
        # we clamp the measurement to the 3-sigma boundary to prevent
        # the filter from 'exploding' due to sensor dropouts (compression artifacts).
        limit = 3.0 * std_dev
        z_effective = z_raw
        if abs(y) > limit:
            clamped_y = np.sign(y) * limit
            z_effective = (self.kf.H @ self.kf.x)[0,0] + clamped_y
            
        self.kf.update(np.array([[z_effective]]))
        
        # 4. Extract results
        x = self.kf.x.flatten()[0]
        v = self.kf.x.flatten()[1]
        a = self.kf.x.flatten()[2]
        
        return MetabolicSnapshot(
            glucose=reading,
            filtered_value=float(x),
            velocity=float(v),
            acceleration=float(a)
        )
