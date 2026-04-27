---
phase: 17
plan: 4
wave: 2
depends_on: [plan_17_1]
files_modified: ["diabetic/ingestion/cardiac.py", "scripts/ble_scan.py"]
autonomous: false
user_setup:
  - service: hardware
    why: "BLE sensor discovery"
    env_vars:
      - name: HEART_RATE_SENSOR_ADDRESS
        source: "MAC address discovered by ble_scan.py"
---

# Plan 17.4: Hardware Realization (Native BLE Client)

<objective>
Replace mock cardiac data with real-time BLE sensor ingestion.
Purpose: Enable clinical-grade HRV metrics for faint prediction.
Output: Resilient BleakClient implementation and discovery utility.
</objective>

<context>
- diabetic/ingestion/cardiac.py
- diabetic/medical_constants.py
</context>

<tasks>

<task type="auto">
  <name>Create BLE Discovery Utility</name>
  <files>scripts/ble_scan.py</files>
  <action>
    Implement a simple async scanner using `bleak` to list nearby sensor addresses.
  </action>
  <verify>Run `python scripts/ble_scan.py` and see devices.</verify>
  <done>Discovery tool available.</done>
</task>

<task type="auto">
  <name>Implement Resilient BLE Client</name>
  <files>diabetic/ingestion/cardiac.py</files>
  <action>
    Implement `BleakClient` loop with automatic reconnection.
    Add validation to RR intervals before HRV calculation.
    Enforce "Mock Guard": if address is "MOCK", ensure signal quality is flagged.
  </action>
  <verify>Connect to real sensor or verify try/except loop handles disconnected states.</verify>
  <done>Native BLE ingestion active.</done>
</task>

</tasks>

<verification>
After all tasks, verify:
- [ ] Cardiac heart rate updates in real-time when sensor is on.
- [ ] System reverts to "STALE" flag if signal is lost for >15 mins.
</verification>
