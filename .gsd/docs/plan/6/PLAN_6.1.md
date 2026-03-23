---
phase: 6
plan: 1
wave: 1
depends_on: ["Plan 5.1"]
files_modified:
  - start.ps1
  - src/comms/cloud_audit.py
autonomous: true
user_setup:
  - service: MongoDB Atlas
    why: "Permanent cloud auditing"
    env_vars:
      - name: MONGO_URI
---

# Plan 6.1: Native Start & Cloud Logging

<objective>
Finalize the production environment for autonomous, 24/7 execution with remote auditing.

Output: Launcher scripts and cloud logging integration.
</objective>

<context>
Load for context:
- .gsd/docs/INFRASTRUCTURE.md
- src/coordinator.py
</context>

<tasks>

<task type="auto">
  <name>Create Windows Launcher</name>
  <files>start.ps1</files>
  <action>
    Write a PowerShell script that:
    - Pulls latest git changes.
    - Activates `.venv`.
    - Checks for `.env` file presence.
    - Launches `src/coordinator.py`.
    - Retries automatically if the process crashes.
  </action>
  <verify>./start.ps1 (in dummy env)</verify>
  <done>System is 'one-click' launchable on Windows</done>
</task>

<task type="auto">
  <name>Implement Cloud Audit Logs</name>
  <files>src/comms/cloud_audit.py</files>
  <action>
    Implement a MongoDB client that pushes every alert (and relevant metabolic context) to a remote collection.
    - Identity: Each log includes `local_timestamp` and `device_id`.
  </action>
  <verify>python -c "from src.comms.cloud_audit import log_alert; ..."</verify>
  <done>Historical performance is audit-protected in the cloud</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Restarting the computer and running `start.ps1` restores the monitor instantly.
- [ ] Alert data appears in the MongoDB dashboard.
</verification>

<success_criteria>
- [ ] System is stable for long-term production use.
</success_criteria>
