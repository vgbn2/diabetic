================================================================================
  BIO-QUANT — REFINED DEVELOPMENT PLAN
  Hyperglycemia Faint Predictor + Hypoglycemia Crash Detector
================================================================================
  Written against the actual codebase. Every task references real files.
================================================================================


════════════════════════════════════════════════════════════════════════════════
  CURRENT STATE — WHAT'S ALREADY WORKING
════════════════════════════════════════════════════════════════════════════════

  ✅ Core inference pipeline runs end-to-end (simulation mode confirmed)
  ✅ UKF (Unscented Kalman Filter) with Bergman Minimal Model — medically correct
  ✅ XGBoost model trained and loaded (xgboost_v1.json)
  ✅ Dynamic Stress Index (DSI) from HRV
  ✅ Circuit breaker prevents predictions on stale data
  ✅ Async event bus architecture (3 parallel workers)
  ✅ Nightscout client for real CGM data
  ✅ Alert logic for all 5 states: STABLE, CAUTION, CRITICAL_HYPO,
     WARNING_HYPER, FAINT_RISK
  ✅ Digital Twin (BergmanDigitalTwin) for synthetic training data
  ✅ Radar physics simulation (UWB radar for contactless HR)
  ✅ Interaction agent powered by Groq LLaMA-3

  What's missing: Telegram delivery, chart visualization,
  live HRV source, retraining pipeline, crash scenario testing.


════════════════════════════════════════════════════════════════════════════════
  PHASE 1 — MAKE ALERTS ACTUALLY REACH THE USER  (Priority: Critical)
  Estimated time: 1-2 days
════════════════════════════════════════════════════════════════════════════════

  TASK 1.1 — Wire Telegram into the alert controller
  File: src/alerts/controller.py

  The alert service currently only logs and prints. Add actual delivery:

    import requests

    class MetabolicAlertingService:
        def __init__(self, ...):
            self.token = os.getenv('TELEGRAM_BOT_TOKEN')
            self.chat_id = os.getenv('TELEGRAM_CHAT_ID')
            self.caregiver_id = os.getenv('TELEGRAM_CAREGIVER_ID')

        def _send_telegram(self, chat_id, message):
            if not self.token or not chat_id:
                return
            try:
                requests.post(
                    f'https://api.telegram.org/bot{self.token}/sendMessage',
                    json={'chat_id': chat_id, 'text': message, 'parse_mode': 'HTML'},
                    timeout=5
                )
            except Exception:
                pass  # NEVER let Telegram failure crash medical inference

        def alert(self, status, message):
            if status == 'CRITICAL_HYPO':
                msg = f'🚨 <b>CRITICAL HYPO</b>\n{message}\n\nEat fast-acting carbs NOW.'
                self._send_telegram(self.chat_id, msg)
                self._send_telegram(self.caregiver_id, msg)  # also alert caregiver

            elif status == 'FAINT_RISK':
                msg = f'⚠️ <b>FAINT RISK</b>\n{message}\n\nSit down. Hydrate. Check ketones.'
                self._send_telegram(self.chat_id, msg)
                self._send_telegram(self.caregiver_id, msg)

            elif status in ('WARNING_HYPER', 'STRESS_DEVIATION', 'CAUTION'):
                msg = f'⚡ <b>{status}</b>\n{message}'
                self._send_telegram(self.chat_id, msg)

  TASK 1.2 — Create .env file
  File: .env (in hyperglycemia-faint-predictor/)

    NIGHTSCOUT_URL=
    NIGHTSCOUT_API_SECRET=
    TELEGRAM_BOT_TOKEN=
    TELEGRAM_CHAT_ID=
    TELEGRAM_CAREGIVER_ID=
    GROQ_API_KEY=

  TASK 1.3 — Test Telegram before trusting it with medical alerts

    python -c "
    import requests, os
    from dotenv import load_dotenv
    load_dotenv()
    r = requests.post(
        f'https://api.telegram.org/bot{os.getenv(\"TELEGRAM_BOT_TOKEN\")}/sendMessage',
        json={'chat_id': os.getenv('TELEGRAM_CHAT_ID'), 'text': 'Bio-Quant online.'}
    )
    print(r.json())
    "

    Expected: {"ok": true, ...}
    If not ok — fix .env before proceeding.


════════════════════════════════════════════════════════════════════════════════
  PHASE 2 — FIX THE SIMULATION TO ACTUALLY TRIGGER ALERTS  (Priority: High)
  Estimated time: 1 day
════════════════════════════════════════════════════════════════════════════════

  PROBLEM: Current simulation injects glucose 110→130→150 (rising).
  The model predicts ~85 mg/dL and returns STABLE. No alert fires.
  This makes it impossible to verify the alert system works.

  TASK 2.1 — Add crash scenario to simulation
  File: main.py

  Add a second scenario that simulates a hypoglycemic crash:

    async def run_simulation_crash_test(engine):
        """Simulates a hypoglycemic crash — should trigger CRITICAL_HYPO."""
        logger.info("Starting Crash Scenario Test...")
        now = datetime.now()

        # Step 1: Inject stress (HRV drops — reduces insulin sensitivity)
        for i in range(3):
            await engine.event_bus.put(BiometricReading(
                timestamp=now + timedelta(seconds=i*2),
                rmssd=12.0,  # critically low HRV
                source="Simulation"
            ))
            await asyncio.sleep(0.1)

        # Step 2: Inject falling glucose
        for i, sgv in enumerate([85, 72, 61, 54]):
            await engine.event_bus.put(GlucoseReading(
                timestamp=now + timedelta(minutes=i*5),
                sgv=sgv,
                direction="DoubleDown",
                lag_minutes=15
            ))
            await asyncio.sleep(0.5)

        await asyncio.sleep(2)

  Add to main():
    elif mode == "crash":
        worker_task = asyncio.create_task(engine.inference_worker())
        await run_simulation_crash_test(engine)
        worker_task.cancel()

  Run with:
    python main.py crash

  Expected output:
    [ASYNC-ALERT] [CRITICAL_HYPO] Metabolic crash forecast: ~52 mg/dL in T+30m.

  TASK 2.2 — Add faint risk scenario

    async def run_simulation_faint_test(engine):
        """Simulates hyperglycemic faint risk — should trigger FAINT_RISK."""
        now = datetime.now()

        # High stress
        for i in range(5):
            await engine.event_bus.put(BiometricReading(
                timestamp=now + timedelta(seconds=i*2),
                rmssd=8.0,  # extreme stress
                source="Simulation"
            ))

        # Critically high glucose
        for i, sgv in enumerate([280, 310, 340, 370]):
            await engine.event_bus.put(GlucoseReading(
                timestamp=now + timedelta(minutes=i*5),
                sgv=sgv,
                direction="SingleUp",
                lag_minutes=15
            ))
            await asyncio.sleep(0.5)

        await asyncio.sleep(2)

  Run with:
    python main.py faint

  Expected output:
    [ASYNC-ALERT] [FAINT_RISK] Critical Hyperglycemia (370) with stress surge.


════════════════════════════════════════════════════════════════════════════════
  PHASE 3 — FIX THE MOCK HRV FOR LIVE MODE  (Priority: High)
  Estimated time: half a day
════════════════════════════════════════════════════════════════════════════════

  PROBLEM: In live mode, radar_worker generates random HRV between 30-60 ms.
  This causes DSI to fluctuate randomly and fires false alerts constantly.
  File: src/coordinator.py

  TASK 3.1 — Use a stable baseline until real hardware is connected

    async def radar_worker(self, mock: bool = True):
        logger.info("Biometric Worker Started")
        while True:
            if mock:
                # Use stable resting baseline — not random
                # Replace with real wearable data when available
                hrv = BiometricReading(
                    timestamp=datetime.now(),
                    rmssd=55.0,  # healthy adult resting baseline
                    source="Mock_Stable"
                )
                await self.event_bus.put(hrv)
                await asyncio.sleep(30)  # update every 30 seconds, not 10

  TASK 3.2 — Document hardware integration path
  When a real wearable (Apple Watch, Garmin, Polar H10) is available:
  - Apple Watch → HealthKit → Apple Health Export → parse XML → feed to event bus
  - Polar H10 → BLE SDK → direct RMSSD stream → feed to event bus
  - Any wearable with HRV API → HTTP polling → feed to event bus

  The event bus accepts any BiometricReading regardless of source.
  The source field just needs to be updated for logging.


════════════════════════════════════════════════════════════════════════════════
  PHASE 4 — VISUALIZATION DASHBOARD  (Priority: Medium)
  Estimated time: 2-3 days
════════════════════════════════════════════════════════════════════════════════

  TASK 4.1 — Add Flask API to serve chart data
  New file: src/api.py

    from flask import Flask, jsonify
    from flask_cors import CORS
    import time

    app = Flask(__name__)
    CORS(app)

    # These will be set by coordinator on startup
    shared_engine = None

    @app.route('/api/state')
    def get_state():
        if not shared_engine:
            return jsonify({'error': 'Engine not initialized'})

        hrv_data = []
        glucose_data = []

        for r in shared_engine.hrv_buffer[-50:]:
            hrv_data.append({
                'time': int(r.timestamp.timestamp()),
                'value': r.rmssd
            })

        for r in shared_engine.cgm_buffer[-50:]:
            glucose_data.append({
                'time': int(r.timestamp.timestamp()),
                'value': r.sgv
            })

        return jsonify({
            'hrv': hrv_data,
            'glucose': glucose_data,
            'dsi': shared_engine.stress_tracker.get_current_dsi(),
            'status': 'STABLE'  # pull from last inference result
        })

    def start_api():
        app.run(port=5000, debug=False, use_reloader=False)

  Install: pip install flask flask-cors

  TASK 4.2 — Create chart.html
  Shows three panels:
    - Glucose over time (candlestick — 5-minute OHLCV aggregation)
    - HRV over time (line chart)
    - DSI gauge (0.5 = relaxed, 3.0 = extreme stress)

  Use lightweight-charts (same as Terminus) for consistency.
  Color coding:
    - Glucose < 70:  red zone
    - Glucose 70-180: green zone
    - Glucose > 180: amber zone
    - Glucose > 300: red zone

  TASK 4.3 — Run API and chart together
  In main.py live mode, start Flask in a background thread:

    import threading
    from src.api import start_api, shared_engine as api_engine

    # Before starting async workers
    api_thread = threading.Thread(target=start_api, daemon=True)
    api_thread.start()


════════════════════════════════════════════════════════════════════════════════
  PHASE 5 — RETRAIN THE MODEL ON REAL DATA  (Priority: Medium)
  Estimated time: 1-2 days after collecting data
════════════════════════════════════════════════════════════════════════════════

  The current xgboost_v1.json was trained on OhioT1DM dataset — a public
  dataset of Type 1 diabetic patients. This is a good starting point but
  glucose dynamics are highly personal.

  TASK 5.1 — Generate synthetic training data using Digital Twin
  File: src/simulation/digital_twin.py (already implemented)

    from src.simulation.digital_twin import BergmanDigitalTwin

    twin = BergmanDigitalTwin()
    df = twin.generate_dataset(days=30)

    # Create target column: glucose 30 minutes later
    df['sgv_target_30m'] = df['sgv'].shift(-6)  # 6 * 5min = 30min
    df = df.dropna()
    df.to_parquet('data/synthetic_30day.parquet')

  TASK 5.2 — Retrain XGBoost on synthetic data
  File: src/train_model.py (already exists, may need updating)

    from src.models.xgboost_predictor import XGBoostPredictor
    import pandas as pd

    df = pd.read_parquet('data/synthetic_30day.parquet')
    model = XGBoostPredictor()
    model.train(df, target_col='sgv_target_30m')
    model.save('models/xgboost_v2.json')

  TASK 5.3 — Validate before deploying
  Run the validation suite:

    python src/validation_suite.py

  Check both PASSED before switching to the new model.

  TASK 5.4 — Personal calibration (when Nightscout data is available)
  After 2 weeks of live data collection:
  - Export from Nightscout
  - Fine-tune the XGBoost model on personal data
  - The personal model will outperform the generic one significantly


════════════════════════════════════════════════════════════════════════════════
  PHASE 6 — INTERACTION AGENT (Already built, needs Groq key)
  Estimated time: half a day
════════════════════════════════════════════════════════════════════════════════

  The UserInteractionAgent in src/agents/interaction_agent.py is complete.
  It uses Groq LLaMA-3 to ask context questions during ambiguous alerts.

  Example flow:
    Alert fires: STRESS_DEVIATION
    Agent asks via Telegram: "Your glucose is rising with high stress.
                              Did you just eat, or are you feeling anxious?"
    User replies: "Just had lunch"
    Agent logs: meal event, adjusts COB estimate, suppresses further alerts

  TASK 6.1 — Get Groq API key (free at console.groq.com)
  Add to .env: GROQ_API_KEY=your_key_here

  TASK 6.2 — Wire agent into coordinator
  File: src/coordinator.py

  After alert fires, call the agent:
    from .agents.interaction_agent import UserInteractionAgent

    self.agent = UserInteractionAgent()

    # In _sync_and_predict():
    if status != 'STABLE':
        question = self.agent.process_alert(status, dsi)
        if question:
            self.alert_service._send_telegram(
                self.alert_service.chat_id,
                f"🤖 {question}"
            )

  TASK 6.3 — Handle user reply (Telegram webhook or polling)
  When user replies to the bot, route the message to the agent:
    self.agent.handle_response(user_message)

  This upgrades the system from one-way alerts to a two-way
  medical dialogue — the system asks, user confirms, system adapts.


════════════════════════════════════════════════════════════════════════════════
  PHASE 7 — NIGHTSCOUT SETUP (For real CGM data)
  Estimated time: 1 day
════════════════════════════════════════════════════════════════════════════════

  Nightscout is a free, open-source CGM remote monitoring system.
  It acts as the bridge between the CGM sensor and Bio-Quant.

  Data flow:
    CGM Sensor (Dexcom/Libre) → Nightscout → Bio-Quant

  Options for hosting Nightscout:
    1. T1Pal — easiest, managed hosting, ~$12/month
    2. Railway.app — free tier, deploy from GitHub
    3. Fly.io — free tier
    4. Self-hosted on a Raspberry Pi

  Once hosted, add to .env:
    NIGHTSCOUT_URL=https://yourname.up.railway.app
    NIGHTSCOUT_API_SECRET=your_secret

  Test the connection:
    python src/nightscout_client.py

  Expected: prints last 3 glucose readings with timestamps.


════════════════════════════════════════════════════════════════════════════════
  PHASE 8 — HARDWARE (Future — Phase 2 in architecture doc)
  Estimated time: months, requires electronics knowledge
════════════════════════════════════════════════════════════════════════════════

  The architecture document describes a non-invasive 2.4 GHz CSRR
  (Complementary Split Ring Resonator) microwave sensor to replace
  patch CGMs. The physics engine (src/physics/dielectric_engine.py,
  src/physics/radar_physics.py) and radar processor
  (src/ingestion/radar.py) are already implemented in simulation.

  This is genuinely cutting-edge research — measuring dielectric
  properties of blood to infer glucose concentration non-invasively.

  For MVP: skip this entirely. Use Nightscout + any CGM sensor.
  For Phase 2: integrate a UWB radar module (Novelda X4 or similar)
  via USB, replace mock radar_worker with real hardware stream.

  The code is already written for it. The hardware just needs to be
  connected and calibrated.


════════════════════════════════════════════════════════════════════════════════
  EXECUTION ORDER — DO THESE IN SEQUENCE
════════════════════════════════════════════════════════════════════════════════

  Week 1:
    Day 1: Phase 1 — Telegram integration + .env setup
    Day 2: Phase 2 — Fix simulation scenarios, verify all 5 alert states fire
    Day 3: Phase 3 — Fix mock HRV, run stable live simulation
    Day 4-5: Phase 4 — Chart dashboard

  Week 2:
    Day 1: Phase 6 — Groq agent + Telegram two-way dialogue
    Day 2: Phase 7 — Nightscout setup if CGM hardware available
    Day 3-5: Phase 5 — Retrain model on synthetic data, validate

  Week 3+:
    Collect real data. Fine-tune model on personal glucose patterns.
    Phase 8 when ready for hardware.


════════════════════════════════════════════════════════════════════════════════
  QUICK REFERENCE — COMMANDS
════════════════════════════════════════════════════════════════════════════════

  Install dependencies:
    pip install -r requirements.txt
    pip install scipy flask flask-cors

  Run simulation (current — stable, no alert):
    python main.py simulation

  Run crash test (after Phase 2 — triggers CRITICAL_HYPO):
    python main.py crash

  Run faint test (after Phase 2 — triggers FAINT_RISK):
    python main.py faint

  Run live mode (after Phase 1 and 7):
    python main.py live

  Test Telegram:
    python -c "import requests,os; from dotenv import load_dotenv; load_dotenv(); print(requests.post(f'https://api.telegram.org/bot{os.getenv(\"TELEGRAM_BOT_TOKEN\")}/sendMessage', json={'chat_id': os.getenv('TELEGRAM_CHAT_ID'), 'text': 'Test'}).json())"

  Run validation suite:
    python src/validation_suite.py

  Generate synthetic training data:
    python src/simulation/digital_twin.py

  Retrain model:
    python src/train_model.py


════════════════════════════════════════════════════════════════════════════════
  THE ONE THING THAT MATTERS MOST
════════════════════════════════════════════════════════════════════════════════

  Everything else in this plan is technical work. But the most important
  thing is medical validation before this goes anywhere near a real patient.

  The model predicts glucose 30 minutes out. That prediction needs to be
  tested against real CGM data — not synthetic — with accuracy measured
  using MARD (Mean Absolute Relative Difference). Clinical grade is < 10%.

  Do not use this in a live medical context until:
    1. Telegram alerts are verified to actually arrive
    2. The model has been validated on real personal CGM data
    3. A caregiver is also receiving all CRITICAL alerts
    4. The circuit breaker has been tested with data gaps
    5. False positive rate is measured and acceptable

  The code is solid. The math is correct. The safety depends on
  real-world validation that only real data can provide.

================================================================================
  END OF PLAN
================================================================================