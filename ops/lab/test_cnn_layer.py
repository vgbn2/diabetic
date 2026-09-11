import torch
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from diabetic.config import config
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.ml_engine.convolutional_layer import DiabeticCNN
from diabetic.ml_engine.inference import MetabolicInferenceRunner

class TestDiabeticCNN(unittest.TestCase):
    def setUp(self):
        self.temporal_channels = 2  # Glucose + Heart Rate
        self.static_features = 15   # Age, weight, gender, ethnicity, etc (Layer 1-2)
        self.seq_len = 30           # 30 timestamps (e.g., last 150 mins if 5m intervals)
        self.batch_size = 16
        
        self.model = DiabeticCNN(
            temporal_channels=self.temporal_channels,
            static_features=self.static_features,
            lstm_hidden_size=64
        )

    def test_forward_dims(self):
        """Verify the model outputs glucose and heart-rate predictions per batch item."""
        # [Batch, Channels, Time]
        X_temp = torch.randn(self.batch_size, self.temporal_channels, self.seq_len)
        # [Batch, StaticFeatures]
        X_static = torch.randn(self.batch_size, self.static_features)
        
        output = self.model(X_temp, X_static)
        
        self.assertEqual(output.shape, (self.batch_size, 2))

    def test_gradient_flow(self):
        """Verify that gradients propagate to the weights."""
        X_temp = torch.randn(self.batch_size, self.temporal_channels, self.seq_len)
        X_static = torch.randn(self.batch_size, self.static_features)
        target = torch.randn(self.batch_size, 2)
        
        output = self.model(X_temp, X_static)
        loss = torch.nn.MSELoss()(output, target)
        loss.backward()
        
        # Check if one of the model's parameters has a gradient
        for name, param in self.model.named_parameters():
            if param.requires_grad:
                self.assertIsNotNone(param.grad, f"Gradient for {name} is None")
                break


class TestMetabolicInferenceRunner(unittest.TestCase):
    def test_short_window_before_hot_reload(self):
        """Fresh runners must initialize sampling mode before first inference."""
        runner = MetabolicInferenceRunner()
        self.assertTrue(runner.weights_loaded)
        snapshot = MetabolicSnapshot(
            glucose=GlucoseReading(
                timestamp=datetime.now(timezone.utc),
                value=6.5,
                trend="Flat",
            )
        )

        tensor = runner._prepare_temporal_tensor([snapshot])

        self.assertFalse(runner._resample_to_5min)
        self.assertIsNone(tensor)

    def test_full_window_matches_model_channels(self):
        """Live inference windows must match the two-channel training contract."""
        runner = MetabolicInferenceRunner()
        start = datetime.now(timezone.utc) - timedelta(minutes=145)
        snapshots = [
            MetabolicSnapshot(
                glucose=GlucoseReading(
                    timestamp=start + timedelta(minutes=5 * idx),
                    value=6.0 + (idx * 0.01),
                    trend="Flat",
                ),
                predicted_hr=72.0,
            )
            for idx in range(runner.seq_len)
        ]

        tensor = runner._prepare_temporal_tensor(snapshots)
        result = runner.run_inference_on_snapshots(snapshots)

        self.assertEqual(tensor.shape, (1, runner.config.temporal_channels, runner.seq_len))
        self.assertEqual(runner.config.temporal_channels, 2)
        self.assertIn("glucose", result)
        self.assertIn("heart_rate", result)

    def test_missing_weights_disable_neural_inference(self):
        """Missing deployment weights must fall back instead of using random parameters."""
        with TemporaryDirectory() as tmpdir:
            missing_path = Path(tmpdir) / "missing-v15.pth"
            with patch.object(config, "ML_WEIGHTS_PATH", str(missing_path)):
                runner = MetabolicInferenceRunner()

        start = datetime.now(timezone.utc) - timedelta(minutes=145)
        snapshots = [
            MetabolicSnapshot(
                glucose=GlucoseReading(
                    timestamp=start + timedelta(minutes=5 * idx),
                    value=6.0 + (idx * 0.01),
                    trend="Flat",
                ),
                predicted_hr=72.0,
            )
            for idx in range(runner.seq_len)
        ]

        self.assertFalse(runner.weights_loaded)
        self.assertIsNone(runner.run_inference_on_snapshots(snapshots))

if __name__ == "__main__":
    unittest.main()
