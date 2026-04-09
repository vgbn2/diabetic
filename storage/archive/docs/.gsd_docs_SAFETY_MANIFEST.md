# Bio-Quant Safety Manifest

## 🛡️ MISSION CRITICAL RULES
1. **Never Suppress Critical Alerts**: While a circuit breaker exists for warning-level alerts, critical-level alerts (< 55 mg/dL or > 400 mg/dL) must bypass all dampening.
2. **Fail-Safe Identity**: Every data packet must contain a source identifier to prevent cross-contamination if multiple users are eventually supported.
3. **Signal Quality Guard**: If the Kalman Filter residual exceeds 50 mg/dL (indicating sensor failure), the system must alert for "Sensor Malfunction" instead of displaying erratic glucose.

## ⚠️ RISK MITIGATION
- **API Downtime**: Exponential backoff in `ingestion` ensures we don't spam the server but recover instantly on return.
- **Replay Protection**: The `coordinator` must check timestamps to ensure we aren't alerting on stale data (Physiological Lag vs. Network Lag).
- **Personalization**: Models must be fine-tuned per-user. A "Global Model" is only a starting point.

## 🚑 EMERGENCY PROTOCOL
- If `CRITICAL_HYPO` is triggered:
    1. Send Telegram to User.
    2. Wait 30 seconds for acknowledgement.
    3. If no ack, send Telegram to Caregiver with "EMERGENCY: RESPONSE REQUIRED".
