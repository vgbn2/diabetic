---
phase: 0.8
plan: 2
wave: 1
depends_on: []
files_modified: 
  - scripts/troubleshooting/infrastructure/verify_schedule.py
  - scripts/troubleshooting/infrastructure/verify_visuals.py
  - scripts/troubleshooting/infrastructure/verify_safety_sync.py
autonomous: true

must_haves:
  truths:
    - "verify_schedule.py crashes loudly rather than softly printing a fail string."
    - "verify_visuals.py crashes loudly if the dashboard image fails to render."
    - "verify_safety_sync.py is purged."
  artifacts:
    - "scripts/troubleshooting/infrastructure/verify_schedule.py"
    - "scripts/troubleshooting/infrastructure/verify_visuals.py"
---

# Plan 0.8.2: Hardening Simulation & UI Troubleshooting

<objective>
Eliminate silent mock failures and redundant synchronous pipelines from the simulation auditing tools to guarantee fail-fast stability.

Purpose: Verification scripts must mirror the async-native core engine. Sync scripts mask race conditions, and prints mask true continuous integration failures.
Output: Hardened scheduling and visualization validation scripts, dropping legacy sync baggage.
</objective>

<context>
Load for context:
- scripts/troubleshooting/infrastructure/verify_schedule.py
- scripts/troubleshooting/infrastructure/verify_visuals.py
- scripts/troubleshooting/infrastructure/verify_safety_sync.py
</context>

<tasks>

<task type="auto">
  <name>Fail-Fast verified schedules</name>
  <files>scripts/troubleshooting/infrastructure/verify_schedule.py</files>
  <action>
    Wrap logic in `async def run_audit()` and run via `asyncio.run()`.
    Add `import sys` and replace `print("STATUS: FAILED")` with explicit `sys.exit(1)`.
    Ensure output formatting uses standard standard `[OK]` and `[X]`.
    AVOID: Any logic that allows the script to exit 0 on a heuristic mismatch.
  </action>
  <verify>python scripts/troubleshooting/infrastructure/verify_schedule.py</verify>
  <done>Exits 1 on condition failure, operates async natively.</done>
</task>

<task type="auto">
  <name>Fail-Fast visualizer</name>
  <files>scripts/troubleshooting/infrastructure/verify_visuals.py</files>
  <action>
    Add `import sys`.
    Replace `print("Error: live_dashboard.png NOT found.")` with `sys.exit(1)`.
    AVOID: Soft printing errors instead of crashing.
  </action>
  <verify>python scripts/troubleshooting/infrastructure/verify_visuals.py</verify>
  <done>If UI rendering fails resulting in no file, it exits 1.</done>
</task>

<task type="auto">
  <name>Purge legacy sync script</name>
  <files>scripts/troubleshooting/infrastructure/verify_safety_sync.py</files>
  <action>
    Delete the file to enforce the async-native Engine Parity requirement.
    AVOID: Leaving it deprecated or unused.
  </action>
  <verify>File no longer exists</verify>
  <done>Codebase is strictly async for safety verification.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] No remaining `print("STATUS: FAILED")` or similar non-crashing logs in these files.
- [ ] `verify_safety_sync.py` is successfully removed.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
