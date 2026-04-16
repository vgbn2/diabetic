"""
Context Classifier: Labels metabolic snapshots with their probable physiological cause.

Uses BPM (Heart Rate) and HRV (Heart Rate Variability) heuristics to differentiate:
  - FOOD:              Meal detected in the metabolic treatment window.
  - EXERCISE:          High HR (>110 BPM) + Low HRV (<20 ms).
  - STRESS_STUDYING:   Medium-High HR (85-110 BPM) + Low HRV (<30 ms).
  - RELAXED_STUDYING:  Baseline HR (65-85 BPM) + Normal HRV (30-60 ms).
  - SLEEP:             Low HR (<65 BPM) + High HRV (>60 ms).
  - RANDOM_SPIKE:      Glucose rising without any identified trigger.
  - UNKNOWN:           Insufficient cardiac data to classify.

Thresholds are defined in medical_constants.py and treated as personalization seeds.
"""
from enum import Enum
from typing import Optional
from diabetic.registry import MetabolicSnapshot
from diabetic import medical_constants as mc


class ActivityType(Enum):
    FOOD = "FOOD"
    EXERCISE = "EXERCISE"
    STRESS_STUDYING = "STRESS_STUDYING"
    STRESS_ANOMALY = "STRESS_ANOMALY"  # Glucose/HR Decoupling
    RELAXED_STUDYING = "RELAXED_STUDYING"
    SLEEP = "SLEEP"
    RANDOM_SPIKE = "RANDOM_SPIKE"
    UNKNOWN = "UNKNOWN"


def classify_context(snapshot: MetabolicSnapshot) -> ActivityType:
    """
    Heuristic classifier for metabolic context.

    Priority order (highest to lowest):
    1. FOOD — if a meal event exists in the snapshot, food dominates.
    2. EXERCISE — high cardiac output overrides other labels.
    3. STRESS_ANOMALY — high velocity but LOW heart rate (Decoupling).
    4. STRESS_STUDYING — elevated HR with low HRV.
    5. SLEEP — low HR with high HRV.
    6. RANDOM_SPIKE — glucose rising without a known cause.
    7. RELAXED_STUDYING — baseline state (fallback when awake).
    8. UNKNOWN — no cardiac data available.
    """
    # 1. Food (highest priority — if meal logged, that's the cause)
    if snapshot.last_meal is not None:
        return ActivityType.FOOD

    # 1b. Anomaly: High speed but low HR (Decoupling)
    # We check this early because it represents a potential emergency or stress event
    # that is explicitly NOT exercise.
    is_rising_fast = snapshot.velocity > mc.FAINT_VELOCITY_LIMIT_PER_MIN
    bpm = snapshot.bpm
    hrv = snapshot.hrv

    if bpm is not None and is_rising_fast and bpm < mc.BPM_STRESS_THRESHOLD:
        return ActivityType.STRESS_ANOMALY

    # Require cardiac data for remaining complex classifications
    if bpm is None or hrv is None:
        if is_rising_fast:
            return ActivityType.RANDOM_SPIKE
        return ActivityType.UNKNOWN

    # 2. Exercise: high HR + low HRV
    if bpm > mc.BPM_EXERCISE_THRESHOLD and hrv < 20:
        return ActivityType.EXERCISE

    # 3. Stress Studying: medium-high HR + low HRV
    if bpm > mc.BPM_STRESS_THRESHOLD and hrv < mc.HRV_STRESS_CEILING:
        return ActivityType.STRESS_STUDYING

    # 4. Sleep: low HR + high HRV
    if bpm < mc.BPM_SLEEP_CEILING and hrv > mc.HRV_SLEEP_FLOOR:
        return ActivityType.SLEEP

    # 5. Random Spike: glucose climbing without identified trigger
    if is_rising_fast:
        return ActivityType.RANDOM_SPIKE

    # 6. Fallback: Relaxed Studying / baseline awake state
    return ActivityType.RELAXED_STUDYING


if __name__ == "__main__":
    from datetime import datetime, timezone
    from diabetic.registry import GlucoseReading, CardiacReading, MealEvent

    base_glucose = GlucoseReading(
        timestamp=datetime.now(timezone.utc), value=7.0, trend="Flat"
    )

    # Test 1: Meal present
    snap = MetabolicSnapshot(glucose=base_glucose, last_meal=MealEvent(
        timestamp=datetime.now(timezone.utc), carbs=30
    ))
    result = classify_context(snap)
    assert result == ActivityType.FOOD, f"Expected FOOD, got {result}"
    print(f"[TEST 1] Meal present  -> {result.value} [OK]")

    # Test 2: Exercise
    snap = MetabolicSnapshot(glucose=base_glucose, cardiac=CardiacReading(
        timestamp=datetime.now(timezone.utc), bpm=130, hrv=12.0
    ))
    result = classify_context(snap)
    assert result == ActivityType.EXERCISE, f"Expected EXERCISE, got {result}"
    print(f"[TEST 2] High HR/Low HRV -> {result.value} [OK]")

    # Test 3: Stress Studying
    snap = MetabolicSnapshot(glucose=base_glucose, cardiac=CardiacReading(
        timestamp=datetime.now(timezone.utc), bpm=95, hrv=22.0
    ))
    result = classify_context(snap)
    assert result == ActivityType.STRESS_STUDYING, f"Expected STRESS_STUDYING, got {result}"
    print(f"[TEST 3] Med HR/Low HRV -> {result.value} [OK]")

    # Test 4: Sleep
    snap = MetabolicSnapshot(glucose=base_glucose, cardiac=CardiacReading(
        timestamp=datetime.now(timezone.utc), bpm=55, hrv=75.0
    ))
    result = classify_context(snap)
    assert result == ActivityType.SLEEP, f"Expected SLEEP, got {result}"
    print(f"[TEST 4] Low HR/High HRV -> {result.value} [OK]")

    # Test 5: Stress Anomaly (Decoupling)
    # High velocity (0.15) but baseline HR (72)
    snap = MetabolicSnapshot(glucose=base_glucose, velocity=0.15, cardiac=CardiacReading(
        timestamp=datetime.now(timezone.utc), bpm=72, hrv=45.0
    ))
    result = classify_context(snap)
    assert result == ActivityType.STRESS_ANOMALY, f"Expected STRESS_ANOMALY, got {result}"
    print(f"[TEST 5] Decoupling detected -> {result.value} [OK]")

    # Test 6: Random Spike (No cardiac data)
    snap = MetabolicSnapshot(glucose=base_glucose, velocity=0.15, cardiac=None)
    result = classify_context(snap)
    assert result == ActivityType.RANDOM_SPIKE, f"Expected RANDOM_SPIKE, got {result}"
    print(f"[TEST 6] Rising w/no HR data -> {result.value} [OK]")

    # Test 7: Relaxed baseline
    snap = MetabolicSnapshot(glucose=base_glucose, velocity=0.01, cardiac=CardiacReading(
        timestamp=datetime.now(timezone.utc), bpm=72, hrv=45.0
    ))
    result = classify_context(snap)
    assert result == ActivityType.RELAXED_STUDYING, f"Expected RELAXED_STUDYING, got {result}"
    print(f"[TEST 7] Baseline awake -> {result.value} [OK]")

    print("\nALL CONTEXT CLASSIFIER TESTS PASSED.")
