"""Single-owner candidate validation and recoverable model promotion."""

from __future__ import annotations

import asyncio
import fcntl
import hashlib
import json
import logging
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

from diabetic.config import config
from diabetic.ml_engine.train import TrainingResult, train_metabolic_cnn

logger = logging.getLogger("Bio-Quant.ML.TrainingService")
_PROCESS_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class PromotionPaths:
    deployed: Path
    state_dir: Path
    candidate: Path
    backup: Path
    manifest: Path
    manifest_backup: Path
    journal: Path
    attempt: Path
    lock: Path

    @classmethod
    def for_deployed(cls, deployed: Path) -> "PromotionPaths":
        state_dir = deployed.parent / ".training"
        return cls(
            deployed=deployed,
            state_dir=state_dir,
            candidate=state_dir / "candidate.pth",
            backup=state_dir / "last_known_good.pth",
            manifest=state_dir / "manifest.json",
            manifest_backup=state_dir / "last_known_good_manifest.json",
            journal=state_dir / "promotion.json",
            attempt=state_dir / "last_attempt.json",
            lock=state_dir / "training.lock",
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_file(path: Path) -> None:
    with path.open("rb") as stream:
        os.fsync(stream.fileno())


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _durable_unlink(path: Path) -> None:
    if path.exists():
        path.unlink()
        _fsync_directory(path.parent)


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)
    _fsync_directory(path.parent)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    shutil.copy2(source, temporary)
    _fsync_file(temporary)
    os.replace(temporary, destination)
    _fsync_directory(destination.parent)


def _durable_replace(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    _fsync_file(source)
    os.replace(source, destination)
    _fsync_directory(destination.parent)


def _read_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path.name} must contain an object")
    return value


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


def _current_runner():
    try:
        from diabetic.coordinator import Coordinator

        coordinator = Coordinator._instance
        return getattr(coordinator, "neural_runner", None) if coordinator else None
    except Exception:
        return None


def _activate_runner(runner, deployed: Path) -> bool:
    if runner is None:
        return True
    if not deployed.exists():
        runner.weights_loaded = False
        return True
    try:
        return bool(runner.reload_weights(deployed))
    except Exception:
        logger.exception("Model activation raised unexpectedly.")
        return False


def _manifest_matches(path: Path, artifact_hash: str) -> bool:
    try:
        manifest = _read_json(path)
    except (OSError, ValueError, json.JSONDecodeError):
        return False
    return (
        manifest.get("status") == "promoted"
        and manifest.get("sha256") == artifact_hash
    )


def _cleanup_transaction(paths: PromotionPaths) -> None:
    for path in (paths.manifest_backup, paths.candidate):
        _durable_unlink(path)
    for path in paths.state_dir.glob("*.tmp"):
        _durable_unlink(path)
    _durable_unlink(paths.journal)


def _restore_previous(paths: PromotionPaths, journal: dict) -> None:
    previous_exists = bool(journal["previous_exists"])
    previous_hash = journal.get("previous_sha256")
    if previous_exists:
        if not paths.backup.exists() or sha256_file(paths.backup) != previous_hash:
            raise RuntimeError("last-known-good artifact is unavailable or invalid")
        _atomic_copy(paths.backup, paths.deployed)
    else:
        _durable_unlink(paths.deployed)

    if journal.get("previous_manifest_exists"):
        if not paths.manifest_backup.exists():
            raise RuntimeError("last-known-good manifest is unavailable")
        _atomic_copy(paths.manifest_backup, paths.manifest)
    else:
        _durable_unlink(paths.manifest)


def _recover_transaction(paths: PromotionPaths) -> str:
    """Recover one authoritative disk version from an interrupted promotion."""
    if not paths.journal.exists():
        _durable_unlink(paths.candidate)
        for path in paths.state_dir.glob("*.tmp"):
            _durable_unlink(path)
        return "clean"

    journal = _read_json(paths.journal)
    required = {"candidate_sha256", "previous_exists", "previous_manifest_exists"}
    if not required.issubset(journal):
        raise RuntimeError("promotion journal is incomplete")

    candidate_hash = str(journal["candidate_sha256"])
    deployed_hash = sha256_file(paths.deployed) if paths.deployed.exists() else None
    if (
        journal.get("state") == "committed"
        and deployed_hash == candidate_hash
        and _manifest_matches(paths.manifest, candidate_hash)
    ):
        _cleanup_transaction(paths)
        return "committed"

    _restore_previous(paths, journal)
    _cleanup_transaction(paths)
    return "rolled_back"


def recover_training_state(deployed_path: Optional[Path] = None) -> str:
    """Recover an interrupted transaction before loading weights at process start."""
    paths = PromotionPaths.for_deployed(
        Path(deployed_path or config.ML_WEIGHTS_PATH)
    )
    if (
        not paths.journal.exists()
        and not paths.candidate.exists()
        and not any(paths.state_dir.glob("*.tmp"))
    ):
        return "clean"
    with _training_file_lock(paths.lock):
        return _recover_transaction(paths)


def _prepare_transaction(
    paths: PromotionPaths,
    *,
    candidate_hash: str,
    promotion_manifest: dict,
) -> None:
    previous_exists = paths.deployed.exists()
    previous_hash = sha256_file(paths.deployed) if previous_exists else None
    if previous_exists:
        _atomic_copy(paths.deployed, paths.backup)
    else:
        _durable_unlink(paths.backup)

    previous_manifest_exists = paths.manifest.exists()
    if previous_manifest_exists:
        _atomic_copy(paths.manifest, paths.manifest_backup)
    else:
        _durable_unlink(paths.manifest_backup)

    _atomic_json(
        paths.journal,
        {
            "state": "prepared",
            "candidate_sha256": candidate_hash,
            "previous_exists": previous_exists,
            "previous_sha256": previous_hash,
            "previous_manifest_exists": previous_manifest_exists,
            "promotion_manifest": promotion_manifest,
        },
    )


def _promote_candidate(paths: PromotionPaths) -> None:
    _durable_replace(paths.candidate, paths.deployed)


def _publish_manifest(paths: PromotionPaths, payload: dict) -> None:
    _atomic_json(paths.manifest, payload)
    journal = _read_json(paths.journal)
    journal["state"] = "committed"
    _atomic_json(paths.journal, journal)


def _write_attempt_best_effort(paths: PromotionPaths, payload: dict) -> None:
    try:
        _atomic_json(paths.attempt, payload)
    except Exception:
        logger.exception("Could not persist the non-authoritative training attempt.")


def _failure_payload(started: datetime, source: str, error: Exception) -> dict:
    return {
        "status": "failed",
        "started_at": started.isoformat(),
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        "error": error.__class__.__name__,
    }


def _recover_failed_promotion(
    paths: PromotionPaths,
    *,
    runner,
    started: datetime,
    source: str,
    error: Exception,
    force_rollback: bool,
) -> dict:
    recovered = None
    recovery_error = None
    try:
        if paths.journal.exists():
            if force_rollback:
                journal = _read_json(paths.journal)
                _restore_previous(paths, journal)
                _cleanup_transaction(paths)
                recovered = "rolled_back"
            else:
                recovered = _recover_transaction(paths)
            if not _activate_runner(runner, paths.deployed):
                raise RuntimeError("authoritative model failed activation")
    except Exception as recovery_exc:
        recovery_error = recovery_exc
        logger.exception("Model promotion recovery failed.")

    if recovered == "committed":
        try:
            committed = _read_json(paths.manifest)
            _write_attempt_best_effort(paths, committed)
            return committed
        except Exception:
            recovery_error = RuntimeError("committed manifest is unreadable")

    paths.candidate.unlink(missing_ok=True)
    failure = _failure_payload(started, source, error)
    if recovery_error is not None:
        failure["recovery_required"] = True
        failure["recovery_error"] = recovery_error.__class__.__name__
    _write_attempt_best_effort(paths, failure)
    logger.exception("Training pipeline failed.")
    return failure


async def run_training_pipeline(
    *,
    source: str = "mongo",
    epochs: int = 20,
) -> dict:
    """Train, validate, transactionally promote, activate, and report one model."""

    paths = PromotionPaths.for_deployed(Path(config.ML_WEIGHTS_PATH))
    started = datetime.now(timezone.utc)

    async with _PROCESS_LOCK:
        try:
            with _training_file_lock(paths.lock):
                runner = _current_runner()
                prepared = False
                try:
                    recovery = _recover_transaction(paths)
                    if recovery == "rolled_back" and not _activate_runner(
                        runner, paths.deployed
                    ):
                        raise RuntimeError("recovered model failed activation")

                    paths.candidate.unlink(missing_ok=True)
                    result = await train_metabolic_cnn(
                        source=source,
                        epochs=epochs,
                        weight_version=config.ML_WEIGHTS_VERSION,
                        output_path=paths.candidate,
                    )
                    if not isinstance(result, TrainingResult):
                        payload = {
                            "status": "rejected",
                            "started_at": started.isoformat(),
                            "finished_at": datetime.now(timezone.utc).isoformat(),
                            "source": source,
                        }
                        _write_attempt_best_effort(paths, payload)
                        return payload

                    candidate_hash = sha256_file(paths.candidate)
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
                    _prepare_transaction(
                        paths,
                        candidate_hash=candidate_hash,
                        promotion_manifest=payload,
                    )
                    prepared = True
                    _promote_candidate(paths)
                    if not _activate_runner(runner, paths.deployed):
                        raise RuntimeError("promoted model failed hot reload")
                    _publish_manifest(paths, payload)
                    try:
                        _cleanup_transaction(paths)
                    except Exception:
                        logger.exception(
                            "Promotion committed; transaction cleanup remains pending."
                        )
                    _write_attempt_best_effort(paths, payload)
                    return payload
                except Exception as exc:
                    return _recover_failed_promotion(
                        paths,
                        runner=runner,
                        started=started,
                        source=source,
                        error=exc,
                        force_rollback=prepared,
                    )
        except Exception as exc:
            failure = _failure_payload(started, source, exc)
            _write_attempt_best_effort(paths, failure)
            logger.exception("Training lock acquisition failed.")
            return failure


def read_training_manifest() -> dict:
    manifest = PromotionPaths.for_deployed(Path(config.ML_WEIGHTS_PATH)).manifest
    try:
        return _read_json(manifest)
    except (OSError, ValueError, json.JSONDecodeError):
        return {"status": "never_run"}
