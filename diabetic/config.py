import logging
import os
from pathlib import Path
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional, Dict, Literal
from diabetic import medical_constants

class Settings(BaseSettings):
    _ROOT_DIR = Path(__file__).resolve().parent.parent

# -----------------------------------------------------------------------------
# CORE SETTINGS: API & Alerting Credentials
# -----------------------------------------------------------------------------
    NIGHTSCOUT_URL: str = ""
    API_SECRET: str = Field("", validation_alias="NIGHTSCOUT_API_SECRET")
    OPENWEATHER_API_KEY: str = ""
    WEATHER_MOCK_MODE: bool = False
    
    # Alerting (Telegram)
    TELEGRAM_TOKEN: str = Field("", validation_alias="TELEGRAM_BOT_TOKEN")
    USER_ID: int = Field(0, validation_alias="TELEGRAM_CHAT_ID")
    CAREGIVER_ID: Optional[int] = None
    
# -----------------------------------------------------------------------------
# RUNTIME SETTINGS: Polling & Logging
# -----------------------------------------------------------------------------
    LOG_LEVEL: str = "INFO"
    BIO_ENVIRONMENT: Literal["production", "development", "test"] = "production"
    DATA_POLLING_INTERVAL: int = 150  # 2.5 minutes
    PREFER_MMOL: bool = True
    SAMPLING_INTERVAL_MINS: float = medical_constants.SAMPLING_INTERVAL_MINS
    
# -----------------------------------------------------------------------------
# PATIENT PROFILE: Physiological Baselines
# -----------------------------------------------------------------------------
    PATIENT_AGE: int = Field(30, ge=5, le=110, validation_alias="PATIENT_AGE")
    PATIENT_WEIGHT_KG: float = Field(
        45.0,
        ge=12,
        le=300,
        validation_alias="PATIENT_WEIGHT_KG",
    )
    PATIENT_HEIGHT_CM: float = Field(
        158.0,
        ge=60,
        le=250,
        validation_alias="PATIENT_HEIGHT_CM",
    )
    PATIENT_ETHNICITY: str = Field("UNKNOWN", validation_alias="PATIENT_ETHNICITY")
    PATIENT_NATIONALITY: str = Field("UNKNOWN", validation_alias="PATIENT_NATIONALITY")
    PATIENT_RELIGION: str = Field("NON_RELIGIOUS", validation_alias="PATIENT_RELIGION")
    PATIENT_GENDER: Literal["MALE", "FEMALE", "OTHER"] = Field(
        "FEMALE",
        validation_alias="PATIENT_GENDER",
    )
    PATIENT_DIABETES_TYPE: Literal[
        "T1D", "T2D", "LADA", "MODY", "PREDIABETES"
    ] = Field("T1D", validation_alias="PATIENT_DIABETES_TYPE")
    PATIENT_DIAGNOSIS_YEAR: int = Field(2020, validation_alias="PATIENT_DIAGNOSIS_YEAR")
    PATIENT_ACTIVITY_LEVEL: str = Field("MODERATE", validation_alias="PATIENT_ACTIVITY_LEVEL")
    
# -----------------------------------------------------------------------------
# REGIONAL SETTINGS: Timezone & Maintenance
# -----------------------------------------------------------------------------
    USER_TIMEZONE: str = Field("Asia/Ho_Chi_Minh", validation_alias="BIO_USER_TIMEZONE")
    MAINTENANCE_LOCAL_HOUR: int = Field(3, validation_alias="BIO_MAINTENANCE_HOUR")
    
    # Clinical Lab Results (Personalization 2.2) - MUST BE SET IN .ENV
    PATIENT_FRUCTOSAMIN: float = Field(300.0, validation_alias="PATIENT_FRUCTOSAMIN")
    PATIENT_MICROALBUMINURIA: bool = Field(False, validation_alias="PATIENT_MICROALBUMINURIA")
    PATIENT_INFLAMMATORY_MARKER: bool = Field(False, validation_alias="PATIENT_INFLAMMATORY_MARKER")
    PATIENT_CYCLE_START: str = Field("2026-01-01", validation_alias="PATIENT_CYCLE_START")#if gender=female
    
    PATIENT_GB_MMOL: float = 8.4
    PATIENT_HRV_BASELINE: float = 50.0
    PATIENT_BPM_BASELINE: float = 70.0  # Default 70bpm
    
    # Global Location (Weather Synchronization)
    LATITUDE: float  = medical_constants.DEFAULT_LATITUDE
    LONGITUDE: float = medical_constants.DEFAULT_LONGITUDE
    
# -----------------------------------------------------------------------------
# INFRASTRUCTURE: UI, Database & Hardware
# -----------------------------------------------------------------------------
    UI_SETTINGS: Dict[str, str] = {
        "EMERGENCY": "🚨 EMERGENCY",
        "HIGH": "⚠️ WARNING",
        "CRITICAL_HYPER": "🔺 CRITICAL HYPER",
        "FAINT_RISK": "💫 FAINT RISK",
        "STRESS_ANOMALY": "🫀 STRESS ANOMALY",  # Fix H4: distinct key for decoupling events
        "INFO": "ℹ️ INFO"
    }
    
    # Infrastructure
    MONGO_URI: str = ""
    MONGODB_URI: str = "" # Heroku Add-on standard
    HEART_RATE_SENSOR_ADDRESS: str = "MOCK" # Set to XX:XX... for BLE
    WEATHER_ENABLED: bool = True
    CARDIAC_ENABLED: bool = True
    
    # Local High-Availability (Task 8.1.1)
    LOCAL_DB_PATH: str = "storage/audit.db"
    BACKFILL_MAX_HOURS: int = 24
    RETENTION_DAYS: int = Field(
        180,
        ge=1,
        le=3650,
        validation_alias="BIO_RETENTION_DAYS",
    )
    HUD_STALE_AFTER_SECS: int = Field(900, validation_alias="BIO_HUD_STALE_AFTER_SECS")
    LOCAL_GUI_ENABLED: bool = True

    # TWA Web Auth (Telegram Mini App)
    TWA_ALLOWED_ORIGINS: list[str] = []           # CORS allow-list; empty = same-origin only
    TWA_DEV_TOKEN: str = ""                        # set to enable `Authorization: dev <token>` browser testing
    TWA_AUTH_MAX_AGE_SECS: int = 86400            # reject initData older than this (replay window)

    # ML Engine (Phase 3 Evolution)
    ML_WEIGHTS_VERSION: str = "v15"
    ML_WEIGHTS_PATH: str = str(Path(__file__).resolve().parent.parent / "diabetic/ml_engine/weights/diabetic_cnn_v15.pth")
    AUTO_TRAIN_ENABLED: bool = Field(False, validation_alias="BIO_AUTO_TRAIN_ENABLED")
    TRAIN_STALE_DAYS: int = Field(7, validation_alias="BIO_TRAIN_STALE_DAYS")
    
    # --- WAVE 5: UI & Network parameters ---
    LIVE_HISTORY_HOURS: float = 8.0
    BLE_RECONNECT_SECS: int = 30
    # Locate the .env file in the project root (one level up from diabetic/ folder)
    _BASE_DIR = Path(__file__).resolve().parent.parent
    _DOT_ENV = _BASE_DIR / ".env"

    model_config = SettingsConfigDict(
        env_file=str(_DOT_ENV) if _DOT_ENV.exists() else ".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    @field_validator("PATIENT_GENDER", "PATIENT_DIABETES_TYPE", mode="before")
    @classmethod
    def normalize_patient_enums(cls, value: object) -> object:
        return value.strip().upper() if isinstance(value, str) else value

    def validate_config(self):
        """
        Wave 1 Hardening: Verifies required metadata and connectivity secrets at boot.
        Prevents silent degraded operation in production.
        """
        # Phase 4.1 Hardening: Validate Timezone
        try:
            from zoneinfo import ZoneInfo
            ZoneInfo(self.USER_TIMEZONE)
        except Exception as e:
            raise ValueError(f"CRITICAL BOOT FAILURE: Invalid USER_TIMEZONE '{self.USER_TIMEZONE}': {e}")
            
        # Prioritize MONGODB_URI (Heroku Addons) over MONGO_URI (Local/Manual)
        active_mongo = self.MONGODB_URI or self.MONGO_URI
        
        critical_keys = {
            "NIGHTSCOUT_URL": self.NIGHTSCOUT_URL,
            "API_SECRET": self.API_SECRET,
            "TELEGRAM_TOKEN": self.TELEGRAM_TOKEN,
            "USER_ID": self.USER_ID,
            "MONGO_URI/MONGODB_URI": active_mongo,
            "ML_WEIGHTS_PATH": self.ML_WEIGHTS_PATH
        }
        
        missing = [k for k, v in critical_keys.items() if not v or v == "0"]
        if missing:
            raise ValueError(f"CRITICAL BOOT FAILURE: Missing required environment variables: {', '.join(missing)}")
            
        # Ensure writable storage
        os.makedirs("storage", exist_ok=True)
        os.makedirs("storage/exports", exist_ok=True)
        
        logging.getLogger("Bio-Quant.Config").info("Configuration validated: System ready.")

# Singleton instance
config = Settings()
