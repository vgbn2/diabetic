import asyncio
import logging
import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from diabetic.config import config
from diabetic.ml_engine.train import train_metabolic_cnn

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
        try:
            tz = ZoneInfo(config.USER_TIMEZONE or "Asia/Ho_Chi_Minh")
        except Exception:
            tz = timezone.utc
            
        while self.is_running:
            try:
                now = datetime.now(tz)
                # Next 3:00 AM window
                target = now.replace(hour=3, minute=0, second=0, microsecond=0)
                if now >= target:
                    target += timedelta(days=1)
                
                wait_secs = (target - now).total_seconds()
                logger.info(f"[Scheduler] Next optimization window in {wait_secs/3600:.1f} hours.")
                
                await asyncio.sleep(wait_secs)
                
                # Window Open: Check if training is needed
                # Rule: Retrain if weights are > 7 days old
                staleness = datetime.now(timezone.utc) - self.last_training_time
                if staleness.days >= 7:
                    logger.warning(f"[Scheduler] Model is STALE ({staleness.days} days). Initiating autonomous retraining...")
                    try:
                        # 1. Train new weights
                        await train_metabolic_cnn(
                            source="mongo", 
                            epochs=20, 
                            weight_version=config.ML_WEIGHTS_VERSION
                        )
                        
                        # 2. Signal Coordinator to Hot-Reload
                        from diabetic.coordinator import Coordinator
                        from pathlib import Path
                        coord = Coordinator._instance
                        if coord and coord.neural_runner:
                            coord.neural_runner.reload_weights(Path(config.ML_WEIGHTS_PATH))
                        
                        self.last_training_time = datetime.now(timezone.utc)
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
