"""
Phase 5 — Hot-Reload Stress Test
=================================
Tests whether reload_weights() corrupts in-flight inference.

MongoDB thread-pool exhaustion (the other Phase 5 goal) requires a live Atlas
connection. When MONGO_URI is set, run this script with a real database to
observe serverSelectionTimeoutMS behaviour under concurrent training + polling
load. Without a connection, this script exercises the local CPU path only.

Usage:
    python scripts/simulation/stress_scheduler.py
"""

import asyncio
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

logging.basicConfig(level=logging.WARNING)

from diabetic.config import config
from diabetic.registry import GlucoseReading, MetabolicSnapshot
from diabetic.ml_engine.inference import MetabolicInferenceRunner

ITERATIONS = 100
RELOAD_AT = 50  # Trigger hot-reload mid-stream at this iteration


def _build_snapshots(n: int = 30) -> list:
    """Deterministic 30-snapshot window matching the two-channel training contract."""
    base = datetime.now(timezone.utc) - timedelta(minutes=5 * n)
    return [
        MetabolicSnapshot(
            glucose=GlucoseReading(
                timestamp=base + timedelta(minutes=5 * i),
                value=round(7.0 + 0.05 * math.sin(i * 0.3), 2),
                trend="Flat",
            ),
            predicted_hr=72.0,
        )
        for i in range(n)
    ]


async def main() -> None:
    runner = MetabolicInferenceRunner()
    snapshots = _build_snapshots(runner.seq_len)

    weight_path = Path(config.ML_WEIGHTS_PATH)
    weights_available = weight_path.exists()
    if not weights_available:
        print(f"[WARN] Weights not found at {weight_path}. Runner operates in Cold Mode.")

    results: list[dict] = []

    for i in range(ITERATIONS):
        if i == RELOAD_AT and weights_available:
            # Trigger hot-reload in a thread while the main loop continues
            reload_task = asyncio.create_task(
                asyncio.to_thread(runner.reload_weights, weight_path)
            )

        t0 = time.perf_counter()
        result = runner.run_inference_on_snapshots(snapshots)
        elapsed_ms = (time.perf_counter() - t0) * 1000.0

        results.append({"iter": i, "result": result, "ms": elapsed_ms})

        # Yield to the event loop so the reload task can run
        await asyncio.sleep(0)

    # Wait for reload to finish if it was launched
    if weights_available and RELOAD_AT < ITERATIONS:
        await reload_task

    # --- Report ---
    succeeded = [r for r in results if r["result"] is not None]
    failed = [r for r in results if r["result"] is None]
    latencies = [r["ms"] for r in results]

    # Check for NaN/non-finite in successful results
    anomalies = [
        r for r in succeeded
        if not (math.isfinite(r["result"]["glucose"]) and math.isfinite(r["result"]["heart_rate"]))
    ]

    print(f"\n{'='*60}")
    print(f"  Bio-Quant Phase 5 — Hot-Reload Stress Report")
    print(f"{'='*60}")
    print(f"  Iterations      : {ITERATIONS}")
    print(f"  Succeeded       : {len(succeeded)}/{ITERATIONS}")
    print(f"  Failed (None)   : {len(failed)}")
    print(f"  Anomalies (NaN) : {len(anomalies)}")
    print(f"  Reload at iter  : {RELOAD_AT} ({'weights present' if weights_available else 'skipped — no weights'})")
    print(f"  Latency (ms)    : min={min(latencies):.1f}  avg={sum(latencies)/len(latencies):.1f}  max={max(latencies):.1f}")
    print(f"{'='*60}\n")

    # Exit non-zero if any hard failure
    if failed or anomalies:
        print("[FAIL] Hot-reload stress test detected inference failures.")
        raise SystemExit(1)
    else:
        print("[PASS] Hot-reload stress test: all inferences succeeded.")


if __name__ == "__main__":
    asyncio.run(main())
