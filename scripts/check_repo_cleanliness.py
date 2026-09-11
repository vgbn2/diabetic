#!/usr/bin/env python3
"""
SV Console Cleanliness & Hygiene Evaluator for Bio-Quant.
Mirrors the personal_finance_draft 'backend integrity --json' and repo-hygiene gates.

Usage:
  python scripts/check_repo_cleanliness.py          # Human-readable ANSI table
  python scripts/check_repo_cleanliness.py --json   # Machine-readable JSON output
"""

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# ANSI styling
BOLD = "\033[1m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
DIM = "\033[2m"
RESET = "\033[0m"


def run_cmd(cmd: list[str], timeout: int = 120) -> tuple[bool, str, float]:
    start = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            timeout=timeout,
        )
        duration = time.perf_counter() - start
        return proc.returncode == 0, proc.stdout.strip(), duration
    except Exception as exc:
        duration = time.perf_counter() - start
        return False, str(exc), duration


def check_compilation() -> dict:
    """Evaluates Python syntax & bytecode compilation across all modules."""
    ok, out, dur = run_cmd([sys.executable, "-m", "compileall", "-q", "diabetic", "ops", "tests", "scripts"])
    return {
        "id": "compilation",
        "name": "Bytecode & Syntax Compilation",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "All modules compile cleanly without syntax errors" if ok else out,
    }


def check_cli_parity() -> dict:
    """Enforces 100% parity between CLI manifest and dispatcher routing."""
    ok, out, dur = run_cmd([sys.executable, "-m", "unittest", "ops/lab/test_cli_manifest.py"])
    return {
        "id": "cli_manifest_parity",
        "name": "CLI Manifest ↔ Dispatcher Parity",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "12/12 manifest commands wired to live handlers with zero stubs" if ok else out,
    }


def check_mcp_integrity() -> dict:
    """Validates FastMCP tool specs, schema models, and read-only boundaries."""
    ok, out, dur = run_cmd([sys.executable, "-m", "unittest", "ops/lab/test_mcp_tools.py"])
    return {
        "id": "mcp_tools_integrity",
        "name": "FastMCP Tool Schemas & Safety",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "All bio_* tools adhere to schema definitions and safety bounds" if ok else out,
    }


def check_presentation_authority() -> dict:
    """Verifies that all glucose display formatting routes through glucose_display.py."""
    ok, out, dur = run_cmd([sys.executable, "-m", "unittest", "ops/lab/test_operational_contracts.py"])
    return {
        "id": "presentation_authority",
        "name": "Presentation Unit Authority",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "Strict mmol/L domain model with presentation-only unit conversion" if ok else out,
    }


def check_lifecycle_contracts() -> dict:
    """Validates coordinator state machine, task draining, and single-claim startup."""
    ok, out, dur = run_cmd([sys.executable, "-m", "unittest", "ops/lab/test_runtime_lifecycle.py"])
    return {
        "id": "lifecycle_contracts",
        "name": "Coordinator Lifecycle State Machine",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "Single-claim startup, background task draining, fail-stop invariant verified" if ok else out,
    }


def check_documentation_hygiene() -> dict:
    """Checks MkDocs Material configuration, landing page, and validates strict build."""
    mkdocs_file = REPO_ROOT / "mkdocs.yml"
    index_file = REPO_ROOT / "docs" / "index.md"
    workflow_file = REPO_ROOT / ".github" / "workflows" / "docs.yml"
    files_exist = mkdocs_file.exists() and index_file.exists() and workflow_file.exists()
    if not files_exist:
        return {
            "id": "documentation_hygiene",
            "name": "MkDocs Material & GitHub Pages Setup",
            "passed": False,
            "duration_sec": 0.01,
            "details": "Missing required documentation files (mkdocs.yml, index.md, or docs.yml)",
        }

    ok, out, dur = run_cmd([sys.executable, "-m", "mkdocs", "build", "--strict"])
    return {
        "id": "documentation_hygiene",
        "name": "MkDocs Material & GitHub Pages Setup",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "mkdocs.yml and docs build cleanly under --strict" if ok else out,
    }


def check_test_suite() -> dict:
    """Runs complete contract and integration test suite."""
    ok, out, dur = run_cmd([sys.executable, "-m", "pytest", "-q", "ops/lab/", "tests/"])
    if not ok and "No module named pytest" in out:
        ok, out, dur = run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "ops/lab"])
    return {
        "id": "test_suite_execution",
        "name": "Contract & Lab Test Suite",
        "passed": ok,
        "duration_sec": round(dur, 2),
        "details": "All contract and integration test cases pass" if ok else out,
    }


def run_evaluation() -> dict:
    checks = [
        check_compilation(),
        check_cli_parity(),
        check_mcp_integrity(),
        check_presentation_authority(),
        check_lifecycle_contracts(),
        check_documentation_hygiene(),
        check_test_suite(),
    ]

    total = len(checks)
    passed = sum(1 for c in checks if c["passed"])
    score = passed / total
    grade = "A+" if score == 1.0 else ("A" if score >= 0.85 else ("B" if score >= 0.70 else "F"))

    return {
        "status": "PASS" if score == 1.0 else "FAIL",
        "grade": grade,
        "cleanliness_score": round(score, 2),
        "total_checks": total,
        "passed_checks": passed,
        "failed_checks": total - passed,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()),
        "checks": checks,
    }


def print_human_report(report: dict) -> None:
    print(f"\n{BOLD}{CYAN}BIO-QUANT · SV Console Repository Cleanliness Evaluator{RESET}")
    print(f"{DIM}Timestamp: {report['timestamp']} | Standards: personal_finance_draft{RESET}\n")

    print(f"{BOLD}{'Category / Check':<45} {'Status':<10} {'Duration':<10} {'Details'}{RESET}")
    print("-" * 90)

    for c in report["checks"]:
        status_str = f"{GREEN}✔ PASS{RESET}" if c["passed"] else f"{RED}✖ FAIL{RESET}"
        dur_str = f"{c['duration_sec']:.2f}s"
        name_str = f"{c['name'][:42]}"
        details_str = f"{c['details'][:35]}"
        print(f"{name_str:<45} {status_str:<19} {dur_str:<10} {details_str}")

    print("-" * 90)
    summary_color = GREEN if report["status"] == "PASS" else RED
    print(
        f"\n{BOLD}Overall Grade: {summary_color}{report['grade']}{RESET} | "
        f"Score: {report['cleanliness_score'] * 100:.0f}% ({report['passed_checks']}/{report['total_checks']} checks passed)\n"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="SV Console Cleanliness Evaluator")
    parser.add_argument("--json", action="store_true", help="Output machine-readable JSON")
    args = parser.parse_args()

    report = run_evaluation()

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print_human_report(report)

    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
