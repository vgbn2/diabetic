# Bio-Quant Risk Discovery (Level 2)

## 🧪 RISK 1: Sensor Artifacts vs. Real Crashes
**Problem**: A "Compression Low" (pressure on sensor during sleep) looks like a hypoglycemic crash.
**Discovery**:
- Compression Lows are characterized by a sudden, non-physiological drop (> 40 mg/dL in 5 mins) followed by a recovery that is equally fast.
- **Solution**: Implement a "Confirmation Window". If a drop is > X rate, the system flags it as "SENS_UNSTABLE" and waits 1 tick before alerting, or checks if Heart Rate correlates (Heart Rate usually rises during real hypoglycemia due to adrenaline).

## 🔋 RISK 2: Power/Process Failure
**Problem**: If the Windows machine restarts, the Kalman Filter loses its "memory" (Velocity), leading to 15-20 minutes of inaccuracy while it re-stabilizes.
**Discovery**:
- The Kalman Filter state $[G, V]$ must be serialized to JSON every 5 minutes.
- **Solution**: On startup, the `Orchestrator` must load the last 3 persistent readings from `states/latest_state.json` to "warm up" the filter before the first live reading.

## 🔗 RISK 4: Backend-Frontend Communication
**Problem**: Maintaining a persistent Websocket between two separate Render/Local instances is complex and prone to disconnection.
**Discovery**:
- Since the CGM updates only every 5 minutes, we don't need real-time streaming.
- **Solution**: Use **Stateless Push**. The Backend acts as a client that POSTs a simple JSON payload to the Frontend's Telegram endpoint exactly once every 5 minutes. No persistent connection required.
