"""
diabetic/coordinator_pipeline.py

Isolated per-tenant state and signal processing pipeline.
Prevents cross-patient Kalman filter and prediction contamination in multi-tenant environments.
"""
from collections import deque
from datetime import datetime, timezone
from typing import Optional, List
import logging

from diabetic import medical_constants
from diabetic.dsp.kalman import GlucoseFilter
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.ml_engine.inference import MetabolicInferenceRunner
from diabetic.ml_engine.oracle import BasalOracle
from diabetic.registry import MetabolicSnapshot, GlucoseReading, MealEvent, InsulinDose
from diabetic.config import config
from diabetic.utils.audit_logger import AuditLogger


class TenantPipeline:
    """
    Encapsulates isolated DSP filtering, digital twin state,
    neural prediction buffer, and metabolic snapshot history for one patient.
    """
    def __init__(
        self,
        tenant_id: str,
        audit_logger: Optional[AuditLogger] = None,
        weight_kg: float = config.PATIENT_WEIGHT_KG,
        height_cm: float = config.PATIENT_HEIGHT_CM,
        gender: str = config.PATIENT_GENDER,
        diabetes_type: str = config.PATIENT_DIABETES_TYPE,
        age: float = config.PATIENT_AGE,
    ):
        self.tenant_id = tenant_id
        self.audit = audit_logger
        self.logger = logging.getLogger(f"Bio-Quant.TenantPipeline.{tenant_id}")

        self.filter = GlucoseFilter()
        self.neural_runner = MetabolicInferenceRunner()
        self.twin = DigitalTwin(
            weight_kg=weight_kg,
            height_cm=height_cm,
            gender=gender,
            diabetes_type=diabetes_type,
            age=age,
        )
        self.oracle = BasalOracle(history_days=3)
        self.snapshots: deque[MetabolicSnapshot] = deque(maxlen=medical_constants.SNAPSHOT_CAP)
        self.regime_step_count = 0

        self.last_prediction_4h: list = []
        self.last_prediction_1d: list = []

        self.last_meal: Optional[MealEvent] = None
        self.last_provider_meal: Optional[MealEvent] = None
        self.last_provider_insulin: Optional[InsulinDose] = None

        self.meal_window_start: Optional[datetime] = None
        self.meal_tune_pending: bool = False
        self.actual_meal_peak: float = 0.0
        self.pending_meal_forecast_peak: Optional[float] = None
        self._confidence_smoothed: float = 1.0

    @property
    def last_snapshot(self) -> Optional[MetabolicSnapshot]:
        return self.snapshots[-1] if self.snapshots else None
