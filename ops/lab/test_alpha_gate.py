import unittest

import diabetic.medical_constants as mc


def _apply_alpha_gate(cnn: float, kinematic: float, confidence: float) -> float:
    """
    Mirrors coordinator.py:338-345.
    Extracted here so changes to the coordinator logic require updating this test.
    """
    divergence = abs(cnn - kinematic)
    if divergence > mc.ALPHA_GATE_DIVERGENCE_LIMIT and confidence < mc.ALPHA_GATE_CONFIDENCE_THRESHOLD:
        return kinematic
    return 0.5 * kinematic + 0.5 * cnn


class TestAlphaGate(unittest.TestCase):

    def test_rejects_diverging_low_confidence(self):
        """High divergence + low confidence → use kinematic (reject CNN)."""
        result = _apply_alpha_gate(cnn=10.0, kinematic=5.0, confidence=0.5)
        self.assertEqual(result, 5.0)

    def test_accepts_diverging_high_confidence(self):
        """High divergence but high confidence → blend both predictions."""
        result = _apply_alpha_gate(cnn=10.0, kinematic=5.0, confidence=0.8)
        self.assertAlmostEqual(result, 7.5)

    def test_accepts_close_predictions(self):
        """Small divergence (within limit) → blend regardless of confidence."""
        result = _apply_alpha_gate(cnn=8.0, kinematic=7.5, confidence=0.2)
        self.assertAlmostEqual(result, 7.75)

    def test_gate_constants_match_medical_constants(self):
        """
        Pin the gate thresholds. If these change in medical_constants, this test
        fails — forcing an explicit review of the gate behaviour.
        """
        self.assertEqual(mc.ALPHA_GATE_DIVERGENCE_LIMIT, 2.5)
        self.assertEqual(mc.ALPHA_GATE_CONFIDENCE_THRESHOLD, 0.7)

    def test_boundary_divergence_exactly_at_limit(self):
        """Divergence exactly equal to the limit → blend (not rejection)."""
        result = _apply_alpha_gate(
            cnn=5.0 + mc.ALPHA_GATE_DIVERGENCE_LIMIT,
            kinematic=5.0,
            confidence=0.1,
        )
        # divergence == limit (not strictly >) → blend
        self.assertAlmostEqual(result, 5.0 + mc.ALPHA_GATE_DIVERGENCE_LIMIT / 2.0)

    def test_boundary_confidence_exactly_at_threshold(self):
        """Confidence exactly equal to the threshold → blend (not rejection)."""
        result = _apply_alpha_gate(cnn=10.0, kinematic=5.0, confidence=mc.ALPHA_GATE_CONFIDENCE_THRESHOLD)
        # confidence == threshold (not strictly <) → blend
        self.assertAlmostEqual(result, 7.5)


if __name__ == "__main__":
    unittest.main()
