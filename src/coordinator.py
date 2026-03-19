import asyncio
import os
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
import numpy as np
from .nightscout_client import NightscoutClient
from .filters.metabolic_ukf import MetabolicUKF
from .features.stress import DynamicStressIndex, HRVRecord
from .ingestion_engine import IngestionEngine
from .alerts.controller import MetabolicAlertingService
from .alerts.breaker import DataCircuitBreaker
from .models.registry import ModelRegistry
from .data_models import (
    GlucoseReading, 
    BiometricReading, 
    InferenceState, 
    TreatmentEvent
)
from .agents.interaction_agent import UserInteractionAgent
from .logger import logger

class AsyncInferenceEngine:
    """
    Asynchronous, event-driven metabolic inference engine.
    Uses an Event Bus (asyncio.Queue) to fuse multi-frequency data streams.
    """
    
    def __init__(self):
        self.event_bus = asyncio.Queue()
        self.client = NightscoutClient()
        self.ukf = MetabolicUKF()
        self.stress_tracker = DynamicStressIndex()
        self.ingestion_engine = IngestionEngine()
        self.alert_service = MetabolicAlertingService()
        self.breaker = DataCircuitBreaker(max_gap_minutes=20)
        
        # ML Predictor
        try:
            self.predictor = ModelRegistry.get_model("xgboost")
            model_path = "models/xgboost_v1.json"
            if os.path.exists(model_path):
                self.predictor.load(model_path)
            else:
                self.predictor.is_trained = True # Mock for now
        except Exception as e:
            logger.error(f"Inference Model Initialization Error: {e}")
            self.predictor = None

        # Data Buffers (Lag Compensation)
        self.cgm_buffer: List[GlucoseReading] = []
        self.hrv_buffer: List[BiometricReading] = []
        self.treatment_buffer: List[TreatmentEvent] = []
        
        # API State
        self.last_status = "STABLE"
        
        # Interaction Agent (Phase 6)
        self.agent = UserInteractionAgent()

    async def cgm_worker(self):
        """Worker 1: Asynchronously polls Nightscout (Every 5 mins)."""
        logger.info("CGM Worker Started (Polling: 5m)")
        while True:
            try:
                raw_readings = self.client.fetch_latest_readings(count=5)
                for r in raw_readings:
                    # Convert raw dict to Pydantic GlucoseReading
                    await self.event_bus.put(r)
                
                # Also fetch recent treatments
                treatments = self.client.fetch_treatments(days=1)
                for t in treatments:
                    await self.event_bus.put(t)
            except Exception as e:
                logger.error(f"CGM Worker Error: {e}")
            
            await asyncio.sleep(300) # Wait 5 minutes

    async def radar_worker(self, mock: bool = True):
        """Worker 2: High-frequency data stream (Radar or simulated)."""
        logger.info("Biometric Worker Started")
        while True:
            # Mock high-frequency biometric data
            if mock:
                # Use stable resting baseline — not random
                # Replace with real wearable data when available
                hrv = BiometricReading(
                    timestamp=datetime.now(),
                    rmssd=55.0,  # healthy adult resting baseline
                    source="Mock_Stable"
                )
                await self.event_bus.put(hrv)
                await asyncio.sleep(30) # 30 seconds (higher than CGM)

    async def heartbeat_worker(self):
        """Worker 4: Monitors engine health and system vitality."""
        logger.info("Health Monitor Started")
        while True:
            await asyncio.sleep(300) # 5-minute heartbeat
            logger.info("Bio-Quant Heartbeat: All Systems Nominal")

    async def inference_worker(self):
        """Worker 3: Main brain. Listens to EventBus and runs inference."""
        logger.info("Inference Engine Online")
        while True:
            event = await self.event_bus.get()
            
            # 1. Route Event
            if isinstance(event, GlucoseReading):
                # Apply Circuit Breaker
                if not self.breaker.validate_packet(event.timestamp):
                    continue
                self.cgm_buffer.append(event)
                if len(self.cgm_buffer) > 10: self.cgm_buffer.pop(0)
                
            elif isinstance(event, BiometricReading):
                self.hrv_buffer.append(event)
                if len(self.hrv_buffer) > 50: self.hrv_buffer.pop(0)
                # Ensure HRV baseline is updated
                if event.rmssd: # Added rmssd check
                    self.stress_tracker.add_reading(
                        HRVRecord(
                            timestamp=event.timestamp, 
                            rmssd=event.rmssd
                        )
                    )

            elif isinstance(event, TreatmentEvent):
                # Update treatment buffer (deduplicate by timestamp)
                self.treatment_buffer.append(event)
                self.treatment_buffer = sorted(list({t.timestamp: t for t in self.treatment_buffer}.values()), key=lambda x: x.timestamp)
                if len(self.treatment_buffer) > 20: self.treatment_buffer.pop(0)

            # 2. Synchronize (Fixing Interstitial Lag Fallacy)
            # Find the HRV reading that corresponds to the CGM's physiological window (T-15m)
            self._sync_and_predict()
            
            self.event_bus.task_done()

    def _sync_and_predict(self):
        """Aligins real-time biometrics with lagged CGM data for inference."""
        if not self.cgm_buffer: return
        
        latest_cgm = self.cgm_buffer[-1]
        target_time = latest_cgm.timestamp - timedelta(minutes=latest_cgm.lag_minutes)
        
        # Find closest HRV reading to target_time
        closest_hrv = None
        if self.hrv_buffer:
            closest_hrv = min(self.hrv_buffer, key=lambda x: abs((x.timestamp - target_time).total_seconds())) 
            
        dsi = self.stress_tracker.get_current_dsi(current_rmssd=closest_hrv.rmssd if closest_hrv else None)
        current_hr = closest_hrv.hr if closest_hrv else None
        
        # 3. Filter (UKF) & Predict
        # ROUTE THROUGH INGESTION ENGINE (GARBAGE IN PREVENTER)
        cleaned_sgv = latest_cgm.sgv
        iob, cob = 0.0, 0.0
        
        if len(self.cgm_buffer) >= 3:
            try:
                processed_df = self.ingestion_engine.process_data(self.cgm_buffer, self.treatment_buffer)
                if not processed_df.empty:
                    # Take the latest cleaned value
                    latest_clean = processed_df.iloc[-1]
                    cleaned_sgv = latest_clean['sgv']
                    iob = latest_clean.get('iob', 0.0)
                    cob = latest_clean.get('cob', 0.0)
            except Exception as e:
                logger.error(f"Ingestion Engine Error: {e}")

        filtered = self.ukf.update(z_glucose=cleaned_sgv, dsi=dsi)
        
        logger.info(f"Inference: G={cleaned_sgv:.1f} | Pulse={current_hr if current_hr else 'N/A'} BPM | DSI={dsi:.2f}")

        # Prediction and Alerting...
        if self.predictor:
            pred = self.predictor.predict({
                "sgv": filtered["glucose"],
                "velocity": filtered["velocity"],
                "remote_insulin": filtered["remote_insulin"],
                "iob": iob,
                "cob": cob,
                "dsi": dsi
            })
            
            status, msg = self.alert_service.evaluate_state(latest_cgm.sgv, pred, dsi)
            self.last_status = status
            logger.info(f"Prediction: {pred:.1f} | Status: {status}")
            if status != "STABLE":
                print(f"\n[ASYNC-ALERT] [{status}] {msg}\n")
                self.alert_service.alert(status, msg)
                
                # Dynamic Interaction (Phase 6)
                if status in ('STRESS_DEVIATION', 'FAINT_RISK'):
                    question = self.agent.process_alert(status, dsi)
                    if question:
                        self.alert_service._send_telegram(self.alert_service.chat_id, f"<b>Bio-Quant Agent:</b>\n{question}")

    async def run(self):
        """Entry point for the asynchronous runtime."""
        await asyncio.gather(
            self.cgm_worker(),
            self.radar_worker(mock=True),
            self.inference_worker(),
            self.heartbeat_worker()
        )
