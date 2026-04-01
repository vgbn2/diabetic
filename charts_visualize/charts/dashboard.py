"""
Bio-Quant Local Dashboard
Standalone Flask app — no Nightscout, no cloud, no Telegram needed.
Three modes: Manual, Replay, Synthetic.
Run: python dashboard.py
"""

from flask import Flask, jsonify, request, render_template_string
import numpy as np
import json
import math
import random
from datetime import datetime, timezone, timedelta

app = Flask(__name__)

# ── Medical constants (standalone copy) ──────────────────────────────────────
HYPO_CRITICAL   = 2.5
HYPO_WARNING    = 3.9
HYPER_CRITICAL  = 14.0
FAINT_GLUCOSE   = 17.0
PHYSIO_FLOOR    = 2.2
MMOL_TO_MGDL    = 18.018
SAMPLING_MINS   = 2.5
KINEMATIC_DECAY = 90.0
CARB_SENS       = 0.16
TAU_LIQUID      = 15.0
TAU_STARCH      = 60.0

# ── Kalman filter (self-contained, no filterpy needed) ───────────────────────
class SimpleKalman:
    def __init__(self):
        self.x = np.zeros((3, 1))  # [glucose, velocity, acceleration]
        self.P = np.eye(3) * 10.0
        self.P[0, 0] = 1.0
        self.H = np.array([[1.0, 0.0, 0.0]])
        self.R = np.array([[0.25]])
        self.initialized = False
        self.q_var = 1e-5

    def _matrices(self, dt):
        damping = math.exp(-dt / KINEMATIC_DECAY)
        F = np.array([
            [1.0, dt,  0.5 * dt**2],
            [0.0, damping, dt],
            [0.0, 0.0,  damping]
        ])
        Q = np.eye(3) * self.q_var * dt
        return F, Q

    def update(self, value, dt=SAMPLING_MINS):
        if not self.initialized:
            self.x[0, 0] = value
            self.initialized = True
            return float(value), 0.0, 0.0

        F, Q = self._matrices(dt)
        # Predict
        x_pred = F @ self.x
        P_pred = F @ self.P @ F.T + Q
        # Innovation
        y = value - (self.H @ x_pred)[0, 0]
        S = (self.H @ P_pred @ self.H.T)[0, 0] + self.R[0, 0]
        # 3-sigma clamp
        limit = 3.0 * math.sqrt(S)
        if abs(y) > limit:
            y = math.copysign(limit, y)
            value = (self.H @ x_pred)[0, 0] + y
        # Update
        K = P_pred @ self.H.T / S
        self.x = x_pred + K * y
        self.P = (np.eye(3) - K @ self.H) @ P_pred
        return float(self.x[0, 0]), float(self.x[1, 0]), float(self.x[2, 0])

# ── Digital Twin (carb absorption) ───────────────────────────────────────────
def carb_curve(carbs_g, gi_type="STARCH", csf=CARB_SENS, regime_mult=1.0):
    tau = TAU_LIQUID if gi_type.upper() == "LIQUID" else TAU_STARCH
    t = np.arange(0, 240 + SAMPLING_MINS, SAMPLING_MINS)
    impact = (t / tau) * np.exp(1 - t / tau)
    return impact * carbs_g * csf * regime_mult

def project_4h(glucose, velocity, acceleration, meal_carbs=0, gi_type="STARCH",
               meal_elapsed_mins=0, csf=CARB_SENS):
    dt = SAMPLING_MINS
    t = np.arange(0, 240 + dt, dt)
    decay = np.maximum(0, 1.0 - (t / KINEMATIC_DECAY))
    base = glucose + (velocity * t) * decay
    if meal_carbs > 0:
        full = carb_curve(meal_carbs, gi_type, csf)
        start = int(max(0, meal_elapsed_mins // dt))
        segment = full[start: start + len(t)]
        if len(segment) < len(t):
            segment = np.pad(segment, (0, len(t) - len(segment)))
        base = base + segment
    return np.maximum(PHYSIO_FLOOR, base).tolist()

# ── Kinematic predictor ───────────────────────────────────────────────────────
def predict_kinematic_30m(glucose, velocity, acceleration):
    h = 30.0
    damping = 0.95 if abs(velocity) > 0.1 else 1.0
    v_term = velocity * h * damping
    a_term = 0.25 * acceleration * (h ** 2)
    return max(PHYSIO_FLOOR, glucose + v_term + a_term)

# ── Synthetic patient generator ───────────────────────────────────────────────
def generate_synthetic_day(profile="typical"):
    """
    Generates a 24-hour synthetic glucose trace at 5-min resolution.
    Profiles: typical, brittle, dawn_heavy, hypo_prone
    """
    profiles = {
        "typical":     dict(baseline=7.5, noise=0.15, dawn_rise=1.5, meals=[(7,60,"STARCH"),(12,80,"STARCH"),(18,70,"STARCH")]),
        "brittle":     dict(baseline=9.0, noise=0.4,  dawn_rise=2.5, meals=[(8,90,"STARCH"),(13,100,"LIQUID"),(19,85,"STARCH")]),
        "dawn_heavy":  dict(baseline=6.5, noise=0.1,  dawn_rise=4.0, meals=[(7,50,"STARCH"),(12,60,"STARCH"),(18,65,"STARCH")]),
        "hypo_prone":  dict(baseline=6.0, noise=0.2,  dawn_rise=0.8, meals=[(7,40,"STARCH"),(12,50,"LIQUID"),(18,55,"STARCH")]),
    }
    p = profiles.get(profile, profiles["typical"])

    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    points = []
    kf = SimpleKalman()
    twin = {"csf": CARB_SENS, "liquid_tau": TAU_LIQUID, "starch_tau": TAU_STARCH}

    # Build raw glucose trace
    glucose = p["baseline"]
    active_meals = []  # list of (start_idx, curve)
    n_steps = int(24 * 60 / SAMPLING_MINS)

    raw = []
    for i in range(n_steps):
        t_mins = i * SAMPLING_MINS
        t_hour = t_mins / 60.0

        # Dawn phenomenon (4-8 AM rise)
        if 4 <= t_hour <= 8:
            glucose += p["dawn_rise"] / (4 * 60 / SAMPLING_MINS) * 0.8

        # Decay back toward baseline
        glucose += (p["baseline"] - glucose) * 0.008

        # Meal triggers
        for meal_hour, meal_carbs, gi in p["meals"]:
            if abs(t_hour - meal_hour) < SAMPLING_MINS / 60.0:
                tau = TAU_LIQUID if gi == "LIQUID" else TAU_STARCH
                t_arr = np.arange(0, 240 + SAMPLING_MINS, SAMPLING_MINS)
                curve = (t_arr / tau) * np.exp(1 - t_arr / tau) * meal_carbs * twin["csf"]
                active_meals.append((i, curve))

        # Add meal absorption
        meal_contrib = 0.0
        for start_i, curve in active_meals:
            idx = i - start_i
            if 0 <= idx < len(curve):
                meal_contrib += curve[idx] * (SAMPLING_MINS / 60.0) * 0.18

        glucose += meal_contrib
        glucose += random.gauss(0, p["noise"])
        glucose = max(PHYSIO_FLOOR, min(22.0, glucose))
        raw.append(glucose)

    # Run through Kalman and build output
    kf2 = SimpleKalman()
    for i, g in enumerate(raw):
        ts = now + timedelta(minutes=i * SAMPLING_MINS)
        filt, vel, acc = kf2.update(g)
        pred = predict_kinematic_30m(filt, vel, acc)

        # alert level
        if g < HYPO_CRITICAL:
            alert = "CRITICAL_HYPO"
        elif g < HYPO_WARNING and vel < 0:
            alert = "WARNING_HYPO"
        elif g > HYPER_CRITICAL:
            alert = "CRITICAL_HYPER"
        elif g > FAINT_GLUCOSE and vel > 0.1:
            alert = "FAINT_RISK"
        else:
            alert = None

        points.append({
            "t": ts.isoformat(),
            "t_mins": i * SAMPLING_MINS,
            "raw": round(g, 2),
            "filtered": round(filt, 2),
            "velocity": round(vel, 3),
            "acceleration": round(acc, 4),
            "prediction_30m": round(pred, 2),
            "alert": alert,
            "source": "synthetic"
        })

    return points

# ── Manual simulation state ───────────────────────────────────────────────────
manual_state = {
    "kf": SimpleKalman(),
    "points": [],
    "csf": CARB_SENS,
    "active_meal": None,
    "meal_elapsed": 0,
    "t_mins": 0,
}

def manual_step(glucose_override=None):
    state = manual_state
    if not state["points"]:
        return None

    last = state["points"][-1]
    g = glucose_override if glucose_override is not None else last["filtered"]

    # Add small noise if no override
    if glucose_override is None:
        decay = (7.0 - g) * 0.01
        g = g + decay + random.gauss(0, 0.05)
        if state["active_meal"]:
            curve = carb_curve(
                state["active_meal"]["carbs"],
                state["active_meal"]["gi"],
                state["csf"]
            )
            idx = int(state["meal_elapsed"] / SAMPLING_MINS)
            if idx < len(curve):
                g += curve[idx] * (SAMPLING_MINS / 60.0) * 0.18
            state["meal_elapsed"] += SAMPLING_MINS
            if state["meal_elapsed"] > 240:
                state["active_meal"] = None
                state["meal_elapsed"] = 0

    g = max(PHYSIO_FLOOR, min(25.0, g))
    filt, vel, acc = state["kf"].update(g)
    pred = predict_kinematic_30m(filt, vel, acc)
    state["t_mins"] += SAMPLING_MINS

    meal_carbs = state["active_meal"]["carbs"] if state["active_meal"] else 0
    meal_gi    = state["active_meal"]["gi"]    if state["active_meal"] else "STARCH"
    traj = project_4h(filt, vel, acc, meal_carbs, meal_gi,
                      state["meal_elapsed"], state["csf"])

    if g < HYPO_CRITICAL: alert = "CRITICAL_HYPO"
    elif pred < HYPO_WARNING and vel < 0: alert = "WARNING_HYPO"
    elif g > HYPER_CRITICAL: alert = "CRITICAL_HYPER"
    elif g > FAINT_GLUCOSE and vel > 0.1: alert = "FAINT_RISK"
    else: alert = None

    pt = {
        "t_mins": state["t_mins"],
        "raw": round(g, 2),
        "filtered": round(filt, 2),
        "velocity": round(vel, 3),
        "acceleration": round(acc, 4),
        "prediction_30m": round(pred, 2),
        "trajectory_4h": traj,
        "alert": alert,
        "source": "manual"
    }
    state["points"].append(pt)
    # Keep last 288 points (24h)
    if len(state["points"]) > 288:
        state["points"] = state["points"][-288:]
    return pt

# ── Replay state ──────────────────────────────────────────────────────────────
replay_state = {"points": [], "index": 0, "processed": []}

# ── Live state (from StatelessPush) ───────────────────────────────────────────
live_state = {"points": [], "last_update": None}

def process_replay():
    kf = SimpleKalman()
    out = []
    for i, pt in enumerate(replay_state["points"]):
        filt, vel, acc = kf.update(pt["raw"])
        pred = predict_kinematic_30m(filt, vel, acc)
        if pt["raw"] < HYPO_CRITICAL: alert = "CRITICAL_HYPO"
        elif pred < HYPO_WARNING and vel < 0: alert = "WARNING_HYPO"
        elif pt["raw"] > HYPER_CRITICAL: alert = "CRITICAL_HYPER"
        elif pt["raw"] > FAINT_GLUCOSE and vel > 0.1: alert = "FAINT_RISK"
        else: alert = None
        out.append({
            "t_mins": i * SAMPLING_MINS,
            "t": pt.get("t", ""),
            "raw": round(pt["raw"], 2),
            "filtered": round(filt, 2),
            "velocity": round(vel, 3),
            "acceleration": round(acc, 4),
            "prediction_30m": round(pred, 2),
            "alert": alert,
            "source": "replay"
        })
    replay_state["processed"] = out

# ── API routes ────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template_string(HTML)

# --- Manual mode ---
@app.route("/api/manual/init", methods=["POST"])
def manual_init():
    data = request.json
    glucose = float(data.get("glucose", 7.0))
    manual_state["kf"] = SimpleKalman()
    manual_state["points"] = []
    manual_state["csf"] = float(data.get("csf", CARB_SENS))
    manual_state["active_meal"] = None
    manual_state["meal_elapsed"] = 0
    manual_state["t_mins"] = 0
    filt, vel, acc = manual_state["kf"].update(glucose)
    pt = {
        "t_mins": 0,
        "raw": round(glucose, 2),
        "filtered": round(filt, 2),
        "velocity": 0.0,
        "acceleration": 0.0,
        "prediction_30m": round(glucose, 2),
        "trajectory_4h": project_4h(filt, vel, acc),
        "alert": None,
        "source": "manual"
    }
    manual_state["points"].append(pt)
    return jsonify({"status": "ok", "point": pt})

@app.route("/api/manual/step", methods=["POST"])
def manual_step_route():
    data = request.json or {}
    override = data.get("glucose")
    if override is not None:
        override = float(override)
    pt = manual_step(override)
    if pt is None:
        return jsonify({"error": "not initialised"}), 400
    return jsonify({"status": "ok", "point": pt, "history": manual_state["points"]})

@app.route("/api/manual/meal", methods=["POST"])
def manual_meal():
    data = request.json
    manual_state["active_meal"] = {
        "carbs": float(data.get("carbs", 60)),
        "gi": data.get("gi", "STARCH")
    }
    manual_state["meal_elapsed"] = 0
    return jsonify({"status": "ok"})

@app.route("/api/manual/history")
def manual_history():
    return jsonify(manual_state["points"])

# --- Replay mode ---
@app.route("/api/replay/load", methods=["POST"])
def replay_load():
    data = request.json
    entries = data.get("entries", [])
    parsed = []
    for e in entries:
        raw = float(e.get("sgv", e.get("raw", 0)))
        if raw > 30:  # mg/dL
            raw = raw / MMOL_TO_MGDL
        parsed.append({"raw": raw, "t": e.get("dateString", e.get("t", ""))})
    replay_state["points"] = parsed
    replay_state["index"] = 0
    process_replay()
    return jsonify({"status": "ok", "count": len(parsed)})

@app.route("/api/replay/data")
def replay_data():
    return jsonify(replay_state["processed"])

# --- Synthetic mode ---
@app.route("/api/synthetic/generate", methods=["POST"])
def synthetic_generate():
    data = request.json or {}
    profile = data.get("profile", "typical")
    points = generate_synthetic_day(profile)
    return jsonify({"status": "ok", "points": points, "count": len(points)})

# --- Live mode (Push Receiver) ---
@app.route("/api/push", methods=["POST"])
def live_push():
    data = request.json
    if not data or "snapshot" not in data:
        return jsonify({"error": "invalid payload"}), 400
    
    snap = data["snapshot"]
    pred = data.get("prediction", 0)
    
    # Map back to dashboard internal format
    pt = {
        "t": snap.get("glucose", {}).get("timestamp", datetime.now(timezone.utc).isoformat()),
        "t_mins": 0, # Live doesn't use relative t_mins
        "raw": snap.get("glucose", {}).get("value", 0),
        "filtered": snap.get("filtered_value", 0),
        "velocity": snap.get("velocity", 0),
        "acceleration": snap.get("acceleration", 0),
        "prediction_30m": pred,
        "alert": None, # Engine handles alerts, but we can visualize thresholds
        "source": "live"
    }

    # Internal alert check for dashboard colors
    if pt["raw"] < HYPO_CRITICAL: pt["alert"] = "CRITICAL_HYPO"
    elif pt["prediction_30m"] < HYPO_WARNING and pt["velocity"] < 0: pt["alert"] = "WARNING_HYPO"
    elif pt["raw"] > HYPER_CRITICAL: pt["alert"] = "CRITICAL_HYPER"
    elif pt["raw"] > FAINT_GLUCOSE and pt["velocity"] > 0.1: pt["alert"] = "FAINT_RISK"

    live_state["points"].append(pt)
    live_state["last_update"] = datetime.now(timezone.utc).isoformat()
    
    # Cap at 288 readings (24h)
    if len(live_state["points"]) > 288:
        live_state["points"].pop(0)
        
    return jsonify({"status": "ok"})

@app.route("/api/live/data")
def live_data():
    return jsonify({
        "points": live_state["points"],
        "last_update": live_state["last_update"]
    })

# --- Shared stats ---
@app.route("/api/stats", methods=["POST"])
def compute_stats():
    data = request.json
    points = data.get("points", [])
    if not points:
        return jsonify({})
    vals = [p["filtered"] for p in points]
    time_in_range = sum(1 for v in vals if HYPO_WARNING <= v <= 10.0) / len(vals) * 100
    time_high = sum(1 for v in vals if v > 10.0) / len(vals) * 100
    time_low  = sum(1 for v in vals if v < HYPO_WARNING) / len(vals) * 100
    alerts = [p for p in points if p.get("alert")]
    return jsonify({
        "mean": round(np.mean(vals), 2),
        "std": round(np.std(vals), 2),
        "min": round(min(vals), 2),
        "max": round(max(vals), 2),
        "tir": round(time_in_range, 1),
        "time_high": round(time_high, 1),
        "time_low": round(time_low, 1),
        "alert_count": len(alerts),
        "n": len(vals)
    })

# ── HTML Dashboard ────────────────────────────────────────────────────────────
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Bio-Quant Local Dashboard</title>
<script src="https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"></script>
<style>
  @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@300;400;600&family=Syne:wght@400;700;800&display=swap');

  :root {
    --bg:       #0b0e14;
    --bg2:      #111520;
    --bg3:      #181d2a;
    --border:   #232840;
    --cyan:     #00e5ff;
    --green:    #00ff88;
    --amber:    #ffb700;
    --red:      #ff3d5a;
    --purple:   #9b7cff;
    --text:     #c8d0e0;
    --muted:    #5a6080;
    --font-ui:  'Syne', sans-serif;
    --font-mono:'JetBrains Mono', monospace;
  }

  * { margin: 0; padding: 0; box-sizing: border-box; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 13px;
    min-height: 100vh;
  }

  header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 14px 24px;
    border-bottom: 1px solid var(--border);
    background: var(--bg2);
  }

  .logo {
    font-family: var(--font-ui);
    font-weight: 800;
    font-size: 18px;
    letter-spacing: -0.5px;
    color: var(--cyan);
  }
  .logo span { color: var(--muted); font-weight: 400; font-size: 13px; margin-left: 10px; }

  .mode-tabs { display: flex; gap: 4px; }
  .mode-tab {
    padding: 6px 16px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--muted);
    font-family: var(--font-mono);
    font-size: 12px;
    cursor: pointer;
    border-radius: 4px;
    transition: all .15s;
  }
  .mode-tab.active { background: var(--cyan); color: var(--bg); border-color: var(--cyan); font-weight: 600; }
  .mode-tab:hover:not(.active) { border-color: var(--cyan); color: var(--cyan); }

  .layout {
    display: grid;
    grid-template-columns: 260px 1fr;
    grid-template-rows: auto 1fr;
    height: calc(100vh - 53px);
  }

  .sidebar {
    grid-row: 1 / 3;
    border-right: 1px solid var(--border);
    background: var(--bg2);
    overflow-y: auto;
    padding: 16px;
    display: flex;
    flex-direction: column;
    gap: 16px;
  }

  .panel {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
  }

  .panel-title {
    font-family: var(--font-ui);
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 12px;
  }

  label { display: block; color: var(--muted); font-size: 11px; margin-bottom: 4px; margin-top: 10px; }
  label:first-of-type { margin-top: 0; }

  input[type=number], input[type=range], select {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 12px;
    padding: 6px 8px;
    border-radius: 4px;
    outline: none;
  }
  input[type=number]:focus, select:focus { border-color: var(--cyan); }

  input[type=range] { padding: 0; cursor: pointer; accent-color: var(--cyan); }

  .btn {
    display: block;
    width: 100%;
    padding: 8px;
    margin-top: 10px;
    border: 1px solid var(--border);
    background: transparent;
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 12px;
    cursor: pointer;
    border-radius: 4px;
    transition: all .15s;
    text-align: center;
  }
  .btn:hover { background: var(--bg); border-color: var(--cyan); color: var(--cyan); }
  .btn.primary { background: var(--cyan); color: var(--bg); border-color: var(--cyan); font-weight: 600; }
  .btn.primary:hover { background: #00ccee; }
  .btn.danger { border-color: var(--red); color: var(--red); }
  .btn.danger:hover { background: var(--red); color: var(--bg); }

  .metrics-bar {
    padding: 12px 24px;
    border-bottom: 1px solid var(--border);
    display: flex;
    gap: 32px;
    align-items: center;
    background: var(--bg2);
    flex-wrap: wrap;
  }

  .metric { display: flex; flex-direction: column; gap: 2px; }
  .metric-val {
    font-family: var(--font-ui);
    font-size: 22px;
    font-weight: 700;
    line-height: 1;
  }
  .metric-lbl { font-size: 10px; color: var(--muted); letter-spacing: 1px; text-transform: uppercase; }
  .metric-val.ok    { color: var(--green); }
  .metric-val.warn  { color: var(--amber); }
  .metric-val.crit  { color: var(--red); }
  .metric-val.info  { color: var(--cyan); }

  .alert-badge {
    padding: 4px 12px;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.5px;
    font-family: var(--font-ui);
  }
  .alert-CRITICAL_HYPO   { background: #ff3d5a22; border: 1px solid var(--red);    color: var(--red); }
  .alert-WARNING_HYPO    { background: #ffb70022; border: 1px solid var(--amber);   color: var(--amber); }
  .alert-CRITICAL_HYPER  { background: #ff3d5a22; border: 1px solid var(--red);    color: var(--red); }
  .alert-FAINT_RISK      { background: #9b7cff22; border: 1px solid var(--purple);  color: var(--purple); }
  .alert-none            { background: #00ff8822; border: 1px solid var(--green);   color: var(--green); }

  .chart-area {
    padding: 16px 24px;
    display: flex;
    flex-direction: column;
    gap: 16px;
    overflow-y: auto;
  }

  .chart-wrap {
    background: var(--bg2);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px;
    position: relative;
  }
  .chart-label {
    font-size: 10px;
    color: var(--muted);
    letter-spacing: 1.5px;
    text-transform: uppercase;
    margin-bottom: 10px;
    font-family: var(--font-ui);
    font-weight: 700;
  }

  .stats-grid {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 10px;
  }
  .stat-box {
    background: var(--bg3);
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 12px;
    text-align: center;
  }
  .stat-val { font-size: 20px; font-weight: 700; font-family: var(--font-ui); color: var(--cyan); }
  .stat-lbl { font-size: 10px; color: var(--muted); margin-top: 2px; text-transform: uppercase; letter-spacing: 1px; }

  .section { display: none; }
  .section.active { display: contents; }

  .file-drop {
    border: 2px dashed var(--border);
    border-radius: 6px;
    padding: 16px;
    text-align: center;
    color: var(--muted);
    font-size: 11px;
    cursor: pointer;
    transition: border-color .15s;
  }
  .file-drop:hover { border-color: var(--cyan); color: var(--cyan); }

  textarea {
    width: 100%;
    background: var(--bg);
    border: 1px solid var(--border);
    color: var(--text);
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 8px;
    border-radius: 4px;
    resize: vertical;
    outline: none;
    min-height: 80px;
  }
  textarea:focus { border-color: var(--cyan); }

  .step-controls { display: flex; gap: 6px; }
  .step-controls .btn { margin-top: 0; }

  #auto-running { color: var(--green); font-size: 11px; display: none; }

  ::-webkit-scrollbar { width: 4px; height: 4px; }
  ::-webkit-scrollbar-track { background: var(--bg); }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 2px; }
</style>
</head>
<body>

<header>
  <div class="logo">Bio-Quant <span>local simulation dashboard</span></div>
  <div class="mode-tabs">
    <button class="mode-tab active" onclick="switchMode('manual')">Manual</button>
    <button class="mode-tab" onclick="switchMode('replay')">Replay</button>
    <button class="mode-tab" onclick="switchMode('synthetic')">Synthetic</button>
    <button class="mode-tab" onclick="switchMode('live')">Live Engine</button>
  </div>
</header>

<div class="layout">

  <!-- SIDEBAR -->
  <aside class="sidebar">

    <!-- MANUAL CONTROLS -->
    <div id="sidebar-manual">
      <div class="panel">
        <div class="panel-title">Initialise</div>
        <label>Starting glucose (mmol/L)</label>
        <input type="number" id="init-glucose" value="7.5" step="0.1" min="2.2" max="22">
        <label>Carb sensitivity (CSF)</label>
        <input type="number" id="init-csf" value="0.16" step="0.01" min="0.05" max="0.5">
        <button class="btn primary" onclick="manualInit()">Initialise</button>
      </div>

      <div class="panel">
        <div class="panel-title">Step Forward</div>
        <label>Override glucose (leave empty = simulate)</label>
        <input type="number" id="step-glucose" placeholder="auto" step="0.1" min="2.2" max="22">
        <div class="step-controls" style="margin-top:10px">
          <button class="btn" onclick="manualStep()">+5 min</button>
          <button class="btn" onclick="manualStep(6)">+30 min</button>
          <button class="btn" onclick="autoRun()" id="auto-btn">Auto</button>
        </div>
        <div id="auto-running">● running</div>
      </div>

      <div class="panel">
        <div class="panel-title">Log Meal</div>
        <label>Carbs (g)</label>
        <input type="number" id="meal-carbs" value="60" step="5" min="5" max="200">
        <label>GI Type</label>
        <select id="meal-gi">
          <option value="STARCH">Starch (slow)</option>
          <option value="LIQUID">Liquid / sugar (fast)</option>
        </select>
        <button class="btn" onclick="logMeal()">Log Meal</button>
      </div>
    </div>

    <!-- REPLAY CONTROLS -->
    <div id="sidebar-replay" style="display:none">
      <div class="panel">
        <div class="panel-title">Load Data</div>
        <div class="file-drop" onclick="document.getElementById('file-input').click()">
          Click to load JSON file<br><small>Nightscout format (sgv + dateString)</small>
        </div>
        <input type="file" id="file-input" accept=".json" style="display:none" onchange="loadFile(event)">
        <div style="margin-top:10px; color:var(--muted); font-size:11px;">Or paste JSON:</div>
        <textarea id="json-paste" placeholder='[{"sgv":150,"dateString":"..."}]'></textarea>
        <button class="btn primary" onclick="loadPasted()">Load</button>
      </div>
    </div>

    <!-- SYNTHETIC CONTROLS -->
    <div id="sidebar-synthetic" style="display:none">
      <div class="panel">
        <div class="panel-title">Patient Profile</div>
        <label>Profile</label>
        <select id="syn-profile">
          <option value="typical">Typical T1D</option>
          <option value="brittle">Brittle / labile</option>
          <option value="dawn_heavy">Dawn phenomenon</option>
          <option value="hypo_prone">Hypo prone</option>
        </select>
        <button class="btn primary" onclick="generateSynthetic()">Generate 24h</button>
      </div>
      <div class="panel" id="syn-info" style="display:none">
        <div class="panel-title">Profile Info</div>
        <div id="syn-info-text" style="color:var(--muted);font-size:11px;line-height:1.7"></div>
      </div>
    </div>

    <!-- LIVE CONTROLS -->
    <div id="sidebar-live" style="display:none">
      <div class="panel">
        <div class="panel-title">Engine Connectivity</div>
        <div id="live-status" style="color:var(--muted);font-size:11px;margin-bottom:10px">Waiting for engine push...</div>
        <div class="panel-title" style="margin-top:15px">Snapshot Health</div>
        <div id="live-health" style="font-size:10px; color:var(--muted)">- No snapshots received yet</div>
      </div>
    </div>

  </aside>

  <!-- METRICS BAR -->
  <div class="metrics-bar">
    <div class="metric">
      <div class="metric-val info" id="m-glucose">--</div>
      <div class="metric-lbl">Glucose mmol/L</div>
    </div>
    <div class="metric">
      <div class="metric-val info" id="m-velocity">--</div>
      <div class="metric-lbl">Velocity /min</div>
    </div>
    <div class="metric">
      <div class="metric-val info" id="m-pred">--</div>
      <div class="metric-lbl">Pred 30m</div>
    </div>
    <div class="metric">
      <div class="metric-val info" id="m-tir">--</div>
      <div class="metric-lbl">Time in Range</div>
    </div>
    <div style="margin-left:auto">
      <span class="alert-badge alert-none" id="alert-badge">NOMINAL</span>
    </div>
  </div>

  <!-- CHART AREA -->
  <div class="chart-area">

    <div class="chart-wrap">
      <div class="chart-label">Glucose trace — raw vs Kalman filtered</div>
      <canvas id="chart-glucose" height="140"></canvas>
    </div>

    <div class="chart-wrap" id="traj-wrap" style="display:none">
      <div class="chart-label">4-hour Digital Twin trajectory</div>
      <canvas id="chart-traj" height="100"></canvas>
    </div>

    <div class="chart-wrap">
      <div class="chart-label">Velocity & acceleration</div>
      <canvas id="chart-kinematics" height="80"></canvas>
    </div>

    <div id="stats-section" style="display:none">
      <div class="chart-label" style="padding:0 0 10px">Session statistics</div>
      <div class="stats-grid" id="stats-grid"></div>
    </div>

  </div>
</div>

<script>
// ── State ─────────────────────────────────────────────────────────────────────
let mode = 'manual';
let history = [];
let autoTimer = null;
let liveTimer = null;
let chartGlucose, chartKinematics, chartTraj;

const HYPO_WARN = 3.9, HYPER_CRIT = 14.0, FAINT = 17.0, HYPO_CRIT = 2.5;

// ── Chart init ────────────────────────────────────────────────────────────────
function initCharts() {
  const common = {
    animation: false,
    responsive: true,
    plugins: { legend: { display: true, labels: { color: '#5a6080', font: { family: 'JetBrains Mono', size: 11 }, boxWidth: 12 } } },
    scales: {
      x: { ticks: { color: '#5a6080', font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: '#1a2030' } },
      y: { ticks: { color: '#5a6080', font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: '#1a2030' } }
    }
  };

  chartGlucose = new Chart(document.getElementById('chart-glucose'), {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Raw', data: [], borderColor: '#5a6080', borderWidth: 1, pointRadius: 0, tension: 0.3 },
      { label: 'Filtered (Kalman)', data: [], borderColor: '#00e5ff', borderWidth: 2, pointRadius: 0, tension: 0.4 },
      { label: 'Prediction 30m', data: [], borderColor: '#ffb700', borderWidth: 1.5, borderDash: [4,4], pointRadius: 0, tension: 0.3 },
      { label: 'Hypo warn', data: [], borderColor: '#ffb70040', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [2,4] },
      { label: 'Hyper crit', data: [], borderColor: '#ff3d5a40', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [2,4] },
    ]},
    options: { ...common, scales: { ...common.scales, y: { ...common.scales.y, min: 2, max: 22 } } }
  });

  chartKinematics = new Chart(document.getElementById('chart-kinematics'), {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Velocity (mmol/L/min)', data: [], borderColor: '#00ff88', borderWidth: 1.5, pointRadius: 0, tension: 0.3, yAxisID: 'y' },
      { label: 'Acceleration', data: [], borderColor: '#9b7cff', borderWidth: 1, pointRadius: 0, tension: 0.3, yAxisID: 'y2' },
    ]},
    options: { ...common, scales: { ...common.scales,
      y:  { ...common.scales.y, position: 'left' },
      y2: { ticks: { color: '#5a6080', font: { family: 'JetBrains Mono', size: 10 } }, grid: { color: 'transparent' }, position: 'right' }
    }}
  });

  chartTraj = new Chart(document.getElementById('chart-traj'), {
    type: 'line',
    data: { labels: [], datasets: [
      { label: 'Trajectory', data: [], borderColor: '#9b7cff', borderWidth: 2, pointRadius: 0, tension: 0.4, fill: { target: 'origin', above: '#9b7cff11' } },
      { label: 'Faint threshold', data: [], borderColor: '#ff3d5a40', borderWidth: 1, pointRadius: 0, fill: false, borderDash: [3,4] },
    ]},
    options: { ...common, scales: { ...common.scales, y: { ...common.scales.y, min: 2, max: 22 } } }
  });
}

// ── Render helpers ────────────────────────────────────────────────────────────
function labelFor(pt) {
  return pt.t ? pt.t.slice(11,16) : `t=${pt.t_mins}m`;
}

function renderHistory(pts) {
  if (!pts.length) return;
  const labels = pts.map(labelFor);
  const raw    = pts.map(p => p.raw);
  const filt   = pts.map(p => p.filtered);
  const pred   = pts.map(p => p.prediction_30m);
  const hypo   = pts.map(() => HYPO_WARN);
  const hyper  = pts.map(() => HYPER_CRIT);

  chartGlucose.data.labels = labels;
  chartGlucose.data.datasets[0].data = raw;
  chartGlucose.data.datasets[1].data = filt;
  chartGlucose.data.datasets[2].data = pred;
  chartGlucose.data.datasets[3].data = hypo;
  chartGlucose.data.datasets[4].data = hyper;
  chartGlucose.update();

  chartKinematics.data.labels = labels;
  chartKinematics.data.datasets[0].data = pts.map(p => p.velocity);
  chartKinematics.data.datasets[1].data = pts.map(p => p.acceleration);
  chartKinematics.update();

  const last = pts[pts.length - 1];
  updateMetrics(last, pts);
}

function renderTrajectory(traj) {
  if (!traj || !traj.length) { document.getElementById('traj-wrap').style.display = 'none'; return; }
  document.getElementById('traj-wrap').style.display = '';
  const step = 2.5;
  const labels = traj.map((_, i) => `+${Math.round(i * step)}m`);
  chartTraj.data.labels = labels;
  chartTraj.data.datasets[0].data = traj;
  chartTraj.data.datasets[1].data = traj.map(() => FAINT);
  chartTraj.update();
}

function updateMetrics(last, all) {
  const g = last.filtered;
  const gEl = document.getElementById('m-glucose');
  gEl.textContent = g.toFixed(1);
  gEl.className = 'metric-val ' + (g < HYPO_WARN ? 'crit' : g > HYPER_CRIT ? 'crit' : g > FAINT ? 'warn' : 'ok');

  const v = last.velocity;
  const vEl = document.getElementById('m-velocity');
  vEl.textContent = (v >= 0 ? '+' : '') + v.toFixed(3);
  vEl.className = 'metric-val ' + (Math.abs(v) > 0.1 ? 'warn' : 'info');

  document.getElementById('m-pred').textContent = last.prediction_30m.toFixed(1);

  // TIR
  if (all.length > 1) {
    const tir = all.filter(p => p.filtered >= HYPO_WARN && p.filtered <= 10.0).length / all.length * 100;
    document.getElementById('m-tir').textContent = tir.toFixed(0) + '%';
  }

  const alert = last.alert;
  const badge = document.getElementById('alert-badge');
  badge.textContent = alert || 'NOMINAL';
  badge.className = 'alert-badge ' + (alert ? `alert-${alert}` : 'alert-none');
}

async function fetchStats(pts) {
  if (pts.length < 5) return;
  const res = await fetch('/api/stats', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ points: pts }) });
  const s = await res.json();
  document.getElementById('stats-section').style.display = '';
  document.getElementById('stats-grid').innerHTML = `
    <div class="stat-box"><div class="stat-val">${s.mean}</div><div class="stat-lbl">Mean mmol/L</div></div>
    <div class="stat-box"><div class="stat-val" style="color:var(--green)">${s.tir}%</div><div class="stat-lbl">Time in Range</div></div>
    <div class="stat-box"><div class="stat-val" style="color:var(--amber)">${s.time_high}%</div><div class="stat-lbl">Time High</div></div>
    <div class="stat-box"><div class="stat-val" style="color:var(--red)">${s.time_low}%</div><div class="stat-lbl">Time Low</div></div>
    <div class="stat-box"><div class="stat-val">${s.std}</div><div class="stat-lbl">Std Dev</div></div>
    <div class="stat-box"><div class="stat-val">${s.min} – ${s.max}</div><div class="stat-lbl">Range</div></div>
    <div class="stat-box"><div class="stat-val" style="color:var(--red)">${s.alert_count}</div><div class="stat-lbl">Alerts</div></div>
    <div class="stat-box"><div class="stat-val">${s.n}</div><div class="stat-lbl">Data Points</div></div>
  `;
}

// ── Manual mode ───────────────────────────────────────────────────────────────
async function manualInit() {
  const g = parseFloat(document.getElementById('init-glucose').value);
  const csf = parseFloat(document.getElementById('init-csf').value);
  stopAuto();
  history = [];
  const res = await fetch('/api/manual/init', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ glucose: g, csf }) });
  const d = await res.json();
  history = [d.point];
  renderHistory(history);
  renderTrajectory(d.point.trajectory_4h);
}

async function manualStep(n = 1) {
  const gInput = document.getElementById('step-glucose').value;
  const override = gInput ? parseFloat(gInput) : null;
  for (let i = 0; i < n; i++) {
    const res = await fetch('/api/manual/step', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ glucose: override }) });
    const d = await res.json();
    history = d.history;
  }
  renderHistory(history);
  if (history.length) renderTrajectory(history[history.length-1].trajectory_4h);
  if (history.length % 12 === 0) fetchStats(history);
}

function autoRun() {
  if (autoTimer) { stopAuto(); return; }
  document.getElementById('auto-btn').textContent = 'Stop';
  document.getElementById('auto-running').style.display = '';
  autoTimer = setInterval(() => manualStep(1), 800);
}
function stopAuto() {
  if (autoTimer) { clearInterval(autoTimer); autoTimer = null; }
  document.getElementById('auto-btn').textContent = 'Auto';
  document.getElementById('auto-running').style.display = 'none';
}

async function logMeal() {
  const carbs = parseFloat(document.getElementById('meal-carbs').value);
  const gi = document.getElementById('meal-gi').value;
  await fetch('/api/manual/meal', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ carbs, gi }) });
}

// ── Replay mode ───────────────────────────────────────────────────────────────
async function loadEntries(entries) {
  const res = await fetch('/api/replay/load', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ entries }) });
  const d = await res.json();
  if (d.count) {
    const r2 = await fetch('/api/replay/data');
    const pts = await r2.json();
    history = pts;
    renderHistory(pts);
    document.getElementById('traj-wrap').style.display = 'none';
    fetchStats(pts);
  }
}

function loadFile(evt) {
  const file = evt.target.files[0];
  if (!file) return;
  const reader = new FileReader();
  reader.onload = e => {
    try { loadEntries(JSON.parse(e.target.result)); }
    catch { alert('Invalid JSON'); }
  };
  reader.readAsText(file);
}

function loadPasted() {
  const txt = document.getElementById('json-paste').value.trim();
  if (!txt) return;
  try { loadEntries(JSON.parse(txt)); }
  catch { alert('Invalid JSON'); }
}

// ── Synthetic mode ────────────────────────────────────────────────────────────
const profileInfo = {
  typical:    'Baseline ~7.5 mmol/L. Moderate dawn rise (+1.5). Three standard meals. Low noise.',
  brittle:    'Baseline ~9.0 mmol/L. Large meal spikes. High variability. Dawn rise +2.5.',
  dawn_heavy: 'Baseline ~6.5 mmol/L. Strong dawn phenomenon (+4.0). Stable otherwise.',
  hypo_prone: 'Baseline ~6.0 mmol/L. Frequent low excursions. Minimal dawn. Small meals.'
};

async function generateSynthetic() {
  const profile = document.getElementById('syn-profile').value;
  const res = await fetch('/api/synthetic/generate', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ profile }) });
  const d = await res.json();
  history = d.points;
  renderHistory(d.points);
  document.getElementById('traj-wrap').style.display = 'none';
  fetchStats(d.points);
  document.getElementById('syn-info').style.display = '';
  document.getElementById('syn-info-text').textContent = profileInfo[profile] || '';
}

// ── Mode switching ────────────────────────────────────────────────────────────
function switchMode(m) {
  stopAuto();
  mode = m;
  document.querySelectorAll('.mode-tab').forEach((t, i) => {
    t.classList.toggle('active', ['manual','replay','synthetic'][i] === m);
  });
  document.getElementById('sidebar-manual').style.display    = m === 'manual'    ? '' : 'none';
  document.getElementById('sidebar-replay').style.display    = m === 'replay'    ? '' : 'none';
  document.getElementById('sidebar-synthetic').style.display = m === 'synthetic' ? '' : 'none';
  document.getElementById('sidebar-live').style.display      = m === 'live'      ? '' : 'none';
  
  if (m === 'live') {
    startLive();
  } else {
    stopLive();
  }

  history = [];
  chartGlucose.data.labels = []; chartGlucose.data.datasets.forEach(d => d.data = []); chartGlucose.update();
  chartKinematics.data.labels = []; chartKinematics.data.datasets.forEach(d => d.data = []); chartKinematics.update();
  document.getElementById('traj-wrap').style.display = 'none';
  document.getElementById('stats-section').style.display = 'none';
  document.getElementById('m-glucose').textContent = '--';
  document.getElementById('m-velocity').textContent = '--';
  document.getElementById('m-pred').textContent = '--';
  document.getElementById('m-tir').textContent = '--';
  document.getElementById('alert-badge').textContent = 'NOMINAL';
  document.getElementById('alert-badge').className = 'alert-badge alert-none';
}

async function startLive() {
  if (liveTimer) return;
  liveTimer = setInterval(async () => {
    const res = await fetch('/api/live/data');
    const d = await res.json();
    if (d.points && d.points.length) {
      history = d.points;
      renderHistory(history);
      document.getElementById('live-status').textContent = 'Connected. Last push: ' + d.last_update.slice(11,19);
      document.getElementById('live-status').style.color = 'var(--green)';
      document.getElementById('live-health').textContent = d.points.length + ' snapshots in buffer';
    }
  }, 2000);
}

function stopLive() {
  if (liveTimer) { clearInterval(liveTimer); liveTimer = null; }
}

// ── Init ──────────────────────────────────────────────────────────────────────
initCharts();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    print("\n  Bio-Quant Connect Dashboard")
    print("  Listening for Engine Push at http://localhost:10000/api/push")
    print("  View UI at http://localhost:10000\n")
    app.run(host="0.0.0.0", port=10000, debug=False)