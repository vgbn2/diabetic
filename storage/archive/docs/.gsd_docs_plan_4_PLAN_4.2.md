---
phase: 4
plan: 2
wave: 2
depends_on: ["Plan 4.1"]
files_modified:
  - src/comms/cli_hud.py
autonomous: true
---

# Plan 4.2: Rich CLI Real-Time HUD

<objective>
Create a premium terminal experience for monitoring the algorithm's performance in real-time.

Output: Terminal-based dashboard.
</objective>

<context>
Load for context:
- .gsd/docs/ARCHITECTURE.md
- src/registry.py
</context>

<tasks>

<task type="auto">
  <name>Implement HUD Console</name>
  <files>src/comms/cli_hud.py</files>
  <action>
    Implement a `ConsoleHUD` class using `rich.live` or `rich.panel`.
    - Components: 
        - [LIVE GLUCOSE] Big number + trend arrow.
        - [PREDICTION] Forecaster's 30-min outlook.
        - [RISK DIAL] LBGI/HBGI visual bars.
        - [STATUS] Last heartbeat, VPN status, Alert timer.
  </action>
  <verify>python src/comms/cli_hud.py (simulated feed)</verify>
  <done>User has a clear, visual overview of their metabolic state</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] HUD updates every 5 minutes without flickering.
- [ ] Layout is responsive to terminal resizing.
</verification>

<success_criteria>
- [ ] Terminal UI provides high-fidelity monitoring.
</success_criteria>
