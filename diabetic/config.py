import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict
from diabetic import medical_constants

class Settings(BaseSettings):
    # Core Medical APIs
    NIGHTSCOUT_URL: str = ""
    API_SECRET: str = ""
    OPENWEATHER_API_KEY: str = ""
    WEATHER_MOCK_MODE: bool = True
    
    # Alerting (Telegram)
    TELEGRAM_TOKEN: str = Field("", validation_alias="TELEGRAM_BOT_TOKEN")
    USER_ID: int = Field(0, validation_alias="TELEGRAM_CHAT_ID")
    CAREGIVER_ID: Optional[int] = None
    
    # System Config
    LOG_LEVEL: str = "INFO"
    DATA_POLLING_INTERVAL: int = 150  # 2,5 minutes
    # Medical Units
    PREFER_MMOL: bool = True
    SAMPLING_INTERVAL_MINS: float = medical_constants.SAMPLING_INTERVAL_MINS
    
    # Patient Profile (Layer One - Physiological Baselines)
    PATIENT_AGE: int = 30
    PATIENT_WEIGHT_KG: float = 75.0
    PATIENT_HEIGHT_CM: float = 175.0
    PATIENT_ETHNICITY: str = "ASIAN" # Baseline for insulin resistance bias
    PATIENT_NATIONALITY: str="VIETNAMESE"
    PATIENT_RELIGION: str = "NON_RELIGIOUS" 
    PATIENT_GENDER: str = "FEMALE"  # "MALE" or "FEMALE"
    PATIENT_DIABETES_TYPE: str = "T1D" # From E10.7 code
    PATIENT_DIAGNOSIS_YEAR: int = 2020
    PATIENT_ACTIVITY_LEVEL: str = "MODERATE"
    
    # Clinical Lab Results (Personalization 2.2)
    PATIENT_FRUCTOSAMIN: float = 347.6 # High avg sugar sentinel
    PATIENT_MICROALBUMINURIA: bool = True # Based on 0.3g/L Protein
    PATIENT_INFLAMMATORY_MARKER: bool = True # Based on 70 LEU
    PATIENT_CYCLE_START: str = "2026-04-01" # Anchor for 28-day hormonal cycle (if Female)
    
    PATIENT_GB_MMOL: float = 8.4
    PATIENT_HRV_BASELINE: float = 50.0
    PATIENT_BPM_BASELINE: float = 70.0  # Default 70bpm
    
    # Global Location (Weather Synchronization)
    LATITUDE: float  = medical_constants.DEFAULT_LATITUDE
    LONGITUDE: float = medical_constants.DEFAULT_LONGITUDE
    
    # UI & Alert Settings
    UI_SETTINGS: Dict[str, str] = {
        "EMERGENCY": "🚨 EMERGENCY",
        "HIGH": "⚠️ WARNING",
        "CRITICAL_HYPER": "🔺 CRITICAL HYPER",
        "FAINT_RISK": "💫 FAINT RISK",
        "INFO": "ℹ️ INFO"
    }
    
    # Infrastructure
    MONGO_URI: str = ""
    RENDER_EXTERNAL_URL: str = ""
    HEART_RATE_SENSOR_ADDRESS: str = "MOCK" # Set to XX:XX... for BLE
    
    # Local High-Availability (Task 8.1.1)
    LOCAL_DB_PATH: str = "storage/audit.db"
    BACKFILL_MAX_HOURS: int = 24
    LOCAL_GUI_ENABLED: bool = True
    
    # --- WAVE 5: UI & Network parameters ---
    LIVE_HISTORY_HOURS: float = 8.0
    BLE_RECONNECT_SECS: int = 30
    PUSH_TIMEOUT_SECS: float = 5.0
    POLLING_INTERVAL_SECS: int = 300
    
    FRONTEND_PUSH_URL: str = "http://localhost:10000/api/push"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Singleton instance
config = Settings()
