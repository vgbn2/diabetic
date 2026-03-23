---
phase: 3
plan: 1
wave: 1
depends_on: ["Plan 2.2"]
files_modified:
  - src/alert_engine/decision_matrix.py
  - src/alert_engine/circuit_breaker.py
autonomous: true
must_haves:
  truths:
    - "Alerts are triggered for Hypo Crashing (Rate + Prediction)"
    - "Alerts are triggered for Hyper Fainting (Glucose + HRV)"
  artifacts:
    - "src/alert_engine/decision_matrix.py exists"
---

# Plan 3.1: Bimodal Alert Guard

<objective>
Implement the safety logic that monitors both current risk and future danger to prevent loss of consciousness.

Output: Alert decision engine.
</objective>

<context>
Load for context:
- .gsd/docs/SPEC.md
- .gsd/docs/SAFETY_MANIFEST.md
- src/registry.py
</context>

<tasks>

<task type="auto">
  <name>Implement Decision Matrix</name>
  <files>src/alert_engine/decision_matrix.py</files>
  <action>
    Implement Bimodal logic:
    - `CRITICAL_HYPO`: G < 55.
    - `WARNING_HYPO`: Predict_30m < 70 AND Velocity < -1.5.
    - `FAINT_RISK`: G > 300 AND HRV < 0.7 * Baseline.
    - `CRITICAL_HYPER`: G > 350.

    ```python
    def evaluate_risk(state: MetabolicSnapshot):
        if state.glucose.value < 55:
            return "CRITICAL_HYPO"
        if state.predict_30m < 70 and state.velocity < -1.5:
            return "WARNING_HYPO"
        if state.glucose.value > 300 and state.hrv < state.hrv_baseline * 0.7:
            return "FAINT_RISK"
        return "STABLE"
    ```
  </action>
  <verify>python tests/test_alerts.py</verify>
  <done>All safety thresholds are correctly implemented</done>
</task>

<task type="auto">
  <name>Implement Circuit Breaker</name>
  <files>src/alert_engine/circuit_breaker.py</files>
  <action>
    Logic to prevent "Alert Storms".
    - Rule: Re-arm Warning alerts only after 15 mins.
    - Rule: Critical alerts bypass breaker (always notify).
  </action>
  <verify>python -c "from src.alert_engine.circuit_breaker import Breaker; ..."</verify>
  <done>Warning alert fatigue is mitigated while critical safety is maintained</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Warning Hypo triggers alert without waiting for the actual crash.
- [ ] Repeated calls to Caution Hyper do not result in multiple alerts.
</verification>

<success_criteria>
- [ ] Alerting logic matches the SAFETY_MANIFEST precisely.
</success_criteria>
