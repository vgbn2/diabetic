import os
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict
from diabetic import medical_constants

class Settings(BaseSettings):
# =============================================================================
# 🔐 [LAYER 0: CORE MEDICAL & ALERTING APIs]
# =Focus: Nightscout, OpenWeather, and Telegram Credentials
# =============================================================================
    NIGHTSCOUT_URL: str = ""
    API_SECRET: str = Field("", validation_alias="NIGHTSCOUT_API_SECRET")
    OPENWEATHER_API_KEY: str = ""
    WEATHER_MOCK_MODE: bool = True
    
    # Alerting (Telegram)
    TELEGRAM_TOKEN: str = Field("", validation_alias="TELEGRAM_BOT_TOKEN")
    USER_ID: int = Field(0, validation_alias="TELEGRAM_CHAT_ID")
    CAREGIVER_ID: Optional[int] = None
    
# =============================================================================
# ⚙️ [SYSTEM RUNTIME & SAMPLING]
# =Focus: Polling intervals, Logging levels, and Data Stability
# =============================================================================
    LOG_LEVEL: str = "INFO"
    DATA_POLLING_INTERVAL: int = 150  # 2,5 minutes
    PREFER_MMOL: bool = True
    SAMPLING_INTERVAL_MINS: float = medical_constants.SAMPLING_INTERVAL_MINS
    
# =============================================================================
# 🧬 [PHYSIOLOGICAL BASELINE PROFILE]
# =Focus: Layer 1 Hardware/Biological Static Markers
# =============================================================================
    PATIENT_AGE: int = Field(30, validation_alias="PATIENT_AGE")
    PATIENT_WEIGHT_KG: float = Field(75.0, validation_alias="PATIENT_WEIGHT_KG")
    PATIENT_HEIGHT_CM: float = Field(175.0, validation_alias="PATIENT_HEIGHT_CM")
    PATIENT_ETHNICITY: str = Field("UNKNOWN", validation_alias="PATIENT_ETHNICITY")
    PATIENT_NATIONALITY: str = Field("UNKNOWN", validation_alias="PATIENT_NATIONALITY")
    PATIENT_RELIGION: str = Field("NON_RELIGIOUS", validation_alias="PATIENT_RELIGION")
    PATIENT_GENDER: str = Field("FEMALE", validation_alias="PATIENT_GENDER")
    PATIENT_DIABETES_TYPE: str = Field("T1D", validation_alias="PATIENT_DIABETES_TYPE")
    PATIENT_DIAGNOSIS_YEAR: int = Field(2020, validation_alias="PATIENT_DIAGNOSIS_YEAR")
    PATIENT_ACTIVITY_LEVEL: str = Field("MODERATE", validation_alias="PATIENT_ACTIVITY_LEVEL")
    
# =============================================================================
# 🌍 [REGIONAL & MAINTENANCE LOGIC]
# =Focus: Timezone Discovery and Automated Sync Scheduling
# =============================================================================
    USER_TIMEZONE: str = Field("Asia/Ho_Chi_Minh", validation_alias="BIO_USER_TIMEZONE")
    MAINTENANCE_LOCAL_HOUR: int = Field(3, validation_alias="BIO_MAINTENANCE_HOUR")
    
    # Clinical Lab Results (Personalization 2.2) - MUST BE SET IN .ENV
    PATIENT_FRUCTOSAMIN: float = Field(300.0, validation_alias="PATIENT_FRUCTOSAMIN")
    PATIENT_MICROALBUMINURIA: bool = Field(False, validation_alias="PATIENT_MICROALBUMINURIA")
    PATIENT_INFLAMMATORY_MARKER: bool = Field(False, validation_alias="PATIENT_INFLAMMATORY_MARKER")
    PATIENT_CYCLE_START: str = Field("2026-01-01", validation_alias="PATIENT_CYCLE_START")
    
    PATIENT_GB_MMOL: float = 8.4
    PATIENT_HRV_BASELINE: float = 50.0
    PATIENT_BPM_BASELINE: float = 70.0  # Default 70bpm
    
    # Global Location (Weather Synchronization)
    LATITUDE: float  = medical_constants.DEFAULT_LATITUDE
    LONGITUDE: float = medical_constants.DEFAULT_LONGITUDE
    
# =============================================================================
# 📱 [INTERACTION & HARDWARE STACK]
# =Focus: UI Settings, BLE Addresses, and Data Persistence
# =============================================================================
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
