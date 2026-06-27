import logging
import torch
import numpy as np
import random

# Global seeding for reproducible training (L3)
torch.manual_seed(42)
np.random.seed(42)
random.seed(42)
if torch.cuda.is_available():
    torch.cuda.manual_seed_all(42)

import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Subset
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import os

from diabetic.ml_engine.convolutional_layer import DiabeticCNN, CNNConfig
from diabetic.ml_engine.metabolic_dataset import MetabolicDataset
from diabetic.config import config

logger = logging.getLogger("Bio-Quant.ML.Train")

async def train_metabolic_cnn(
    source: str = "csv",
    csv_path: str = "storage/data/processed/mar23-apr07.csv",
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 0.001,
    weight_version: str = "v15"
):
    logger.info(f"\n--- CLINICAL TRAINING INITIATED (Source: {source}) ---")
    
    # 1. Device Setup
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Device: {device}")

    # 2. Data Loading
    if source == "mongo":
        from diabetic.ingestion.mongo import MongoDBClient
        client = MongoDBClient()
        df_input = await client.fetch_training_data(days=15)
        if df_input is None:
            logger.error("Failed to retrieve training data from MongoDB. Aborting.")
            return None
        dataset = MetabolicDataset(df_input=df_input)
    else:
        dataset = MetabolicDataset(csv_path=csv_path)
    
    # Sequential Splitting (Wave 5 Protocol)
    # Introduce gap to prevent temporal window overlap (Leakage Fix)
    gap = dataset.seq_len + dataset.prediction_offset
    if len(dataset) <= gap:
        logger.error(f"Dataset too small ({len(dataset)}) for seq_len {dataset.seq_len}. Need more data.")
        return None
        
    train_size = int(0.8 * len(dataset)) - gap
    if train_size <= 0:
        logger.error("Training set too small after gap. Aborting.")
        return None

    train_set = Subset(dataset, range(train_size))
    val_set = Subset(dataset, range(train_size + gap, len(dataset)))

    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)

    # 3. Model Initialization
    cnn_config = CNNConfig()
    model = DiabeticCNN(config=cnn_config).to(device)
    
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=5, factor=0.5)

    # 4. Training Loop
    history = {"train_loss": [], "val_loss": []}
    
    best_val = float('inf')
    patience_count = 0
    PATIENCE_LIMIT = 10

    weight_path = Path(config.ML_WEIGHTS_PATH)
    weight_path.parent.mkdir(parents=True, exist_ok=True)
    if weight_version != config.ML_WEIGHTS_VERSION:
        logger.warning(
            "Requested weight_version %s, but configured deployment path is %s. "
            "Saving to ML_WEIGHTS_PATH for scheduler/inference parity.",
            weight_version,
            config.ML_WEIGHTS_PATH,
        )

    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for temp_x, static_y, targets in train_loader:
            temp_x, static_y, targets = temp_x.to(device), static_y.to(device), targets.to(device)
            
            optimizer.zero_grad()
            outputs = model(temp_x, static_y)
            loss = criterion(outputs, targets)
            loss.backward()
            
            # Fix H4: Gradient Clipping for LSTM stability
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            
            optimizer.step()
            train_loss += loss.item()

        # Validation
        model.eval()
        val_loss = 0.0
        with torch.no_grad():
            for temp_x, static_y, targets in val_loader:
                temp_x, static_y, targets = temp_x.to(device), static_y.to(device), targets.to(device)
                outputs = model(temp_x, static_y)
                loss = criterion(outputs, targets)
                val_loss += loss.item()

        avg_train = train_loss / len(train_loader)
        avg_val = val_loss / len(val_loader)
        
        history["train_loss"].append(avg_train)
        history["val_loss"].append(avg_val)

        scheduler.step(avg_val)

        if (epoch + 1) % 5 == 0 or epoch == 0:
            logger.info(f"Epoch [{epoch+1}/{epochs}] | Train Loss: {avg_train:.6f} | Val Loss: {avg_val:.6f}")

        if avg_val < best_val:
            best_val = avg_val
            torch.save(model.state_dict(), weight_path)
            patience_count = 0
        else:
            patience_count += 1
            if patience_count >= PATIENCE_LIMIT:
                logger.info(f"EARLY STOPPING: Validation loss stagnated for {PATIENCE_LIMIT} epochs.")
                break

    # 7. ANTI-HALLUCINATION GUARD (Phase 3)
    # Strategy: Enforce clinical boundaries and error floors before allowing deployment.
    LOSS_FLOOR = 2.0  # Max allowable MSE for deployment
    if best_val > LOSS_FLOOR:
        logger.error(f"[Guard] TRAINING REJECTED: Final Val Loss ({best_val:.4f}) exceeds safety floor ({LOSS_FLOOR}). Potential divergence or data corruption.")
        if weight_path.exists(): weight_path.unlink()
        return None
        
    # Physiological Clipping Check
    try:
        model.load_state_dict(torch.load(weight_path, weights_only=True))
        model.eval()
        with torch.no_grad():
            x_sample, s_sample, _ = next(iter(val_loader))
            preds = model(x_sample.to(device), s_sample.to(device)).cpu().numpy()
            
            # Rescale for guard check (Glucose is idx 0)
            g_preds = preds[:, 0] * 20.0
            
            # Check for extreme hallucinations (outside 2.0 - 25.0 mmol/L)
            if np.any(g_preds < 2.0) or np.any(g_preds > 25.0):
                logger.error(f"[Guard] TRAINING REJECTED: Model produced non-physiological predictions (Range: {g_preds.min():.1f} - {g_preds.max():.1f}). Weights purged.")
                if weight_path.exists(): weight_path.unlink()
                return None
    except Exception as ge:
        logger.error(f"[Guard] Safety check failed with error: {ge}")
        if weight_path.exists(): weight_path.unlink()
        return None

    logger.info(f"[Guard] Anti-hallucination checks PASSED. Weights {weight_version} verified for production.")

    # 8. Convergence Visualization
    try:
        plt.figure(figsize=(10, 6))
        plt.plot(history["train_loss"], label="Train Loss")
        plt.plot(history["val_loss"], label="Val Loss")
        plt.title(f"Metabolic CNN Training Convergence ({weight_version})")
        plt.xlabel("Epoch")
        plt.ylabel("MSE Loss")
        plt.legend()
        plt.grid(True)
        
        charts_dir = Path(__file__).resolve().parents[2] / "charts"
        charts_dir.mkdir(parents=True, exist_ok=True)
        plot_path = charts_dir / "latest_training_convergence.png"
        plt.savefig(plot_path)
        plt.close()
        logger.info(f"[Visualization] Convergence plot saved to {plot_path}")
    except Exception as e:
        logger.warning(f"[Visualization] Failed to generate convergence plot: {e}")

    return model

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=str, default="csv", choices=["csv", "mongo"])
    parser.add_argument("--epochs", type=int, default=50)
    parser.add_argument("--version", type=str, default="v15")
    args = parser.parse_args()

    import asyncio
    logging.basicConfig(level=logging.INFO)
    asyncio.run(train_metabolic_cnn(
        source=args.source, 
        epochs=args.epochs,
        weight_version=args.version
    ))
