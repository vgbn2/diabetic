"""
Bio-Quant -- Audit DB Inspector (Mission Control)
==================================================
Verifies that the SQLite audit database is reachable and contains records.
Fail-Fast: crashes with sys.exit(1) on any failure.
"""

import asyncio
import sqlite3
import sys
import os

# -- Path Resolution --
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.append(PROJECT_ROOT)

DB_PATH = os.path.join(PROJECT_ROOT, "storage", "audit.db")


async def run_audit():
    print("\n  Bio-Quant -- AUDIT DB INSPECTOR")
    print("  " + "=" * 50)

    # -- Probe 1: File Existence --
    print("\n  [1] Checking DB file exists...")
    if not os.path.exists(DB_PATH):
        print(f"  [X] FAILED: audit.db not found at: {DB_PATH}")
        sys.exit(1)
    print(f"  [OK] DB file found: {DB_PATH}")

    # -- Probe 2: Connection & Row Read --
    print("\n  [2] Connecting and reading audit_logs...")
    try:
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM audit_logs ORDER BY timestamp DESC LIMIT 10;")
        rows = cursor.fetchall()
        conn.close()
    except Exception as e:
        print(f"  [X] FAILED: SQLite error: {e}")
        sys.exit(1)

    # -- Probe 3: Non-Empty Result --
    if not rows:
        print("  [X] FAILED: audit_logs table returned 0 rows. Database may be empty or misconfigured.")
        sys.exit(1)

    print(f"  [OK] Retrieved {len(rows)} row(s) from audit_logs.")
    for row in rows:
        print(f"       {row}")

    print("\n  [PASS] Audit DB inspection: SUCCESS\n")


if __name__ == "__main__":
    try:
        asyncio.run(run_audit())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"\n  [FATAL] Inspector crash: {e}")
        sys.exit(1)
