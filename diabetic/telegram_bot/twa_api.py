from fastapi import FastAPI, Request, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import logging
import os
import hashlib
import hmac
from pathlib import Path
from datetime import datetime, timezone
from typing import Literal, Optional

from diabetic.config import config
from diabetic.registry import MetabolicSnapshot, GlucoseReading
from diabetic.auth.dependencies import require_twa_user
from diabetic.storage.vessel_registry import VesselRegistry
from diabetic.utils.ip_resolver import normalize_ip

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
    timestamp: Optional[str]
    age_seconds: Optional[float]
    degraded_reasons: list[str]

# Shared state reference (will be injected by the Coordinator)
COORDINATOR_REF = None

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
        glucose=latest.filtered_value,
        velocity=latest.velocity,
        trend=latest.glucose.trend,
        active_carbs=latest.active_carbs,
        active_insulin=latest.active_insulin,
        confidence=latest.confidence_index,
        timestamp=timestamp.isoformat(),
        age_seconds=round(age, 1),
        degraded_reasons=degraded_reasons,
    )

@app.get("/api/v1/forecast", dependencies=[Depends(require_twa_user)])
async def get_forecast():
    """Returns the 4h trajectory for the 'Metabolic Horizon' chart."""
    if not COORDINATOR_REF or not COORDINATOR_REF.snapshots:
        return {"state": "waiting", "points": [], "horizon": [], "horizon_1d": []}
    
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
        "points": [s.filtered_value for s in COORDINATOR_REF.snapshots[-history_pts:]],
        "horizon": getattr(COORDINATOR_REF, "last_prediction_4h", []),
        "horizon_1d": getattr(COORDINATOR_REF, "last_prediction_1d", []),
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


# -----------------------------------------------------------------------------
# 🌐 [MULTI-TENANT INGRESS GATEWAY & DISPATCHER]
# -----------------------------------------------------------------------------
_registry: Optional[VesselRegistry] = None

def _get_registry() -> VesselRegistry:
    global _registry
    if _registry is None:
        _registry = VesselRegistry()
    return _registry


async def _resolve_tenant_id(request: Request, slug: Optional[str] = None) -> str:
    """
    Resolves tenant_id in priority order:
    1. Path custom_slug (/t/{slug}/...)
    2. Header 'x-tenant-id'
    3. Dual-stack client IP lookup in DeviceBindings (IPv4, Tailscale, IPv6)
    4. Default fallback ('default')
    """
    if slug:
        return slug.strip().lower()

    hdr_tenant = request.headers.get("x-tenant-id")
    if hdr_tenant:
        return hdr_tenant.strip().lower()

    # Client IP match (check X-Forwarded-For, X-Real-IP, then socket host)
    client_host = None
    xff = request.headers.get("x-forwarded-for")
    if xff:
        client_host = xff.split(",")[0].strip()
    elif request.headers.get("x-real-ip"):
        client_host = request.headers.get("x-real-ip").strip()
    elif request.client:
        client_host = request.client.host

    if client_host:
        try:
            reg = _get_registry()
            user = await reg.resolve_tenant_by_ip(client_host)
            if user:
                return f"user_{user.telegram_id}"
        except Exception as e:
            logger.debug("Client IP resolution error: %s", e)

    return "default"


async def _validate_ingress_auth(request: Request, slug: Optional[str] = None) -> None:
    """
    Validates Nightscout-compatible API secret from query parameters or headers.
    Supports system-wide API_SECRET and per-device/tenant specific secret hashes.
    Accepts raw secret, SHA-1 hash, or 'api-secret: <hash>' / 'api-secret: <raw>' header.
    """
    configured_secret = (config.API_SECRET or "").strip()

    allowed_hashes = set()
    allowed_raws = set()

    if configured_secret:
        allowed_raws.add(configured_secret)
        allowed_hashes.add(hashlib.sha1(configured_secret.encode("utf-8")).hexdigest())

    # Check for per-device specific secret in VesselRegistry
    if slug:
        try:
            reg = _get_registry()
            binding = await reg.resolve_device_binding_by_slug(slug)
            if binding and binding.api_secret_hash:
                allowed_hashes.add(binding.api_secret_hash.strip().lower())
        except Exception as e:
            logger.debug("Failed checking tenant-specific secret: %s", e)

    if not allowed_raws and not allowed_hashes:
        return  # Ingress open if no secrets configured

    def check_candidate(candidate: str) -> bool:
        c = candidate.strip()
        c_lower = c.lower()
        if any(hmac.compare_digest(c, r) for r in allowed_raws):
            return True
        if any(hmac.compare_digest(c_lower, h) for h in allowed_hashes):
            return True
        c_sha1 = hashlib.sha1(c.encode("utf-8")).hexdigest()
        if any(hmac.compare_digest(c_sha1, h) for h in allowed_hashes):
            return True
        return False

    # 1. Query parameter secret=... or token=...
    q_secret = request.query_params.get("secret") or request.query_params.get("token") or request.query_params.get("api-secret")
    if q_secret and check_candidate(q_secret):
        return

    # 2. Header api-secret or Authorization
    hdr_secret = request.headers.get("api-secret")
    if hdr_secret and check_candidate(hdr_secret):
        return

    auth_hdr = request.headers.get("authorization", "")
    if auth_hdr.lower().startswith("bearer "):
        bearer_val = auth_hdr[7:]
        if check_candidate(bearer_val):
            return

    logger.warning("[Ingress] Unauthorized CGM push attempt rejected.")
    raise HTTPException(status_code=401, detail="Unauthorized: invalid api-secret or token")


@app.post("/api/v1/entries")
@app.post("/t/{slug}/api/v1/entries")
@app.get("/api/v1/entries")
@app.get("/t/{slug}/api/v1/entries")
async def ingest_cgm_entries(
    request: Request,
    slug: Optional[str] = None,
):
    """
    Nightscout-compatible CGM ingestion and query endpoint.
    Accepts POST telemetry from xDrip+, Ottai, Nightscout Uploader, and synthetic streams.
    Accepts GET requests from web browsers/uploaders to inspect recent readings.
    """
    await _validate_ingress_auth(request, slug=slug)

    tenant_id = await _resolve_tenant_id(request, slug=slug)

    # If accessed via GET (browser or uploader checking connection)
    if request.method == "GET":
        pipeline = COORDINATOR_REF.get_pipeline(tenant_id) if COORDINATOR_REF else None
        if not pipeline or not pipeline.snapshots:
            return []

        # Return recent readings in standard Nightscout format
        results = []
        for s in list(pipeline.snapshots)[-10:]:
            ts = s.glucose.timestamp
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            results.append({
                "sgv": round(s.filtered_value * 18.0182, 0),
                "date": int(ts.timestamp() * 1000),
                "dateString": ts.isoformat(),
                "trend": s.glucose.trend,
                "direction": s.glucose.trend,
                "type": "sgv",
            })
        return results[::-1]

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    entries_list = body if isinstance(body, list) else [body]
    if not entries_list:
        return {"status": "ok", "inserted": 0}

    ingested_count = 0
    for entry in entries_list:
        try:
            # Parse Nightscout fields (sgv, dateString/date, direction)
            sgv_raw = entry.get("sgv") or entry.get("mbg") or entry.get("glucose")
            if sgv_raw is None:
                continue

            # Standardize mg/dL to mmol/L if raw sgv > 35
            val = float(sgv_raw)
            if val > 35.0:
                val = round(val / 18.0182, 2)

            ts_raw = entry.get("dateString") or entry.get("sysTime")
            if ts_raw:
                try:
                    ts = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00"))
                except ValueError:
                    ts = datetime.now(timezone.utc)
            elif "date" in entry:
                try:
                    ts = datetime.fromtimestamp(float(entry["date"]) / 1000.0, tz=timezone.utc)
                except Exception:
                    ts = datetime.now(timezone.utc)
            else:
                ts = datetime.now(timezone.utc)

            trend = str(entry.get("direction") or entry.get("trend") or "Flat")

            reading = GlucoseReading(
                timestamp=ts,
                value=val,
                trend=trend,
                source="ingress_gateway",
            )

            if COORDINATOR_REF:
                await COORDINATOR_REF._process_reading(reading, tenant_id=tenant_id)
                ingested_count += 1
        except Exception as e:
            logger.warning("[Ingress] Failed parsing reading for tenant %s: %s", tenant_id, e)

    return {"status": "ok", "tenant": tenant_id, "inserted": ingested_count}


@app.get("/t/{slug}/api/v1/hud")
async def get_tenant_hud_data(request: Request, slug: str):
    """Returns isolated HUD state for a specific tenant slug."""
    if not COORDINATOR_REF:
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
            timestamp=None,
            age_seconds=None,
            degraded_reasons=["coordinator_not_initialized"],
        )

    pipeline = COORDINATOR_REF.get_pipeline(slug)
    if not pipeline.snapshots:
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
            timestamp=None,
            age_seconds=None,
            degraded_reasons=["no_metabolic_snapshot"],
        )

    latest: MetabolicSnapshot = pipeline.snapshots[-1]
    timestamp = latest.glucose.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    age = max(0.0, (datetime.now(timezone.utc) - timestamp).total_seconds())
    fresh = age <= config.HUD_STALE_AFTER_SECS

    return HUDState(
        state="live" if fresh else "stale",
        ready=fresh,
        fresh=fresh,
        glucose=latest.filtered_value,
        velocity=latest.velocity,
        trend=latest.glucose.trend,
        active_carbs=latest.active_carbs,
        active_insulin=latest.active_insulin,
        confidence=latest.confidence_index,
        timestamp=timestamp.isoformat(),
        age_seconds=round(age, 1),
        degraded_reasons=[] if fresh else ["stale_metabolic_snapshot"],
    )


@app.get("/t/{slug}/api/v1/forecast")
async def get_tenant_forecast(request: Request, slug: str):
    """Returns the 4h trajectory for a specific tenant slug."""
    if not COORDINATOR_REF:
        return {"state": "waiting", "points": [], "horizon": [], "horizon_1d": []}

    pipeline = COORDINATOR_REF.get_pipeline(slug)
    if not pipeline.snapshots:
        return {"state": "waiting", "points": [], "horizon": [], "horizon_1d": []}

    history_pts = int(150 / config.SAMPLING_INTERVAL_MINS)
    timestamp = pipeline.snapshots[-1].glucose.timestamp
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    fresh = (
        datetime.now(timezone.utc) - timestamp
    ).total_seconds() <= config.HUD_STALE_AFTER_SECS
    return {
        "state": "live" if fresh else "stale",
        "tenant": slug,
        "timestamp": timestamp.isoformat(),
        "points": [s.filtered_value for s in pipeline.snapshots[-history_pts:]],
        "horizon": getattr(pipeline, "last_prediction_4h", []),
        "horizon_1d": getattr(pipeline, "last_prediction_1d", []),
        "resolution_mins": config.SAMPLING_INTERVAL_MINS,
    }


@app.get("/api/v1/client/summary")
@app.get("/t/{slug}/api/v1/client/summary")
async def get_client_summary(request: Request, slug: Optional[str] = None):
    """
    Consolidated client-side endpoint for web, mobile apps, and TWA clients.
    Provides instant HUD, forecast, and biometric metadata in a single round-trip.
    """
    tenant_id = await _resolve_tenant_id(request, slug=slug)

    # Resolve user details if available
    user_name = "Default Patient"
    telegram_id = None
    try:
        reg = _get_registry()
        if slug:
            user = await reg.resolve_tenant_by_slug(slug)
            if user:
                user_name = user.name
                telegram_id = user.telegram_id
        elif tenant_id.startswith("user_"):
            tid = int(tenant_id.replace("user_", ""))
            user = await reg.get_user(tid)
            if user:
                user_name = user.name
                telegram_id = user.telegram_id
    except Exception as e:
        logger.debug("Failed getting user metadata for summary: %s", e)

    hud_data = await (get_tenant_hud_data(request, slug=tenant_id) if tenant_id != "default" else get_hud_data())

    return {
        "tenant_id": tenant_id,
        "patient_name": user_name,
        "telegram_id": telegram_id,
        "hud": hud_data,
        "server_time": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/api/v1/client/cgm_config")
@app.get("/t/{slug}/api/v1/client/cgm_config")
async def get_cgm_config(request: Request, slug: Optional[str] = None):
    """
    Returns copy-pasteable CGM uploader parameters (URL, API secret hash, direct webhook)
    for mobile apps (xDrip+, Ottai, Nightscout).
    """
    import hashlib
    tenant_id = await _resolve_tenant_id(request, slug=slug)
    user_slug = slug or (tenant_id if not tenant_id.startswith("user_") else "default")

    raw_secret = config.API_SECRET or "bioquant123"
    sha1_secret = hashlib.sha1(raw_secret.encode("utf-8")).hexdigest()
    base_host = "https://hpdesk-1.tail285cce.ts.net"

    return {
        "nightscout_url": base_host,
        "api_secret": raw_secret,
        "api_secret_sha1": sha1_secret,
        "direct_upload_url": f"{base_host}/t/{user_slug}/api/v1/entries?secret={sha1_secret}",
        "tenant_slug": user_slug,
    }


@app.post("/api/v1/calibration", dependencies=[Depends(require_twa_user)])
async def update_calibration(traits: dict):
    """Allows the user to update Bio-Traits (Weight, Age, Sensitivity) via GUI."""
    if not COORDINATOR_REF:
         raise HTTPException(status_code=503, detail="Engine Offline")
    
    # Logic: Update VesselRegistry and re-sync Twin
    success = await COORDINATOR_REF.vessel_registry.update_user_traits(config.USER_ID, traits)
    if success:
        return {"status": "success", "message": "Bio-Traits Recalibrated"}
    return {"status": "error", "message": "Profile not found or no valid fields"}

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
