"""Explicit model-training controls."""

import json

from diabetic.ml_engine.training_service import (
    read_training_manifest,
    run_training_pipeline,
)


async def train(flags: dict) -> int:
    source = str(flags.get("--source", "mongo"))
    epochs = int(flags.get("--epochs", 20))
    result = await run_training_pipeline(source=source, epochs=epochs)
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "promoted" else 1


async def status(_flags: dict) -> int:
    print(json.dumps(read_training_manifest(), indent=2))
    return 0
