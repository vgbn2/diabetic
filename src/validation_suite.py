import numpy as np
from src.coordinator import MetabolicInferenceEngine
from src.physics.radar_physics import RadarPhysicsEngine
from src.ingestion.radar import UWBRadarProcessor
from src.logger import logger

class SystemValidationSuite:
    """
    Unit and integration validation for the Metabolic Inference layers.
    """
    
    def __init__(self):
        self.engine = MetabolicInferenceEngine(use_mock_model=True)
        self.physics = RadarPhysicsEngine()
        self.radar_processor = UWBRadarProcessor()

    def val_radar_extraction(self):
        t_hr, t_rr = 75.0, 18.0
        matrix = self.physics.simulate_radar_return(hr_bpm=t_hr, rr_bpm=t_rr)
        vitals = self.radar_processor.extract_vitals(matrix)
        success = (abs(vitals['hr'] - t_hr) / t_hr) < 0.05
        return "PASSED" if success else "FAILED"

    def val_stress_correlation(self):
        # High glucose + High DSI
        self.engine.ukf.ukf.x = np.array([320.0, 1.0, 0.0, 0.0, 0.0, 2.5]) 
        res = self.engine.run_cycle(current_hrv=10.0)
        return "PASSED" if res['alert_level'] == "FAINT_RISK" else "FAILED"

    def run_suite(self):
        print(f"\n{'LAYER':<25} | {'STATUS':<10}")
        print("-" * 40)
        print(f"{'PHYSICS_RADAR_DSP':<25} | {self.val_radar_extraction():<10}")
        print(f"{'METABOLIC_STRESS_LOGIC':<25} | {self.val_stress_correlation():<10}")

if __name__ == "__main__":
    SystemValidationSuite().run_suite()
