import torch
import torch.nn as nn
from dataclasses import dataclass, field


@dataclass
class CNNConfig:
    """
    Centralized hyperparameter registry for DiabeticCNN.
    Modify this config to tune without touching model code.
    """
    # --- Input Geometry ---
    temporal_channels: int = 2      # e.g. Glucose + Heart Rate
    static_features: int = 15       # Bio-basal trait count (L1-L2)

    # --- CNN (Temporal Feature Extractor) ---
    cnn_out_channels: int = 32
    kernel_size: int = 3

    # --- LSTM (Sequence Memory) ---
    lstm_hidden_size: int = 64
    lstm_num_layers: int = 1

    # --- MLP (Static Embedding) ---
    static_emb_size: int = 32
    static_hidden_size: int = 64

    # --- Fusion Head ---
    head_hidden_size: int = 32

    # --- Regularization ---
    dropout: float = 0.2


class DiabeticCNN(nn.Module):
    """
    Hybrid CNN + LSTM + MLP architecture for Metabolic Intelligence.
    Fuses temporal sensor traces with static bio-basal traits.

    Architecture (Phase 10.1):
    1. Temporal Path (Layer 1): Input(B, C, T) -> Conv1d -> ReLU -> MaxPool1d -> LSTM -> Hidden
    2. Static Path (Layer 1-2): Input(B, S) -> Linear -> ReLU -> Linear -> Embedding
    3. Head: Concat(Hidden, Embedding) -> Linear -> Output(B, 2)
    """
    # --- Metadata for Inference (Phase 15.2) ---
    STATIC_FEATURE_LABELS = [
        "age", "weight", "height", "gender", "ethnicity", 
        "diabetes_type", "diagnosis_year", "activity_level",
        "fructosamin", "is_inflamed", "is_sick", #cant really know if someone is sick without them telling
        "temporal_multiplier", "temp_forcing", "hum_forcing", "aqi_forcing"
    ]

    def __init__(
        self,
        temporal_channels: int = 2,
        static_features: int = 15,
        lstm_hidden_size: int = 64,
        config: CNNConfig | None = None
    ):
        super(DiabeticCNN, self).__init__()

        # If no config provided, build one from the legacy kwargs
        if config is None:
            config = CNNConfig(
                temporal_channels=temporal_channels,
                static_features=static_features,
                lstm_hidden_size=lstm_hidden_size
            )
        self.config = config
        c = config

        # 1. Temporal Processing (CNN -> LSTM)
        self.conv1 = nn.Conv1d(
            in_channels=c.temporal_channels,
            out_channels=c.cnn_out_channels,
            kernel_size=c.kernel_size,
            padding=c.kernel_size // 2
        )
        self.relu = nn.ReLU()
        self.pool = nn.MaxPool1d(kernel_size=2)

        self.lstm = nn.LSTM(
            input_size=c.cnn_out_channels,
            hidden_size=c.lstm_hidden_size,
            batch_first=True,
            num_layers=c.lstm_num_layers
        )

        # 2. Static Feature Processing (MLP)
        self.static_mlp = nn.Sequential(
            nn.Linear(c.static_features, c.static_hidden_size),
            nn.ReLU(),
            nn.Dropout(c.dropout),
            nn.Linear(c.static_hidden_size, c.static_emb_size),
            nn.ReLU()
        )

        # 3. Fusion Head
        self.head = nn.Sequential(
            nn.Linear(c.lstm_hidden_size + c.static_emb_size, c.head_hidden_size),
            nn.ReLU(),
            nn.Linear(c.head_hidden_size, 2) # Output: [Glucose, HeartRate]
        )

    def forward(self, temporal_x: torch.Tensor, static_y: torch.Tensor) -> torch.Tensor:
        """
        Forward pass for hybrid metabolic forecasting.

        Args:
            temporal_x: (Batch, Channels, TimeSteps)
            static_y: (Batch, StaticFeatures)
        Returns:
            Output: (Batch, 2) normalized [glucose, heart_rate] forecast
        """
        # --- Temporal Path ---
        x = self.conv1(temporal_x)
        x = self.relu(x)
        x = self.pool(x)

        # LSTM wants (Batch, Seq, Features)
        x = x.transpose(1, 2)
        lstm_out, (h_n, c_n) = self.lstm(x)

        # Extract latest hidden state: (Batch, HiddenSize)
        temporal_features = h_n[-1]

        # --- Static Path ---
        static_features_emb = self.static_mlp(static_y)

        # --- Fusion ---
        combined = torch.cat([temporal_features, static_features_emb], dim=1)

        return self.head(combined)
