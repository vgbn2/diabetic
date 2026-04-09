import torch
import unittest
from diabetic.ml_engine.convolutional_layer import DiabeticCNN

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
        """Verify the model outputs a single scalar residue per batch item."""
        # [Batch, Channels, Time]
        X_temp = torch.randn(self.batch_size, self.temporal_channels, self.seq_len)
        # [Batch, StaticFeatures]
        X_static = torch.randn(self.batch_size, self.static_features)
        
        output = self.model(X_temp, X_static)
        
        self.assertEqual(output.shape, (self.batch_size, 1))

    def test_gradient_flow(self):
        """Verify that gradients propagate to the weights."""
        X_temp = torch.randn(self.batch_size, self.temporal_channels, self.seq_len)
        X_static = torch.randn(self.batch_size, self.static_features)
        target = torch.randn(self.batch_size, 1)
        
        output = self.model(X_temp, X_static)
        loss = torch.nn.MSELoss()(output, target)
        loss.backward()
        
        # Check if one of the model's parameters has a gradient
        for name, param in self.model.named_parameters():
            if param.requires_grad:
                self.assertIsNotNone(param.grad, f"Gradient for {name} is None")
                break

if __name__ == "__main__":
    unittest.main()
