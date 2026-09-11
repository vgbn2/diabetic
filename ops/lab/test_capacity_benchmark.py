"""Contracts for the aggregate-only synthetic capacity benchmark."""

import asyncio
import unittest

from scripts.benchmarks.benchmark_runtime_cost import (
    MAX_VIRTUAL_PATIENTS,
    _benchmark_queue_pressure,
    _latency_summary,
    _validate_options,
    run_benchmark,
)


class TestBenchmarkHelpers(unittest.TestCase):
    def test_latency_summary_has_stable_percentile_schema(self):
        summary = _latency_summary([1.0, 2.0, 3.0, 4.0])

        self.assertEqual(summary["samples"], 4)
        self.assertLessEqual(summary["p50_ms"], summary["p95_ms"])
        self.assertLessEqual(summary["p95_ms"], summary["p99_ms"])

    def test_virtual_patient_queues_coalesce_only_readings(self):
        report = asyncio.run(
            _benchmark_queue_pressure(
                virtual_patients=3,
                readings_per_patient=10,
                queue_size=2,
            )
        )

        self.assertEqual(report["produced_readings"], 30)
        self.assertEqual(report["consumed_readings"], 6)
        self.assertEqual(report["coalesced_readings"], 24)
        self.assertEqual(report["dropped_readings"], 0)
        self.assertEqual(report["critical_events_enqueued"], 30)
        self.assertEqual(report["critical_events_consumed"], 30)
        self.assertFalse(report["critical_event_durability_proven"])
        self.assertLessEqual(report["max_queue_depth"], 2)

    def test_resource_limits_reject_unbounded_patient_counts(self):
        with self.assertRaisesRegex(ValueError, "virtual_patients"):
            _validate_options(
                iterations=1,
                virtual_patients=MAX_VIRTUAL_PATIENTS + 1,
                process_workers=0,
                torch_threads=1,
            )


class TestBenchmarkReport(unittest.TestCase):
    def test_report_is_synthetic_and_not_capacity_qualification(self):
        report = asyncio.run(
            run_benchmark(
                iterations=5,
                virtual_patients=3,
                process_workers=0,
                torch_threads=1,
                batch_sizes=(1,),
            )
        )

        self.assertTrue(report["metadata"]["synthetic_only"])
        self.assertFalse(report["metadata"]["capacity_qualification"])
        self.assertFalse(report["metadata"]["clinical_data_accessed"])
        self.assertGreater(report["model"]["parameter_count"], 0)
        self.assertGreater(report["model"]["parameter_bytes"], 0)
        self.assertIn("p99_ms", report["inference"]["batch_1"])
        self.assertIn("p99_ms", report["horizons"])
        self.assertIsNone(report["event_loop"]["process_isolated_cpu_work"])
        self.assertEqual(report["virtual_patient_pressure"]["virtual_patients"], 3)
        self.assertGreater(report["resources"]["rss_bytes"], 0)


if __name__ == "__main__":
    unittest.main()
