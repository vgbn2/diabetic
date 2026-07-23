"""Single-owner candidate validation and atomic model promotion."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import shutil
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from diabetic.config import config
from diabetic.ml_engine.train import TrainingResult, train_metabolic_cnn

logger = logging.getLogger("Bio-Quant.ML.TrainingService")
_PROCESS_LOCK = asyncio.Lock()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


@contextmanager
def _training_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another training process owns the lock") from exc
        try:
            yield
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def _restore_backup(backup: Path | None, deployed: Path) -> None:
    if backup is None or not backup.exists():
        return
    restore_tmp = deployed.with_suffix(deployed.suffix + ".restore")
    shutil.copy2(backup, restore_tmp)
    os.replace(restore_tmp, deployed)


async def run_training_pipeline(
    *,
    source: str = "mongo",
    epochs: int = 20,
) -> dict:
    """Train, validate, atomically promote, reload, and report one model."""

    deployed = Path(config.ML_WEIGHTS_PATH)
    state_dir = deployed.parent / ".training"
    candidate = state_dir / "candidate.pth"
    backup = state_dir / "last_known_good.pth"
    manifest_path = state_dir / "manifest.json"
    lock_path = state_dir / "training.lock"
    started = datetime.now(timezone.utc)

    async with _PROCESS_LOCK:
        try:
            with _training_file_lock(lock_path):
                candidate.unlink(missing_ok=True)
                result = await train_metabolic_cnn(
                    source=source,
                    epochs=epochs,
                    weight_version=config.ML_WEIGHTS_VERSION,
                    output_path=candidate,
                )
                if not isinstance(result, TrainingResult):
                    payload = {
                        "status": "rejected",
                        "started_at": started.isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "source": source,
                    }
                    _atomic_json(manifest_path, payload)
                    return payload

                candidate_hash = sha256_file(candidate)
                previous_backup: Path | None = None
                if deployed.exists():
                    backup_tmp = backup.with_suffix(".tmp")
                    backup.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(deployed, backup_tmp)
                    os.replace(backup_tmp, backup)
                    previous_backup = backup

                deployed.parent.mkdir(parents=True, exist_ok=True)
                os.replace(candidate, deployed)

                reload_ok = True
                coordinator = None
                try:
                    from diabetic.coordinator import Coordinator

                    coordinator = Coordinator._instance
                    if coordinator and coordinator.neural_runner:
                        reload_ok = coordinator.neural_runner.reload_weights(deployed)
                except Exception:
                    logger.exception("Model hot reload raised unexpectedly.")
                    reload_ok = False

                if not reload_ok:
                    if previous_backup is None:
                        deployed.unlink(missing_ok=True)
                    else:
                        _restore_backup(previous_backup, deployed)
                    if previous_backup is not None and coordinator is not None:
                        try:
                            coordinator.neural_runner.reload_weights(deployed)
                        except Exception:
                            logger.exception("Last-known-good reload also failed.")
                    raise RuntimeError("promoted model failed hot reload")

                payload = {
                    "status": "promoted",
                    "started_at": started.isoformat(),
                    "finished_at": datetime.now(timezone.utc).isoformat(),
                    "source": source,
                    "sample_count": result.sample_count,
                    "validation_loss": result.best_validation_loss,
                    "version": config.ML_WEIGHTS_VERSION,
                    "sha256": candidate_hash,
                }
                _atomic_json(manifest_path, payload)
                return payload
        except Exception as exc:
            candidate.unlink(missing_ok=True)
            payload = {
                "status": "failed",
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "error": exc.__class__.__name__,
            }
            _atomic_json(manifest_path, payload)
            logger.exception("Training pipeline failed.")
            return payload


def read_training_manifest() -> dict:
    manifest = Path(config.ML_WEIGHTS_PATH).parent / ".training" / "manifest.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "never_run"}
