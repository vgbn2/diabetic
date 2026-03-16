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
        'status': getattr(shared_engine, 'last_status', 'STABLE')
    })

def start_api():
    app.run(port=5000, debug=False, use_reloader=False)
