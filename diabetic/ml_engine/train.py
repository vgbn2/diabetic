"""Off-loop CNN candidate training.

This module produces a validated candidate artifact. Deployment promotion is
owned by :mod:`diabetic.ml_engine.training_service`.
"""

from __future__ import annotations

import asyncio
import logging
import random
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Subset

from diabetic.config import config
from diabetic.ml_engine.convolutional_layer import CNNConfig, DiabeticCNN
from diabetic.ml_engine.metabolic_dataset import MetabolicDataset

logger = logging.getLogger("Bio-Quant.ML.Train")


@dataclass(frozen=True)
class TrainingResult:
    model: DiabeticCNN
    best_validation_loss: float
    sample_count: int
    artifact_path: Path


def _seed_training() -> None:
    torch.manual_seed(42)
    np.random.seed(42)
    random.seed(42)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(42)


def _remove_candidate(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        logger.exception("Could not remove rejected candidate artifact.")


def _train_dataset(
    dataset: MetabolicDataset,
    *,
    epochs: int,
    batch_size: int,
    lr: float,
    weight_version: str,
    output_path: Path,
) -> TrainingResult | None:
    """Train and validate a candidate synchronously in a worker thread."""

    _seed_training()
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info("Training candidate on device %s", device)

    gap = dataset.seq_len + dataset.prediction_offset
    if len(dataset) <= gap:
        logger.error(
            "Dataset too small (%s) for sequence gap %s.", len(dataset), gap
        )
        return None

    train_size = int(0.8 * len(dataset)) - gap
    if train_size <= 0:
        logger.error("Training set is empty after leakage gap.")
        return None

    train_set = Subset(dataset, range(train_size))
    val_set = Subset(dataset, range(train_size + gap, len(dataset)))
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)
    if not train_loader or not val_loader:
        logger.error("Training or validation loader is empty.")
        return None

    model = DiabeticCNN(config=CNNConfig()).to(device)
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    lr_scheduler = optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, patience=5, factor=0.5
    )

    history = {"train_loss": [], "val_loss": []}
    best_val = float("inf")
    patience_count = 0
    patience_limit = 10
    output_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for temporal, static, targets in train_loader:
            temporal, static, targets = (
                temporal.to(device),
                static.to(device),
                targets.to(device),
            )
            optimizer.zero_grad()
            loss = criterion(model(temporal, static), targets)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()
            train_loss += loss.item()

        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for temporal, static, targets in val_loader:
                temporal, static, targets = (
                    temporal.to(device),
                    static.to(device),
                    targets.to(device),
                )
                val_loss += criterion(model(temporal, static), targets).item()

        avg_train = train_loss / len(train_loader)
        avg_val = val_loss / len(val_loader)
        history["train_loss"].append(avg_train)
        history["val_loss"].append(avg_val)
        lr_scheduler.step(avg_val)

        if epoch == 0 or (epoch + 1) % 5 == 0:
            logger.info(
                "Epoch %s/%s train=%.6f validation=%.6f",
                epoch + 1,
                epochs,
                avg_train,
                avg_val,
            )

        if avg_val < best_val:
            best_val = avg_val
            torch.save(model.state_dict(), output_path)
            patience_count = 0
        else:
            patience_count += 1
            if patience_count >= patience_limit:
                break

    if best_val > 2.0:
        logger.error("Candidate rejected: validation MSE %.4f exceeds 2.0.", best_val)
        _remove_candidate(output_path)
        return None

    try:
        model.load_state_dict(torch.load(output_path, weights_only=True))
        model.eval()
        with torch.no_grad():
            temporal, static, _ = next(iter(val_loader))
            predictions = (
                model(temporal.to(device), static.to(device)).cpu().numpy()
            )
        glucose_predictions = predictions[:, 0] * 20.0
        if np.any(glucose_predictions < 2.0) or np.any(glucose_predictions > 25.0):
            logger.error(
                "Candidate rejected: physiological range %.2f–%.2f mmol/L.",
                glucose_predictions.min(),
                glucose_predictions.max(),
            )
            _remove_candidate(output_path)
            return None
    except Exception:
        logger.exception("Candidate load/physiology validation failed.")
        _remove_candidate(output_path)
        return None

    try:
        charts_dir = Path(__file__).resolve().parents[2] / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        plt.figure(figsize=(10, 6))
        plt.plot(history["train_loss"], label="Train Loss")
        plt.plot(history["val_loss"], label="Validation Loss")
        plt.title(f"Metabolic CNN Training ({weight_version})")
        plt.xlabel("Epoch")
        plt.ylabel("MSE")
        plt.legend()
        plt.grid(True)
        plt.savefig(charts_dir / "latest_training_convergence.png")
        plt.close()
    except Exception:
        logger.exception("Could not render convergence chart.")

    return TrainingResult(
        model=model,
        best_validation_loss=best_val,
        sample_count=len(dataset),
        artifact_path=output_path,
    )


async def train_metabolic_cnn(
    source: str = "csv",
    csv_path: str = "storage/data/processed/mar23-apr07.csv",
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 0.001,
    weight_version: str = "v15",
    output_path: Path | None = None,
) -> TrainingResult | None:
    """Load data asynchronously and train a candidate off the live event loop."""

    logger.info("Clinical candidate training requested from %s.", source)
    if source == "mongo":
        from diabetic.ingestion.mongo import MongoDBClient

        frame = await MongoDBClient().fetch_training_data(days=15)
        if frame is None:
            logger.error("MongoDB did not provide deployable training data.")
            return None
        dataset = MetabolicDataset(
            df_input=frame,
            allow_synthetic_cardiac=False,
        )
    else:
        dataset = MetabolicDataset(csv_path=csv_path)

    candidate_path = Path(output_path or config.ML_WEIGHTS_PATH)
    return await asyncio.to_thread(
        _train_dataset,
        dataset,
        epochs=epochs,
        batch_size=batch_size,
        lr=lr,
        weight_version=weight_version,
        output_path=candidate_path,
    )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default="csv", choices=["csv", "mongo"])
    parser.add_argument("--epochs", type=int, default=50)
    args = parser.parse_args()

    from diabetic.ml_engine.training_service import run_training_pipeline

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_training_pipeline(source=args.source, epochs=args.epochs))
