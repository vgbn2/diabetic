---
phase: 0.8
plan: 1
wave: 1
depends_on: []
files_modified: 
  - scripts/check_audit_db.py
  - scripts/troubleshooting/infrastructure/test_supabase.py
autonomous: true

must_haves:
  truths:
    - "check_audit_db.py fails loudly if SQLite fails to return rows."
    - "test_mongodb.py uses pymongo/motor without masking network exceptions."
  artifacts:
    - "scripts/check_audit_db.py"
    - "scripts/troubleshooting/infrastructure/test_mongodb.py"
---

# Plan 0.8.1: Hardening Database Troubleshooting Scripts

<objective>
Refactor base database validation scripts to align with the Fail-Fast Auditing protocol, enforcing strict `sys.exit(1)` and asyncio loop compliance.

Purpose: "Mission Control" tools must never mask failure or return a friendly error warning when databases are inaccessible.
Output: Two async-native, fail-fast SQL/NoSQL testing scripts.
</objective>

<context>
Load for context:
- scripts/check_audit_db.py
- scripts/troubleshooting/infrastructure/test_supabase.py
- diabetic/registry.py
</context>

<tasks>

<task type="auto">
  <name>Hard Fail check_audit_db.py</name>
  <files>scripts/check_audit_db.py</files>
  <action>
    Wrap logic in `async def run_audit()`.
    Require explicit project root path resolution using `sys.path.append()`.
    Replace simple `except Exception as e: print` with `sys.exit(1)` crashing.
    If no rows are fetched, also crash with `sys.exit(1)`.
    AVOID: Soft printing errors instead of crashing.
  </action>
  <verify>python scripts/check_audit_db.py returns standard or exits 1 on failure</verify>
  <done>Script fails via sys.exit(1) if audit.db fails to read.</done>
</task>

<task type="auto">
  <name>Async Motor test_mongodb.py</name>
  <files>scripts/troubleshooting/infrastructure/test_mongodb.py</files>
  <action>
    Create script to probe MongoDB using `motor.motor_asyncio`.
    Wrap in `async def run_audit()`.
    Perform explicit `ping` and `inserted_id` verification.
    AVOID: masking connection failures or using sync `pymongo` without an event loop.
  </action>
  <verify>python scripts/troubleshooting/infrastructure/test_mongodb.py</verify>
  <done>Script crashes loudly on MongoDB auth/network errors.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Both scripts run under `asyncio.run()`.
- [ ] Both scripts evaluate connectivity rather than just object initialization.
</verification>

<success_criteria>
- [ ] All tasks verified
- [ ] Must-haves confirmed
</success_criteria>
