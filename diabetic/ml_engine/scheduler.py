import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from diabetic.config import config
from diabetic.ml_engine.training_service import run_training_pipeline

logger = logging.getLogger("Bio-Quant.Scheduler")

class MetabolicScheduler:
    """
    Automated background training loop (Phase 3).
    Ensures model stays personalized and accurate without human intervention.
    """
    def __init__(self):
        self.is_running = False
        self.last_training_time = self._get_last_training_time()

    def _get_last_training_time(self) -> datetime:
        """Checks the modification time of the current weights file."""
        weights_path = config.ML_WEIGHTS_PATH
        if os.path.exists(weights_path):
            try:
                mtime = os.path.getmtime(weights_path)
                return datetime.fromtimestamp(mtime, tz=timezone.utc)
            except Exception:
                pass
        return datetime.min.replace(tzinfo=timezone.utc)

    async def run_forever(self):
        """Main scheduler loop."""
        self.is_running = True
        logger.info("[Scheduler] Automated Metabolic Training Scheduler initialized.")
        
        # Regional timezone for 3 AM scheduling
        tz = ZoneInfo(config.USER_TIMEZONE)
            
        while self.is_running:
            try:
                now = datetime.now(tz)
                # Next 3:00 AM window
                target = now.replace(hour=config.MAINTENANCE_LOCAL_HOUR, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                
                wait_secs = (target - now).total_seconds()
                logger.info(f"[Scheduler] Next optimization window in {wait_secs/3600:.1f} hours.")
                
                await asyncio.sleep(wait_secs)
                
                # Window Open: Check if training is needed
                # Recompute from disk every window so manual promotions are seen.
                self.last_training_time = self._get_last_training_time()
                staleness = datetime.now(timezone.utc) - self.last_training_time
                if staleness.days >= config.TRAIN_STALE_DAYS:
                    logger.warning(f"[Scheduler] Model is STALE ({staleness.days} days). Initiating autonomous retraining...")
                    try:
                        result = await run_training_pipeline(source="mongo", epochs=20)
                        if result["status"] != "promoted":
                            logger.error(
                                "[Scheduler] Training ended with status %s.",
                                result["status"],
                            )
                            continue
                        self.last_training_time = self._get_last_training_time()
                        logger.info("[Scheduler] Autonomous training and hot-reload complete.")
                    except Exception as te:
                        logger.error(f"[Scheduler] Training failed: {te}")
                else:
                    logger.info(f"[Scheduler] Model is fresh ({staleness.days} days old). Skipping window.")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"[Scheduler] Critical failure in background loop: {e}")
                await asyncio.sleep(600) # Cool down before retry
