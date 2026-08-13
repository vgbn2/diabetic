from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import logging
import os
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal, Optional

from diabetic.config import config
from diabetic.registry import MetabolicSnapshot
from diabetic.auth.dependencies import require_twa_user
from diabetic.ui.glucose_display import (
    decimal_places,
    glucose_series,
    glucose_value,
    glucose_velocity,
    hud_haptic_warning,
    hud_range,
    unit_label,
)

# --- [SKILL-LIKE LOGIC: DATA INTERFACE] ---
# This bridge follows the 'Passive Sentinel to Active HUD' transformation.
# It exposes the internal Coordinator state to the Telegram Web App (TWA).

logger = logging.getLogger("Bio-Quant.TWA")
app = FastAPI(title="Bio-Quant TWA Bridge")

# Enable CORS for TWA hosting (usually on GitHub Pages or Cloud Run)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.TWA_ALLOWED_ORIGINS,  # empty = same-origin only; set for cross-origin hosting
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [STATIC HUD SERVING] ---
# In production, this allows Heroku to serve the 'Face' of the app.
# Resolved from project root (not CWD) so non-Docker / non-root launches still
# find the static pages — mirrors config.py's absolute ML-weight pathing.
TWA_DIR = str(Path(__file__).resolve().parents[2] / "twa")
_ASSETS_DIR = os.path.join(TWA_DIR, "assets")
# Guard on the assets subdir: StaticFiles raises at construction if it is missing.
if os.path.isdir(_ASSETS_DIR):
    app.mount("/assets", StaticFiles(directory=_ASSETS_DIR), name="assets")


def _serve_page(name: str):
    path = os.path.join(TWA_DIR, name)
    if os.path.exists(path):
        return FileResponse(path)
    return {"error": f"{name} not found"}


@app.get("/")
async def serve_hud():
    """Serves the main Glassmorphism HUD (dashboard)."""
    return _serve_page("index.html")


@app.get("/login")
async def serve_login():
    """Auth gate shown when opened outside Telegram or unauthorized."""
    return _serve_page("login.html")


@app.get("/settings")
async def serve_settings():
    """Bio-traits editor page."""
    return _serve_page("settings.html")


@app.get("/history")
async def serve_history():
    """Recent-glucose history page."""
    return _serve_page("history.html")

class HUDState(BaseModel):
    state: Literal["waiting", "live", "stale", "degraded"]
    ready: bool
    fresh: bool
    glucose: Optional[float]
    velocity: Optional[float]
    trend: str
    active_carbs: float
    active_insulin: float
    confidence: float
    unit: str
    decimal_places: int
    range_state: Optional[Literal["low", "in_range", "high"]]
    haptic_warning: bool
    timestamp: Optional[str]
    age_seconds: Optional[float]
    degraded_reasons: list[str]

# Shared state reference (injected by the one live Coordinator process).
COORDINATOR_REF = None


def clear_api_coordinator(coordinator_instance) -> bool:
    """Remove the projection only when the caller still owns it."""
    global COORDINATOR_REF
    if COORDINATOR_REF is not coordinator_instance:
        return False
    COORDINATOR_REF = None
    return True

@app.get("/api/v1/hud", dependencies=[Depends(require_twa_user)])
async def get_hud_data():
    """Returns the real-time metabolic frame for the glassmorphism HUD."""
    if not COORDINATOR_REF or not COORDINATOR_REF.snapshots:
        return HUDState(
            state="waiting",
            ready=False,
            fresh=False,
            glucose=None,
            velocity=None,
            trend="FLAT",
            active_carbs=0.0,
            active_insulin=0.0,
            confidence=0.0,
            unit=unit_label(),
            decimal_places=decimal_places(),
            range_state=None,
            haptic_warning=False,
            timestamp=None,
            age_seconds=None,
            degraded_reasons=["no_metabolic_snapshot"],
        )
    
    latest: MetabolicSnapshot = COORDINATOR_REF.snapshots[-1]
    timestamp = latest.glucose.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())
    fresh = age <= config.HUD_STALE_AFTER_SECS
    treatment_degraded = (
        getattr(COORDINATOR_REF, "treatment_fetch_state", "waiting") == "degraded"
    )
    degraded_reasons = []
    if not fresh:
        degraded_reasons.append("stale_metabolic_snapshot")
    if treatment_degraded:
        degraded_reasons.append("treatment_provider_degraded")
    
    return HUDState(
        state="degraded" if fresh and treatment_degraded else ("live" if fresh else "stale"),
        ready=fresh and not treatment_degraded,
        fresh=fresh,
        glucose=glucose_value(latest.filtered_value),
        velocity=glucose_velocity(latest.velocity),
        trend=latest.glucose.trend,
        active_carbs=latest.active_carbs,
        active_insulin=latest.active_insulin,
        confidence=latest.confidence_index,
        unit=unit_label(),
        decimal_places=decimal_places(),
        range_state=hud_range(latest.filtered_value),
        haptic_warning=hud_haptic_warning(latest.filtered_value),
        timestamp=timestamp.isoformat(),
        age_seconds=round(age, 1),
        degraded_reasons=degraded_reasons,
    )

@app.get("/api/v1/forecast", dependencies=[Depends(require_twa_user)])
async def get_forecast():
    """Returns the 4h trajectory for the 'Metabolic Horizon' chart."""
    if not COORDINATOR_REF or not COORDINATOR_REF.snapshots:
        return {
            "state": "waiting",
            "points": [],
            "horizon": [],
            "horizon_1d": [],
            "unit": unit_label(),
            "decimal_places": decimal_places(),
        }
    
    history_pts = int(150 / config.SAMPLING_INTERVAL_MINS)
    timestamp = COORDINATOR_REF.snapshots[-1].glucose.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    fresh = (
        datetime.now(timezone.utc) - timestamp
    ).total_seconds() <= config.HUD_STALE_AFTER_SECS
    return {
        "state": "live" if fresh else "stale",
        "timestamp": timestamp.isoformat(),
        "points": glucose_series(
            s.filtered_value for s in COORDINATOR_REF.snapshots[-history_pts:]
        ),
        "horizon": glucose_series(
            getattr(COORDINATOR_REF, "last_prediction_4h", [])
        ),
        "horizon_1d": glucose_series(
            getattr(COORDINATOR_REF, "last_prediction_1d", [])
        ),
        "unit": unit_label(),
        "decimal_places": decimal_places(),
        "resolution_mins": config.SAMPLING_INTERVAL_MINS,
    }


@app.get("/healthz")
async def healthz():
    """Liveness only: the HTTP process can answer."""
    return {"status": "ok"}


@app.get("/readyz")
async def readyz():
    """Detail-free core-monitoring readiness gate."""
    from diabetic.utils.health import get_system_health

    health = await get_system_health()
    if not health["ready"]:
        raise HTTPException(status_code=503, detail="not ready")
    return {"status": "ready"}

@app.post("/api/v1/calibration", dependencies=[Depends(require_twa_user)])
async def update_calibration(traits: dict):
    """Persist allowed profile traits without changing active runtime state."""
    if not COORDINATOR_REF:
         raise HTTPException(status_code=503, detail="Engine Offline")

    success = await COORDINATOR_REF.vessel_registry.update_user_traits(
        config.USER_ID, traits
    )
    if success:
        return {
            "status": "success",
            "stored": True,
            "applied_to_runtime": False,
            "message": "Bio-traits saved. Active forecasts are unchanged.",
        }
    return {
        "status": "error",
        "stored": False,
        "applied_to_runtime": False,
        "message": "Profile not found or no valid fields",
    }

def start_api(coordinator_instance):
    """Helper to launch the API in a background thread or separate process."""
    global COORDINATOR_REF
    COORDINATOR_REF = coordinator_instance
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = "%(asctime)s - TWA_BRIDGE - %(message)s"
    
    # Binds 0.0.0.0:8000 (matches the docker-compose bio-quant-twa service).
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    # Test launch
    logger.info("Bio-Quant TWA Bridge Interface Loaded.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
