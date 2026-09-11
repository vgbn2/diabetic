"""Single-owner candidate validation and atomic model promotion."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import shutil
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from diabetic.config import config

try:
    from diabetic.ml_engine.train import TrainingResult, train_metabolic_cnn
except (ModuleNotFoundError, ImportError):
    TrainingResult = None  # type: ignore[assignment, misc]
    train_metabolic_cnn = None  # type: ignore[assignment]

logger = logging.getLogger("Bio-Quant.ML.TrainingService")
_PROCESS_LOCK = asyncio.Lock()


@dataclass(frozen=True)
class PromotionPaths:
    state_dir: Path
    candidate: Path
    backup: Path
    manifest: Path
    manifest_backup: Path
    journal: Path
    lock_path: Path

    @classmethod
    def for_deployed(cls, deployed: Path) -> "PromotionPaths":
        state_dir = deployed.parent / ".training"
        return cls(
            state_dir=state_dir,
            candidate=state_dir / "candidate.pth",
            backup=state_dir / "last_known_good.pth",
            manifest=state_dir / "manifest.json",
            manifest_backup=state_dir / "last_known_good_manifest.json",
            journal=state_dir / "promotion.json",
            lock_path=state_dir / "training.lock",
        )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fsync_directory(path: Path) -> None:
    if not hasattr(os, "O_DIRECTORY") or os.O_DIRECTORY is None:
        return
    try:
        fd = os.open(str(path), os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


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
    os.replace(temporary, destination)
    _fsync_directory(destination.parent)


def _promote_candidate(candidate: Path, deployed: Path) -> None:
    deployed.parent.mkdir(parents=True, exist_ok=True)
    os.replace(candidate, deployed)
    _fsync_directory(deployed.parent)


def _cleanup_transaction(paths: PromotionPaths) -> None:
    paths.candidate.unlink(missing_ok=True)
    paths.backup.unlink(missing_ok=True)
    paths.manifest_backup.unlink(missing_ok=True)
    paths.journal.unlink(missing_ok=True)


def _rollback_transaction(
    paths: PromotionPaths,
    deployed: Path,
    had_deployed: bool,
    had_manifest: bool,
) -> None:
    if had_deployed and paths.backup.exists():
        _atomic_copy(paths.backup, deployed)
    elif not had_deployed:
        deployed.unlink(missing_ok=True)

    if had_manifest and paths.manifest_backup.exists():
        _atomic_copy(paths.manifest_backup, paths.manifest)
    elif not had_manifest:
        paths.manifest.unlink(missing_ok=True)

    paths.candidate.unlink(missing_ok=True)
    paths.backup.unlink(missing_ok=True)
    paths.manifest_backup.unlink(missing_ok=True)
    paths.journal.unlink(missing_ok=True)


def recover_training_state(deployed: Path) -> str:
    paths = PromotionPaths.for_deployed(deployed)
    if not paths.journal.exists():
        return "clean"
    try:
        journal_data = json.loads(paths.journal.read_text(encoding="utf-8"))
        state = journal_data.get("state")
        if state == "committed":
            _cleanup_transaction(paths)
            return "committed"
        elif state == "prepared":
            had_deployed = journal_data.get("previous_exists", False)
            had_manifest = journal_data.get("previous_manifest_exists", False)
            _rollback_transaction(paths, deployed, had_deployed, had_manifest)
            return "rolled_back"
    except Exception:
        logger.exception("Error during recover_training_state")
        raise
    return "unknown"


def _lock_training_stream(stream):
    try:
        import fcntl

        try:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError("another training process owns the lock") from exc

        def _release_fcntl():
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)

        return _release_fcntl
    except ModuleNotFoundError:
        pass

    try:
        import msvcrt

        try:
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except (BlockingIOError, OSError) as exc:
            raise RuntimeError("another training process owns the lock") from exc

        def _release_msvcrt():
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass

        return _release_msvcrt
    except ModuleNotFoundError:
        pass

    raise RuntimeError("No supported process file lock mechanism available on this platform")


@contextmanager
def _training_file_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as stream:
        release = _lock_training_stream(stream)
        try:
            yield
        finally:
            release()


async def run_training_pipeline(
    *,
    source: str = "mongo",
    epochs: int = 20,
) -> dict:
    """Train, validate, atomically promote, reload, and report one model."""

    deployed = Path(config.ML_WEIGHTS_PATH)
    paths = PromotionPaths.for_deployed(deployed)
    paths.state_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc)

    async with _PROCESS_LOCK:
        try:
            with _training_file_lock(paths.lock_path):
                recover_training_state(deployed)
                paths.candidate.unlink(missing_ok=True)

                train_fn = train_metabolic_cnn
                result_cls = TrainingResult
                if train_fn is None or result_cls is None:
                    from diabetic.ml_engine.train import (
                        TrainingResult as _TR,
                        train_metabolic_cnn as _TMC,
                    )
                    train_fn = _TMC
                    result_cls = _TR

                result = await train_fn(
                    source=source,
                    epochs=epochs,
                    weight_version=config.ML_WEIGHTS_VERSION,
                    output_path=paths.candidate,
                )
                if not isinstance(result, result_cls):
                    payload = {
                        "status": "rejected",
                        "started_at": started.isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "source": source,
                    }
                    _atomic_json(paths.manifest, payload)
                    return payload

                candidate_hash = sha256_file(paths.candidate)
                had_deployed = deployed.exists()
                had_manifest = paths.manifest.exists()
                old_deployed_hash = sha256_file(deployed) if had_deployed else None

                if had_deployed:
                    _atomic_copy(deployed, paths.backup)
                if had_manifest:
                    _atomic_copy(paths.manifest, paths.manifest_backup)

                journal_payload = {
                    "state": "prepared",
                    "candidate_sha256": candidate_hash,
                    "previous_exists": had_deployed,
                    "previous_sha256": old_deployed_hash,
                    "previous_manifest_exists": had_manifest,
                }
                _atomic_json(paths.journal, journal_payload)

                coordinator = None
                try:
                    _promote_candidate(paths.candidate, deployed)

                    reload_ok = True
                    try:
                        from diabetic.coordinator import Coordinator

                        coordinator = Coordinator._instance
                        if coordinator and coordinator.neural_runner:
                            reload_ok = coordinator.neural_runner.reload_weights(deployed)
                    except Exception:
                        logger.exception("Model hot reload raised unexpectedly.")
                        reload_ok = False

                    if not reload_ok:
                        if coordinator and coordinator.neural_runner:
                            coordinator.neural_runner.weights_loaded = False
                        raise RuntimeError("promoted model failed hot reload")

                    manifest_payload = {
                        "status": "promoted",
                        "started_at": started.isoformat(),
                        "finished_at": datetime.now(timezone.utc).isoformat(),
                        "source": source,
                        "sample_count": result.sample_count,
                        "validation_loss": result.best_validation_loss,
                        "version": config.ML_WEIGHTS_VERSION,
                        "sha256": candidate_hash,
                    }
                    _atomic_json(paths.manifest, manifest_payload)

                    _atomic_json(
                        paths.journal,
                        {
                            "state": "committed",
                            "candidate_sha256": candidate_hash,
                            "previous_exists": had_deployed,
                            "previous_manifest_exists": had_manifest,
                        },
                    )
                except Exception as promote_exc:
                    _rollback_transaction(paths, deployed, had_deployed, had_manifest)
                    if had_deployed and coordinator and coordinator.neural_runner:
                        try:
                            restored = coordinator.neural_runner.reload_weights(deployed)
                            if restored:
                                coordinator.neural_runner.weights_loaded = True
                        except Exception:
                            logger.exception("Last-known-good reload failed.")
                    raise promote_exc

                try:
                    _cleanup_transaction(paths)
                except Exception:
                    logger.warning("Transaction cleanup failed.")

                return manifest_payload
        except Exception as exc:
            paths.candidate.unlink(missing_ok=True)
            payload = {
                "status": "failed",
                "started_at": started.isoformat(),
                "finished_at": datetime.now(timezone.utc).isoformat(),
                "source": source,
                "error": str(exc) if "supported process file lock" in str(exc) else exc.__class__.__name__,
            }
            logger.exception("Training pipeline failed.")
            return payload


def read_training_manifest() -> dict:
    manifest = Path(config.ML_WEIGHTS_PATH).parent / ".training" / "manifest.json"
    try:
        return json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"status": "never_run"}
