"""Synthetic runtime-cost characterization for architecture capacity planning.

This benchmark never reads configured providers, databases, archives, or patient
identifiers. Results describe one host and invocation only; they are not clinical
or multi-tenant qualification evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import multiprocessing
import os
import platform
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import numpy as np
import psutil
import torch

from diabetic.ml_engine.convolutional_layer import CNNConfig, DiabeticCNN
from diabetic.ml_engine.forecast import build_horizons
from diabetic.ml_engine.oracle import BasalOracle
from diabetic.ml_engine.twin import DigitalTwin
from diabetic.registry import GlucoseReading, MetabolicSnapshot

_WORKER_MODEL: DiabeticCNN | None = None
_LOGICAL_CPUS = max(1, os.cpu_count() or 1)
MAX_ITERATIONS = 2_000
MAX_VIRTUAL_PATIENTS = 500
MAX_PROCESS_WORKERS = min(4, _LOGICAL_CPUS)


def _validate_options(
    *,
    iterations: int,
    virtual_patients: int,
    process_workers: int,
    torch_threads: int,
) -> None:
    bounds = {
        "iterations": (iterations, 1, MAX_ITERATIONS),
        "virtual_patients": (virtual_patients, 1, MAX_VIRTUAL_PATIENTS),
        "process_workers": (process_workers, 0, MAX_PROCESS_WORKERS),
        "torch_threads": (torch_threads, 1, _LOGICAL_CPUS),
    }
    invalid = [
        f"{name} must be between {minimum} and {maximum}"
        for name, (value, minimum, maximum) in bounds.items()
        if not minimum <= value <= maximum
    ]
    if process_workers and process_workers * torch_threads > _LOGICAL_CPUS:
        invalid.append(
            "process_workers * torch_threads must not exceed logical CPU count"
        )
    if invalid:
        raise ValueError("; ".join(invalid))


def _configure_torch_threads(thread_count: int) -> None:
    torch.set_num_threads(thread_count)
    try:
        torch.set_num_interop_threads(1)
    except RuntimeError:
        # PyTorch permits this setting only before inter-op work starts.
        pass


def _initialize_worker(thread_count: int) -> None:
    global _WORKER_MODEL
    _configure_torch_threads(thread_count)
    _WORKER_MODEL = DiabeticCNN(config=CNNConfig()).eval()


def _worker_infer(payload: tuple[int, int]) -> float:
    batch_size, iterations = payload
    if _WORKER_MODEL is None:
        raise RuntimeError("inference worker model is not initialized")
    temporal = torch.zeros(batch_size, 2, 30)
    static = torch.zeros(batch_size, 15)
    result = None
    with torch.inference_mode():
        for _ in range(iterations):
            result = _WORKER_MODEL(temporal, static)
    return float(result.sum()) if result is not None else 0.0


def _worker_payload_size(payload: bytes) -> int:
    return len(payload)


def _latency_summary(samples_ms: list[float]) -> dict[str, float | int]:
    if not samples_ms:
        return {"samples": 0, "p50_ms": 0.0, "p95_ms": 0.0, "p99_ms": 0.0}
    values = np.asarray(samples_ms, dtype=np.float64)
    return {
        "samples": len(samples_ms),
        "p50_ms": round(float(np.percentile(values, 50)), 6),
        "p95_ms": round(float(np.percentile(values, 95)), 6),
        "p99_ms": round(float(np.percentile(values, 99)), 6),
    }


def _synthetic_history(points: int = 30) -> list[MetabolicSnapshot]:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    history = []
    for index in range(points):
        value = 7.0 + 0.2 * np.sin(index / 4.0)
        history.append(
            MetabolicSnapshot(
                glucose=GlucoseReading(
                    timestamp=start + timedelta(minutes=index * 5),
                    value=float(value),
                    trend="Flat",
                    source="synthetic_benchmark",
                ),
                filtered_value=float(value),
                velocity=0.01,
                acceleration=0.0,
            )
        )
    return history


def _benchmark_inference(
    model: DiabeticCNN, batch_size: int, iterations: int
) -> dict[str, float | int]:
    temporal = torch.zeros(batch_size, 2, 30)
    static = torch.zeros(batch_size, 15)
    samples = []
    with torch.inference_mode():
        for _ in range(10):
            model(temporal, static)
        for _ in range(iterations):
            started = time.perf_counter_ns()
            model(temporal, static)
            samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    summary = _latency_summary(samples)
    elapsed_seconds = sum(samples) / 1000.0
    summary["samples_per_second"] = round(
        batch_size * iterations / elapsed_seconds, 2
    ) if elapsed_seconds else 0.0
    return summary


def _benchmark_horizons(iterations: int) -> dict[str, float | int]:
    history = _synthetic_history()
    twin = DigitalTwin()
    oracle = BasalOracle()
    oracle.params = np.array([1.0, 0.0, 7.0])
    now = datetime(2026, 1, 2, tzinfo=timezone.utc)
    samples = []
    last_result = None
    for _ in range(iterations):
        started = time.perf_counter_ns()
        last_result = build_horizons(twin, oracle, history, now=now)
        samples.append((time.perf_counter_ns() - started) / 1_000_000.0)
    summary = _latency_summary(samples)
    summary["h4_points"] = len(last_result["h4"]) if last_result else 0
    summary["h1d_points"] = len(last_result["h1d"]) if last_result else 0
    return summary


def _run_local_inference(model: DiabeticCNN, iterations: int) -> None:
    temporal = torch.zeros(1, 2, 30)
    static = torch.zeros(1, 15)
    with torch.inference_mode():
        for _ in range(iterations):
            model(temporal, static)


async def _measure_event_loop_lag(
    action: Callable[[], None] | None = None,
    awaitable_action: Callable[[], object] | None = None,
    interval_seconds: float = 0.002,
) -> dict[str, float | int]:
    stop = asyncio.Event()
    lags = []

    async def ticker() -> None:
        expected = time.perf_counter() + interval_seconds
        while not stop.is_set():
            await asyncio.sleep(interval_seconds)
            current = time.perf_counter()
            lags.append(max(0.0, (current - expected) * 1000.0))
            expected = current + interval_seconds

    ticker_task = asyncio.create_task(ticker())
    await asyncio.sleep(interval_seconds * 2)
    started = time.perf_counter()
    if action is not None:
        action()
    elif awaitable_action is not None:
        await awaitable_action()
    elapsed_ms = (time.perf_counter() - started) * 1000.0
    await asyncio.sleep(interval_seconds * 2)
    stop.set()
    await ticker_task
    summary = _latency_summary(lags)
    summary["workload_ms"] = round(elapsed_ms, 3)
    return summary


async def _benchmark_queue_pressure(
    virtual_patients: int,
    readings_per_patient: int,
    queue_size: int,
) -> dict[str, float | int]:
    queues = {
        patient: asyncio.Queue(maxsize=queue_size)
        for patient in range(virtual_patients)
    }
    critical_events = asyncio.Queue()
    coalesced = 0
    dropped = 0
    max_depth = 0
    started = time.perf_counter()

    for sequence in range(readings_per_patient):
        for patient, queue in queues.items():
            event = (time.perf_counter(), patient, sequence)
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                queue.get_nowait()
                queue.task_done()
                queue.put_nowait(event)
                coalesced += 1
            max_depth = max(max_depth, queue.qsize())
            critical_events.put_nowait((patient, sequence))

    queue_ages_ms = []
    consumed = 0
    for queue in queues.values():
        while not queue.empty():
            enqueued_at, _, _ = queue.get_nowait()
            queue_ages_ms.append((time.perf_counter() - enqueued_at) * 1000.0)
            consumed += 1
            queue.task_done()

    critical_produced = critical_events.qsize()
    critical_consumed = 0
    while not critical_events.empty():
        critical_events.get_nowait()
        critical_consumed += 1
        critical_events.task_done()

    elapsed = time.perf_counter() - started
    age_summary = _latency_summary(queue_ages_ms)
    produced_readings = virtual_patients * readings_per_patient
    return {
        "virtual_patients": virtual_patients,
        "readings_per_patient": readings_per_patient,
        "queue_size_per_patient": queue_size,
        "produced_readings": produced_readings,
        "consumed_readings": consumed,
        "coalesced_readings": coalesced,
        "dropped_readings": dropped,
        "critical_events_enqueued": critical_produced,
        "critical_events_consumed": critical_consumed,
        "critical_event_durability_proven": False,
        "max_queue_depth": max_depth,
        "throughput_events_per_second": round(
            (produced_readings + critical_produced) / elapsed, 2
        ) if elapsed else 0.0,
        "queue_age": age_summary,
    }


async def run_benchmark(
    *,
    iterations: int,
    virtual_patients: int,
    process_workers: int,
    torch_threads: int,
    batch_sizes: tuple[int, ...] = (1, 32),
) -> dict:
    _validate_options(
        iterations=iterations,
        virtual_patients=virtual_patients,
        process_workers=process_workers,
        torch_threads=torch_threads,
    )
    _configure_torch_threads(torch_threads)
    process = psutil.Process()
    cpu_start = process.cpu_times()
    wall_start = time.perf_counter()
    model = DiabeticCNN(config=CNNConfig()).eval()
    parameter_count = sum(parameter.numel() for parameter in model.parameters())
    parameter_bytes = sum(
        parameter.numel() * parameter.element_size()
        for parameter in model.parameters()
    )

    inference = {
        f"batch_{batch_size}": _benchmark_inference(
            model, batch_size, iterations
        )
        for batch_size in batch_sizes
    }
    horizons = _benchmark_horizons(iterations)
    loop_iterations = max(100, iterations * 5)
    in_loop = await _measure_event_loop_lag(
        action=lambda: _run_local_inference(model, loop_iterations)
    )

    process_pool = {
        "enabled": False,
        "workers": 0,
        "start_method": None,
        "inference_event_loop": None,
        "serialization_roundtrip": None,
    }
    if process_workers > 0:
        context = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=process_workers,
            mp_context=context,
            initializer=_initialize_worker,
            initargs=(torch_threads,),
        ) as pool:
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(pool, _worker_infer, (1, 1))
            isolated = await _measure_event_loop_lag(
                awaitable_action=lambda: loop.run_in_executor(
                    pool, _worker_infer, (1, loop_iterations)
                )
            )
            payload = bytes(64 * 1024)
            serialization_samples = []
            for _ in range(max(5, min(iterations, 50))):
                started = time.perf_counter_ns()
                size = await loop.run_in_executor(
                    pool, _worker_payload_size, payload
                )
                if size != len(payload):
                    raise RuntimeError("process-pool payload size mismatch")
                serialization_samples.append(
                    (time.perf_counter_ns() - started) / 1_000_000.0
                )
            process_pool = {
                "enabled": True,
                "workers": process_workers,
                "start_method": "spawn",
                "inference_event_loop": isolated,
                "serialization_roundtrip": {
                    "payload_bytes": len(payload),
                    **_latency_summary(serialization_samples),
                },
            }

    queue_pressure = await _benchmark_queue_pressure(
        virtual_patients=virtual_patients,
        readings_per_patient=12,
        queue_size=4,
    )
    elapsed = time.perf_counter() - wall_start
    cpu_end = process.cpu_times()
    cpu_seconds = (
        cpu_end.user + cpu_end.system - cpu_start.user - cpu_start.system
    )
    memory = process.memory_info()

    return {
        "metadata": {
            "synthetic_only": True,
            "capacity_qualification": False,
            "clinical_data_accessed": False,
            "note": "One-host characterization; not clinical or scale proof.",
        },
        "runtime": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "logical_cpu_count": os.cpu_count(),
            "torch_threads": torch_threads,
            "process_workers": process_workers,
        },
        "model": {
            "parameter_count": parameter_count,
            "parameter_bytes": parameter_bytes,
        },
        "inference": inference,
        "horizons": horizons,
        "event_loop": {
            "in_process_cpu_work": in_loop,
            "process_isolated_cpu_work": process_pool["inference_event_loop"],
        },
        "process_pool": process_pool,
        "virtual_patient_pressure": queue_pressure,
        "resources": {
            "wall_seconds": round(elapsed, 3),
            "main_process_cpu_seconds": round(cpu_seconds, 3),
            "main_process_cpu_percent_of_one_core": round(
                cpu_seconds / elapsed * 100.0, 2
            ) if elapsed else 0.0,
            "rss_bytes": memory.rss,
            "main_process_threads": process.num_threads(),
        },
    }


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run aggregate-only synthetic Bio-Quant runtime benchmarks."
    )
    parser.add_argument("--iterations", type=int, default=200)
    parser.add_argument("--virtual-patients", type=int, default=50)
    parser.add_argument("--process-workers", type=int, default=1)
    parser.add_argument("--torch-threads", type=int, default=1)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    try:
        _validate_options(
            iterations=args.iterations,
            virtual_patients=args.virtual_patients,
            process_workers=args.process_workers,
            torch_threads=args.torch_threads,
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    report = asyncio.run(
        run_benchmark(
            iterations=args.iterations,
            virtual_patients=args.virtual_patients,
            process_workers=args.process_workers,
            torch_threads=args.torch_threads,
        )
    )
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
