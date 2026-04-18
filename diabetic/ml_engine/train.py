import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import DataLoader, Subset
import pandas as pd
import matplotlib.pyplot as plt
from pathlib import Path
import os

from diabetic.ml_engine.convolutional_layer import DiabeticCNN, CNNConfig
from diabetic.ml_engine.metabolic_dataset import MetabolicDataset

def train_metabolic_cnn(
    csv_path: str = "storage/data/processed/mar23-apr07.csv",
    epochs: int = 50,
    batch_size: int = 32,
    lr: float = 0.001
):
    print(f"\n--- CLINICAL TRAINING INITIATED: {csv_path} ---")
    
    # 1. Device Setup
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Device: {device}")

    # 2. Data Loading & Sequential Splitting (Wave 5 Protocol)
    dataset = MetabolicDataset(csv_path)
    
    # Introduce gap to prevent temporal window overlap (Leakage Fix)
    gap = dataset.seq_len + dataset.prediction_offset
    train_size = int(0.8 * len(dataset)) - gap
    
    train_set = Subset(dataset, range(train_size))
    val_set = Subset(dataset, range(train_size + gap, len(dataset)))

    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)

    # 3. Model Initialization
    config = CNNConfig()
    model = DiabeticCNN(config=config).to(device)
    
    criterion = nn.MSELoss()
    optimizer = optim.Adam(model.parameters(), lr=lr)

    # 4. Training Loop
    history = {"train_loss": [], "val_loss": []}
    
    for epoch in range(epochs):
        model.train()
        train_loss = 0.0
        for temp_x, static_y, targets in train_loader:
            temp_x, static_y, targets = temp_x.to(device), static_y.to(device), targets.to(device)
            
            optimizer.zero_grad()
            outputs = model(temp_x, static_y)
            loss = criterion(outputs, targets)
            loss.backward()
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

        if (epoch + 1) % 5 == 0 or epoch == 0:
            print(f"Epoch [{epoch+1}/{epochs}] | Train Loss: {avg_train:.6f} | Val Loss: {avg_val:.6f}")

    # 5. Save Weights
    weight_dir = Path("diabetic/ml_engine/weights")
    weight_dir.mkdir(parents=True, exist_ok=True)
    weight_path = weight_dir / "diabetic_cnn_v14.pth"
    torch.save(model.state_dict(), weight_path)
    print(f"\nSUCCESS: Model Weights Saved to {weight_path}")

    # 6. Plot Loss
    plt.figure(figsize=(10, 6))
    plt.plot(history["train_loss"], label="Train Loss")
    plt.plot(history["val_loss"], label="Val Loss")
    plt.title("Metabolic CNN Training Convergence")
    plt.xlabel("Epoch")
    plt.ylabel("MSE Loss")
    plt.legend()
    plt.grid(True, alpha=0.3)
    
    plot_path = "storage/data/processed/plots/training_loss.png"
    plt.savefig(plot_path)
    print(f"Convergence Plot Saved: {plot_path}")

    return model

if __name__ == "__main__":
    train_metabolic_cnn()
