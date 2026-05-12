from fastapi import FastAPI, Request, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import logging
import os
from datetime import datetime, timezone

from diabetic.config import config
from diabetic.registry import MetabolicSnapshot

# --- [SKILL-LIKE LOGIC: DATA INTERFACE] ---
# This bridge follows the 'Passive Sentinel to Active HUD' transformation.
# It exposes the internal Coordinator state to the Telegram Web App (TWA).

app = FastAPI(title="Bio-Quant TWA Bridge")

# Enable CORS for TWA hosting (usually on GitHub Pages or Cloud Run)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict to your TWA domain
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- [STATIC HUD SERVING] ---
# In production, this allows Heroku to serve the 'Face' of the app.
TWA_DIR = os.path.join(os.getcwd(), "twa")
if os.path.exists(TWA_DIR):
    app.mount("/assets", StaticFiles(directory=os.path.join(TWA_DIR, "assets")), name="assets")

@app.get("/")
async def serve_hud():
    """Serves the main Glassmorphism HUD."""
    index_path = os.path.join(TWA_DIR, "index.html")
    if os.path.exists(index_path):
        return FileResponse(index_path)
    return {"error": "HUD Assets Not Found"}

class HUDState(BaseModel):
    glucose: float
    velocity: float
    trend: str
    active_carbs: float
    active_insulin: float
    confidence: float
    last_update: str

# Shared state reference (will be injected by the Coordinator)
COORDINATOR_REF = None

@app.get("/api/v1/hud")
async def get_hud_data():
    """Returns the real-time metabolic frame for the glassmorphism HUD."""
    if not COORDINATOR_REF or not COORDINATOR_REF.snapshots:
        return HUDState(
            glucose=0.0,
            velocity=0.0,
            trend="FLAT",
            active_carbs=0.0,
            active_insulin=0.0,
            confidence=0.0,
            last_update="Waiting for Engine..."
        )
    
    latest: MetabolicSnapshot = COORDINATOR_REF.snapshots[-1]
    
    return HUDState(
        glucose=latest.filtered_value,
        velocity=latest.velocity,
        trend=latest.trend_label,
        active_carbs=latest.active_carbs,
        active_insulin=latest.active_insulin,
        confidence=latest.confidence_index,
        last_update=latest.timestamp.strftime("%H:%M:%S")
    )

@app.get("/api/v1/forecast")
async def get_forecast():
    """Returns the 4h trajectory for the 'Metabolic Horizon' chart."""
    if not COORDINATOR_REF:
        return {"error": "Engine Offline"}
    
    # Logic: Pull from the latest Digital Twin projection
    # Placeholder for actual trajectory array
    history_pts = int(150 / config.SAMPLING_INTERVAL_MINS)
    return {
        "points": [s.filtered_value for s in COORDINATOR_REF.snapshots[-history_pts:]],
        "horizon": getattr(COORDINATOR_REF, 'last_prediction_4h', [])
    }

@app.post("/api/v1/calibration")
async def update_calibration(traits: dict):
    """Allows the user to update Bio-Traits (Weight, Age, Sensitivity) via GUI."""
    if not COORDINATOR_REF:
         raise HTTPException(status_code=503, detail="Engine Offline")
    
    # Logic: Update VesselRegistry and re-sync Twin
    success = await COORDINATOR_REF.vessel_registry.update_user_traits(config.USER_ID, traits)
    if success:
        return {"status": "success", "message": "Bio-Traits Recalibrated"}
    return {"status": "error", "message": "Database Lock"}

def start_api(coordinator_instance):
    """Helper to launch the API in a background thread or separate process."""
    global COORDINATOR_REF
    COORDINATOR_REF = coordinator_instance
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["access"]["fmt"] = "%(asctime)s - TWA_BRIDGE - %(message)s"
    
    # In production, this would run on config.API_PORT
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")

if __name__ == "__main__":
    # Test launch
    print("🚀 Bio-Quant TWA Bridge Interface Loaded.")
    uvicorn.run(app, host="127.0.0.1", port=8000)
