import os
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

class Settings(BaseSettings):
    # Core Medical APIs
    NIGHTSCOUT_URL: str = ""
    API_SECRET: str = ""
    
    # Alerting (Telegram)
    TELEGRAM_TOKEN: str = ""
    USER_ID: int = 0
    CAREGIVER_ID: Optional[int] = None
    
    # System Config
    LOG_LEVEL: str = "INFO"
    DATA_POLLING_INTERVAL: int = 300  # 5 minutes
    SAMPLING_INTERVAL_MINS: float = 5.0
    
    # Medical Units
    PREFER_MMOL: bool = True  # We saw mmol/L in Ottai reports
    
    # Patient Baselines (Medical Logic 1.1)
    PATIENT_GB_MMOL: float = 8.4
    PATIENT_HRV_BASELINE: Optional[float] = None  # None triggers warning on boot
    
    # Infrastructure
    MONGO_URI: str = ""
    RENDER_EXTERNAL_URL: str = ""
    
    FRONTEND_PUSH_URL: str = "http://localhost:10000/api/push"
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

# Singleton instance
config = Settings()
