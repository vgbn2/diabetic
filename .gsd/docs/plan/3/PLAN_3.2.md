---
phase: 3
plan: 2
wave: 2
depends_on: ["Plan 3.1"]
files_modified:
  - src/coordinator.py
  - src/state_manager.py
autonomous: true
must_haves:
  truths:
    - "System recovers Kalman state and alert timers after intentional crash"
    - "Orchestration loop executes precisely every 5 minutes"
  artifacts:
    - "src/coordinator.py exists as main entry point"
---

# Plan 3.2: Central Coordinator & State Persistence

<objective>
Tie all functional layers into a single, resilient infinite loop.

Output: System main entry point and persistence logic.
</objective>

<context>
Load for context:
- .gsd/docs/ARCHITECTURE.md
- src/config.py
</context>

<tasks>

<task type="auto">
  <name>Implement Main Loop</name>
  <files>src/coordinator.py</files>
  <action>
    Create the `Orchestrator` class.
    - Loop: 1. Fetch → 2. Smooth → 3. Feature Gen → 4. Predict → 5. Check Alert → 6. Notify.
    - Handle logging of every tick to `logs/system.log`.
  </action>
  <verify>python src/coordinator.py --dry-run</verify>
  <done>The 'head' of the system is operational and coordinating all components</done>
</task>

<task type="auto">
  <name>Write State Manager</name>
  <files>src/state_manager.py</files>
  <action>
    Implement JSON persistence for:
    - Last Alert Timestamps (for circuit breaker).
    - Kalman Filter State (to prevent filter reset on restart).
    - HRV Baseline (calculated over last 24h).
  </action>
  <verify>python -c "from src.state_manager import save_state; save_state({'test': 1})"</verify>
  <done>System state survives process restarts</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] KeyboardInterrupt (Ctrl+C) gracefully shuts down and saves state.
- [ ] System automatically picks up the last 12 readings from historical logs on boot.
</verification>

<success_criteria>
- [ ] Coordinator handles the entire pipeline autonomously.
</success_criteria>
