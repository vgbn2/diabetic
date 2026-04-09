import torch
import torch.nn as nn
from typing import Optional

class DiabeticCNN(nn.Module):
    """
    Hybrid CNN + LSTM + MLP architecture for Metabolic Intelligence.
    Fuses temporal sensor traces with static bio-basal traits.
    
    Architecture (Phase 10.1):
    1. Temporal Path (Layer 1): Input(B, C, T) -> Conv1d -> ReLU -> MaxPool1d -> LSTM -> Hidden
    2. Static Path (Layer 1-2): Input(B, S) -> Linear -> ReLU -> Linear -> Embedding
    3. Head: Concat(Hidden, Embedding) -> Linear -> Output(B, 1)
    """
    def __init__(
        self,
        temporal_channels: int = 2,
        static_features: int = 15,
        cnn_out_channels: int = 32,
        kernel_size: int = 3,
        lstm_hidden_size: int = 64,
        static_emb_size: int = 32,
        dropout: float = 0.2
    ):
        super(DiabeticCNN, self).__init__()
        
        # 1. Temporal Processing (CNN -> LSTM)
        self.conv1 = nn.Conv1d(
            in_channels=temporal_channels,
            out_channels=cnn_out_channels,
            kernel_size=kernel_size,
            padding=kernel_size // 2
        )
        self.relu = nn.ReLU()
        self.pool = nn.MaxPool1d(kernel_size=2)
        
        # After stride-2 pool, seq_len is halved.
        self.lstm = nn.LSTM(
            input_size=cnn_out_channels,
            hidden_size=lstm_hidden_size,
            batch_first=True,
            num_layers=1
        )
        
        # 2. Static Feature Processing (MLP)
        self.static_mlp = nn.Sequential(
            nn.Linear(static_features, 64),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(64, static_emb_size),
            nn.ReLU()
        )
        
        # 3. Fusion Head
        self.head = nn.Sequential(
            nn.Linear(lstm_hidden_size + static_emb_size, 32),
            nn.ReLU(),
            nn.Linear(32, 1)
        )

    def forward(self, temporal_x: torch.Tensor, static_y: torch.Tensor) -> torch.Tensor:
        """
        Forward pass for hybrid metabolic forecasting.
        
        Args:
            temporal_x: (Batch, Channels, TimeSteps)
            static_y: (Batch, StaticFeatures)
        Returns:
            Output: (Batch, 1) scalar residue
        """
        # --- Temporal Path ---
        # B, C, T -> B, C_out, T_pooled
        x = self.conv1(temporal_x)
        x = self.relu(x)
        x = self.pool(x)
        
        # LSTM wants (Batch, Seq, Features) -> (Batch, T_pooled, C_out)
        x = x.transpose(1, 2)
        
        # lstm_out: (Batch, Seq, HiddenSize), h_n: (Layers, Batch, HiddenSize)
        lstm_out, (h_n, c_n) = self.lstm(x)
        
        # Extract latest hidden state: (Batch, HiddenSize)
        temporal_features = h_n[-1]
        
        # --- Static Path ---
        static_features_emb = self.static_mlp(static_y)
        
        # --- Fusion ---
        combined = torch.cat([temporal_features, static_features_emb], dim=1)
        
        return self.head(combined)
